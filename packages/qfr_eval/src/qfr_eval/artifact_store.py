"""Private evaluator evidence files, content-addressed and verified on every read."""

import hashlib
import io
import os
import re
import tempfile
from pathlib import Path
from typing import Literal

import polars as pl
from qfr_core.data_layer.snapshots import canonical_json, file_hash, logical_hash, normalize_table

from qfr_eval.records import StoredFile


class EvidenceStore:
    def __init__(self, root: Path):
        if root.is_symlink():
            raise ValueError("evidence root cannot be a symlink")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.stat().st_mode & 0o077:
            raise ValueError("evaluator evidence root must be private (0700)")
        self.root = root.resolve()
        self.objects = self.root / "objects"
        if self.objects.is_symlink():
            raise ValueError("evidence objects cannot be a symlink")
        self.objects.mkdir(mode=0o700, exist_ok=True)
        if self.objects.stat().st_mode & 0o077:
            raise ValueError("evaluator objects must be private (0700)")

    def put(
        self, value: bytes, *, suffix: Literal["json", "parquet", "md"], logical: str | None = None
    ) -> StoredFile:
        digest = hashlib.sha256(value).hexdigest()
        path = self.objects / f"{digest}.{suffix}"
        fd, temporary = tempfile.mkstemp(prefix=".staging-", dir=self.objects)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError:
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or path.stat().st_mode & 0o077
                    or file_hash(path) != digest
                ):
                    raise ValueError(
                        "existing immutable evidence object is corrupt or public"
                    ) from None
        finally:
            Path(temporary).unlink(missing_ok=True)
        media: dict[
            str, Literal["application/json", "application/vnd.apache.parquet", "text/markdown"]
        ] = {
            "json": "application/json",
            "parquet": "application/vnd.apache.parquet",
            "md": "text/markdown",
        }
        return StoredFile(
            sha256=digest,
            bytes=len(value),
            relative_path=str(path.relative_to(self.root)),
            media_type=media[suffix],
            logical_sha256=logical,
        )

    def json(self, value: object) -> StoredFile:
        return self.put(canonical_json(value), suffix="json")

    def table(self, frame: pl.DataFrame, grain: list[str]) -> StoredFile:
        frame = normalize_table(frame, grain)
        buffer = io.BytesIO()
        frame.write_parquet(buffer)
        return self.put(buffer.getvalue(), suffix="parquet", logical=logical_hash(frame, grain))

    def read(self, item: StoredFile) -> bytes:
        if not re.fullmatch(r"objects/[0-9a-f]{64}\.(json|parquet|md)", item.relative_path):
            raise ValueError("invalid evidence path")
        path = self.root / item.relative_path
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("evidence file must be private and regular")
        value = path.read_bytes()
        if len(value) != item.bytes or hashlib.sha256(value).hexdigest() != item.sha256:
            raise ValueError("evidence physical hash mismatch")
        if path.stem != item.sha256:
            raise ValueError("evidence identity differs from path")
        return value

    def read_table(self, item: StoredFile, grain: list[str]) -> pl.DataFrame:
        frame = pl.read_parquet(io.BytesIO(self.read(item)))
        if item.logical_sha256 is None or logical_hash(frame, grain) != item.logical_sha256:
            raise ValueError("evidence logical hash mismatch")
        return frame
