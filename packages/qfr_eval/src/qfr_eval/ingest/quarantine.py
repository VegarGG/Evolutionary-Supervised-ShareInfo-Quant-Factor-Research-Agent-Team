"""Private, durable upload/import quarantine with no evaluator database or worker.

Only data-owner CLI processing may turn these references into authorized datasets.
This service exposes metadata, never raw source bytes, to research and MCP.
"""

import hashlib
import json
import os
import sqlite3
import struct
import tempfile
import zipfile
import zlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, cast
from uuid import UUID, uuid4

from qfr_core.access import ServicePrincipal
from qfr_core.contracts.data import AssetReference, SourceAsset
from qfr_core.contracts.transfers import (
    AssetPage,
    IntakeTransportPolicy,
    MountedImportRequest,
    UploadDeclaration,
    UploadStatus,
)
from qfr_core.data_layer.snapshots import canonical_json

from qfr_eval.ingest.quarantine_validation import confined_file, validate_transport


class TransferNotFound(Exception):
    pass


class TransferConflict(Exception):
    pass


def _scope(principal: ServicePrincipal, program: UUID, *, write: bool = False) -> None:
    if principal.audience != "intake" or str(program) not in principal.programs:
        raise TransferNotFound("source unavailable")
    if write and "research_lead" not in principal.roles:
        raise PermissionError("source registration not authorized")


class Quarantine:
    def __init__(self, root: Path, policy: IntakeTransportPolicy, mounts: Mapping[str, Path]):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink() or not root.is_dir():
            raise ValueError("private quarantine directory unavailable")
        self.root, self.policy, self.mounts = root, policy, dict(mounts)
        database = root / "transfers.sqlite3"
        try:
            os.close(os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
        except FileExistsError:
            if database.is_symlink() or not database.is_file():
                raise ValueError("quarantine journal is not a regular file") from None
        self.database = database
        with self.connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS uploads(
              id TEXT PRIMARY KEY, program TEXT NOT NULL, operation_key TEXT NOT NULL,
              request_hash TEXT NOT NULL, declaration TEXT NOT NULL, origin TEXT NOT NULL,
              state TEXT NOT NULL CHECK(state IN ('staging','validated','rejected')),
              reserved_bytes INTEGER NOT NULL, created_at TEXT NOT NULL,
              created_by TEXT NOT NULL, request_id TEXT NOT NULL,
              UNIQUE(program,operation_key));
            CREATE TABLE IF NOT EXISTS chunks(
              upload_id TEXT NOT NULL REFERENCES uploads(id), offset INTEGER NOT NULL,
              sha256 TEXT NOT NULL, body BLOB NOT NULL, PRIMARY KEY(upload_id,offset));
            CREATE TABLE IF NOT EXISTS events(
              id TEXT PRIMARY KEY, upload_id TEXT NOT NULL REFERENCES uploads(id),
              principal TEXT NOT NULL, at TEXT NOT NULL, request_id TEXT NOT NULL,
              action TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS uploads_frozen BEFORE UPDATE ON uploads
              WHEN NEW.id<>OLD.id OR NEW.program<>OLD.program
                OR NEW.operation_key<>OLD.operation_key
                OR NEW.request_hash<>OLD.request_hash OR NEW.declaration<>OLD.declaration
                OR NEW.origin<>OLD.origin OR NEW.reserved_bytes<>OLD.reserved_bytes
                OR NEW.created_at<>OLD.created_at OR NEW.created_by<>OLD.created_by
                OR NEW.request_id<>OLD.request_id
                OR OLD.state<>'staging'
              BEGIN SELECT RAISE(ABORT,'immutable source declaration or terminal state'); END;
            CREATE TRIGGER IF NOT EXISTS uploads_no_delete BEFORE DELETE ON uploads
              BEGIN SELECT RAISE(ABORT,'immutable source history'); END;
            CREATE TRIGGER IF NOT EXISTS chunks_no_update BEFORE UPDATE ON chunks
              BEGIN SELECT RAISE(ABORT,'immutable chunk'); END;
            CREATE TRIGGER IF NOT EXISTS chunks_no_delete BEFORE DELETE ON chunks
              BEGIN SELECT RAISE(ABORT,'immutable chunk history'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
              BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
              BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
            """)

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.database, timeout=self.policy.sqlite_timeout_seconds)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def event(
        conn: sqlite3.Connection,
        identity: UUID,
        principal: ServicePrincipal,
        request_id: UUID,
        action: str,
        detail: str,
    ) -> None:
        conn.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?)",
            [
                str(uuid4()),
                str(identity),
                principal.name,
                datetime.now(UTC).isoformat(),
                str(request_id),
                action,
                detail,
            ],
        )

    @staticmethod
    def row(conn: sqlite3.Connection, program: UUID, identity: UUID) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM uploads WHERE id=? AND program=?", [str(identity), str(program)]
        ).fetchone()
        if not isinstance(row, sqlite3.Row):
            raise TransferNotFound("source unavailable")
        return row

    def status_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> UploadStatus:
        declaration = UploadDeclaration.model_validate_json(row["declaration"])
        received = conn.execute(
            "SELECT coalesce(sum(length(body)),0) FROM chunks WHERE upload_id=?", [row["id"]]
        ).fetchone()[0]
        source = None
        if row["state"] == "validated":
            source = SourceAsset.model_validate(
                {
                    **declaration.model_dump(exclude={"operation_key"}),
                    "reference": json.loads(row["origin"]),
                }
            )
        return UploadStatus(
            upload_id=UUID(row["id"]),
            program_id=UUID(row["program"]),
            state=row["state"],
            bytes_received=received,
            expected_bytes=declaration.bytes,
            chunk_bytes=self.policy.chunk_bytes,
            source=source,
            validation="transport_only",
            execution_authorized=False,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def create(
        self,
        principal: ServicePrincipal,
        program: UUID,
        declaration: UploadDeclaration,
        request_id: UUID,
        *,
        origin: AssetReference | None = None,
    ) -> UploadStatus:
        _scope(principal, program, write=True)
        if (
            len(declaration.model_dump_json().encode()) > self.policy.max_metadata_bytes
            or declaration.bytes > self.policy.max_upload_bytes
            or declaration.media_type not in self.policy.media_types
        ):
            raise ValueError("source exceeds transport policy")
        identity = UUID(
            bytes=hashlib.sha256(f"{program}:{declaration.operation_key}".encode()).digest()[:16],
            version=5,
        )
        origin = origin or AssetReference(transport="finalized_upload", reference_id=str(identity))
        sha = hashlib.sha256(
            canonical_json(
                {
                    "declaration": declaration.model_dump(mode="json"),
                    "origin": origin.model_dump(mode="json"),
                }
            )
        ).hexdigest()
        with self.connection(write=True) as conn:
            old = conn.execute(
                "SELECT * FROM uploads WHERE program=? AND operation_key=?",
                [str(program), declaration.operation_key],
            ).fetchone()
            if old is not None:
                if old["request_hash"] != sha:
                    raise TransferConflict("source key already binds different intent")
                return self.status_row(conn, old)
            count, reserved = conn.execute(
                "SELECT count(*),coalesce(sum(reserved_bytes),0) FROM uploads WHERE program=?",
                [str(program)],
            ).fetchone()
            if (
                count >= self.policy.max_uploads_per_program
                or reserved + declaration.bytes > self.policy.max_reserved_bytes_per_program
            ):
                raise TransferConflict("program source reservation exhausted")
            conn.execute(
                "INSERT INTO uploads VALUES(?,?,?,?,?,?,'staging',?,?,?,?)",
                [
                    str(identity),
                    str(program),
                    declaration.operation_key,
                    sha,
                    declaration.model_dump_json(),
                    origin.model_dump_json(),
                    declaration.bytes,
                    datetime.now(UTC).isoformat(),
                    principal.name,
                    str(request_id),
                ],
            )
            self.event(conn, identity, principal, request_id, "source_declared", sha)
            return self.status_row(conn, self.row(conn, program, identity))

    def status(self, principal: ServicePrincipal, program: UUID, identity: UUID) -> UploadStatus:
        _scope(principal, program)
        with self.connection() as conn:
            return self.status_row(conn, self.row(conn, program, identity))

    def chunk(
        self,
        principal: ServicePrincipal,
        program: UUID,
        identity: UUID,
        offset: int,
        data: bytes,
        sha256: str,
        request_id: UUID,
    ) -> UploadStatus:
        _scope(principal, program, write=True)
        if (
            len(data) > self.policy.chunk_bytes
            or not data
            or hashlib.sha256(data).hexdigest() != sha256
        ):
            raise ValueError("chunk checksum or size differs")
        with self.connection(write=True) as conn:
            row = self.row(conn, program, identity)
            declaration = UploadDeclaration.model_validate_json(row["declaration"])
            if (
                offset < 0
                or offset % self.policy.chunk_bytes
                or len(data) != min(self.policy.chunk_bytes, declaration.bytes - offset)
            ):
                raise ValueError("chunk range differs from declared source")
            previous = conn.execute(
                "SELECT sha256 FROM chunks WHERE upload_id=? AND offset=?", [str(identity), offset]
            ).fetchone()
            if previous is not None:
                if previous[0] != sha256:
                    raise TransferConflict("chunk offset already binds different bytes")
                return self.status_row(conn, row)
            if row["state"] != "staging":
                raise TransferConflict("source is no longer staging")
            conn.execute(
                "INSERT INTO chunks VALUES(?,?,?,?)", [str(identity), offset, sha256, data]
            )
            self.event(
                conn,
                identity,
                principal,
                request_id,
                "chunk_received",
                f"{offset}:{len(data)}:{sha256}",
            )
            return self.status_row(conn, row)

    def finalize(
        self,
        principal: ServicePrincipal,
        program: UUID,
        identity: UUID,
        sha256: str,
        request_id: UUID,
    ) -> UploadStatus:
        _scope(principal, program, write=True)
        with self.connection(write=True) as conn:
            row = self.row(conn, program, identity)
            declaration = UploadDeclaration.model_validate_json(row["declaration"])
            if declaration.sha256 != sha256:
                raise TransferConflict("finalization differs from declared checksum")
            if row["state"] != "staging":
                return self.status_row(conn, row)
            status = self.status_row(conn, row)
            if status.bytes_received != declaration.bytes:
                raise TransferConflict("source chunks incomplete")
            with tempfile.NamedTemporaryFile(
                dir=self.root, prefix="validation-", delete=True
            ) as temporary:
                position = 0
                for item in conn.execute(
                    "SELECT offset,body FROM chunks WHERE upload_id=? ORDER BY offset",
                    [str(identity)],
                ):
                    if position != item[0]:
                        raise TransferConflict("source chunk sequence incomplete")
                    temporary.write(item[1])
                    position += len(item[1])
                temporary.flush()
                os.fsync(temporary.fileno())
                try:
                    validate_transport(cast(BinaryIO, temporary.file), declaration, self.policy)
                except (
                    ValueError,
                    OSError,
                    RecursionError,
                    RuntimeError,
                    EOFError,
                    zipfile.BadZipFile,
                    zipfile.LargeZipFile,
                    zlib.error,
                    struct.error,
                ):
                    conn.execute("UPDATE uploads SET state='rejected' WHERE id=?", [str(identity)])
                    self.event(
                        conn,
                        identity,
                        principal,
                        request_id,
                        "source_rejected",
                        "transport_validation_failed",
                    )
                else:
                    target = self.root / (str(identity) + ".source")
                    if target.exists() or target.is_symlink():
                        # Recover a file committed immediately before a process/DB failure.
                        with confined_file(self.root, target.name) as original:
                            validate_transport(original, declaration, self.policy)
                    else:
                        os.chmod(temporary.name, 0o400)
                        os.link(temporary.name, target)
                        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            os.fsync(directory)
                        finally:
                            os.close(directory)
                    conn.execute("UPDATE uploads SET state='validated' WHERE id=?", [str(identity)])
                    self.event(
                        conn,
                        identity,
                        principal,
                        request_id,
                        "source_validated",
                        declaration.sha256,
                    )
            return self.status_row(conn, self.row(conn, program, identity))

    def import_file(
        self,
        principal: ServicePrincipal,
        program: UUID,
        request: MountedImportRequest,
        request_id: UUID,
    ) -> UploadStatus:
        _scope(principal, program, write=True)
        root = self.mounts.get(request.mount_id)
        if root is None:
            raise TransferNotFound("declared import mount unavailable")
        with confined_file(root, request.relative_path) as source:
            if os.fstat(source.fileno()).st_size != request.declaration.bytes:
                raise ValueError("mounted source size differs")
            status = self.create(
                principal,
                program,
                request.declaration,
                request_id,
                origin=AssetReference(
                    transport="mounted_import",
                    reference_id=request.mount_id,
                    relative_path=request.relative_path,
                ),
            )
            if status.state != "staging":
                return status
            offset = 0
            while data := source.read(self.policy.chunk_bytes):
                if offset + len(data) > request.declaration.bytes:
                    raise ValueError("mounted source grew during import")
                self.chunk(
                    principal,
                    program,
                    status.upload_id,
                    offset,
                    data,
                    hashlib.sha256(data).hexdigest(),
                    request_id,
                )
                offset += len(data)
        return self.finalize(
            principal, program, status.upload_id, request.declaration.sha256, request_id
        )

    def verify(
        self, principal: ServicePrincipal, program: UUID, source: SourceAsset
    ) -> SourceAsset:
        _scope(principal, program)
        # Re-resolve the stored transport metadata, never a caller-supplied filesystem path.
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM uploads WHERE program=? AND state='validated' AND origin=?",
                [str(program), source.reference.model_dump_json()],
            ).fetchall()
            for row in rows:
                status = self.status_row(conn, row)
                if status.source == source:
                    with confined_file(self.root, str(status.upload_id) + ".source") as stream:
                        validate_transport(
                            stream,
                            UploadDeclaration.model_validate_json(row["declaration"]),
                            self.policy,
                        )
                    return source
        raise TransferNotFound("validated source unavailable")

    def page(
        self, principal: ServicePrincipal, program: UUID, *, after: UUID | None, limit: int
    ) -> AssetPage:
        _scope(principal, program)
        if not 1 <= limit <= self.policy.max_uploads_per_program:
            raise ValueError("invalid transfer page size")
        with self.connection() as conn:
            if after is not None:
                self.row(conn, program, after)
            rows = conn.execute(
                "SELECT * FROM uploads WHERE program=? "
                + ("AND id>? " if after else "")
                + "ORDER BY id LIMIT ?",
                [str(program), *([str(after)] if after else []), limit + 1],
            ).fetchall()
            selected = rows[:limit]
            result = AssetPage(
                items=[self.status_row(conn, row) for row in selected],
                next_after_id=UUID(selected[-1]["id"]) if selected else after,
                has_more=len(rows) > limit,
            )
            if len(result.model_dump_json().encode()) > self.policy.max_metadata_bytes:
                raise ValueError("transfer page exceeds bound")
            return result
