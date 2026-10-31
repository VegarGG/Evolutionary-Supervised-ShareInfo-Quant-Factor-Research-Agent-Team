"""Registry behaviour (PLAN Sections 7.7 to 7.9, 10.4 and 16.5).

Publication: schema validation, declared-versus-parsed checks, server-side hashes,
family and version assignment, lineage with AST diffs and idempotency on content.
Pools: append-only entries and events, written only with the control token and an
approval, except seed imports which carry their setup reference.
Every write is one transaction under the registry write lock and emits an audit row.
"""

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import JsonValue
from qfr_core.composite import normalized_weights, strategy_canonical_hash, strategy_diff
from qfr_core.config import RegistryConfig, canonical_json
from qfr_core.contracts import FactorManifest, PoolEntry, StrategyManifest
from qfr_core.correlation import bind
from qfr_core.dsl import DslLimits, ast_diff, declaration_mismatches, validate
from qfr_core.dsl.diff import parse_fragment
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from qfr_core.registry_api import (
    AddEntryRequest,
    AddEntryResponse,
    AppendEventRequest,
    ApprovalRef,
    FamilyView,
    LineageEdge,
    LineageNode,
    LineageView,
    PoolCounts,
    PoolEntryDetail,
    PoolEvent,
    PoolEventPage,
    PoolPage,
    PublishRequest,
    PublishResponse,
    RegistrySummary,
    VersionPage,
    VersionRecord,
    VersionSummary,
)
from sqlalchemy import text
from sqlalchemy.engine import Connection, RowMapping

from qfr_registry.auth import Role
from qfr_registry.db import Database

Pool = Literal["factor", "strategy"]


class RegistryError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: Sequence[dict[str, JsonValue]] = (),
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, list(details)


def content_hash(manifest: FactorManifest | StrategyManifest) -> str:
    """SHA-256 of the canonical JSON manifest; the request holds no server fields."""
    return hashlib.sha256(canonical_json(manifest.model_dump(mode="json")).encode()).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


VERSION_COLUMNS = """v.version_id, v.family_id, v.version_no, v.kind, v.manifest,
    v.content_hash, v.canonical_hash, v.published_seq, v.published_at, v.publisher,
    v.analysis"""


def _version(row: RowMapping) -> VersionRecord:
    manifest = row["manifest"]
    return VersionRecord.model_validate(
        {
            "version_id": row["version_id"],
            "family_id": row["family_id"],
            "version_no": row["version_no"],
            "kind": row["kind"],
            "name": manifest["name"],
            "content_hash": row["content_hash"],
            "canonical_hash": row["canonical_hash"],
            "published_seq": row["published_seq"],
            "published_at": row["published_at"],
            "publisher": row["publisher"],
            "analysis": row["analysis"],
            "manifest": manifest,
        }
    )


def _entry(row: RowMapping) -> PoolEntry:
    return PoolEntry(
        schema_version="pool_entry/1",
        entry_id=row["entry_id"],
        pool=row["pool"],
        version_id=row["version_id"],
        title=row["title"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        approval_id=row["approval_id"],
        setup_ref=row["setup_ref"],
        status=row["status"],
        approved_tier=row["approved_tier"],
        tags=list(row["tags"]),
        last_event_at=row["last_event_at"],
    )


def _event(row: RowMapping) -> PoolEvent:
    return PoolEvent.model_validate(dict(row) | {"tags": list(row["tags"])})


EVENT_COLUMNS = """pe.event_id, pe.event_seq, pe.entry_id, e.pool, e.version_id, pe.at,
    pe.principal, pe.action, pe.from_status, pe.to_status, pe.approved_tier,
    pe.approval_id, pe.setup_ref, pe.tags, pe.note, pe.request_id"""


class RegistryService:
    def __init__(
        self, db: Database, limits: DslLimits, config: RegistryConfig, logger: JsonLogger
    ) -> None:
        self.db, self.limits, self.config, self.logger = db, limits, config, logger

    # ------------------------------------------------------------------ publication

    def _analyze(
        self, manifest: FactorManifest | StrategyManifest
    ) -> tuple[dict[str, JsonValue], str, str]:
        """Return (analysis, canonical_hash, payload_text); raise 400 on invalid content."""
        if isinstance(manifest, StrategyManifest):
            impl = manifest.implementation
            weights = normalized_weights([c.weight for c in impl.components])
            analysis: dict[str, JsonValue] = {
                "normalized_weights": [
                    {"version_id": str(c.version_id), "sign": int(c.sign), "weight": w}
                    for c, w in zip(impl.components, weights, strict=True)
                ],
            }
            payload = canonical_json(impl.model_dump(mode="json"))
            return analysis, strategy_canonical_hash(impl), payload
        expression = manifest.implementation.expression
        check = validate(expression, self.limits)
        if check.analysis is None:
            error = check.errors[0]
            raise RegistryError(
                400,
                str(error["code"]),
                str(error["message"]),
                [{"field": "manifest.implementation.expression", **error}],
            )
        mismatches = declaration_mismatches(
            check.analysis, manifest.declared.fields_used, manifest.declared.max_lookback_days
        )
        if mismatches:
            raise RegistryError(
                400,
                "DECLARATION_MISMATCH",
                "declared fields or lookback differ from the parsed expression",
                [{"field": "manifest.declared", **m.as_dict()} for m in mismatches],
            )
        # Complexity caps are screening's to enforce (Section 8.4); they are recorded here.
        analysis = check.analysis.model_dump(mode="json") | {
            "static_limit_errors": [dict(e) for e in check.errors]
        }
        return analysis, check.analysis.canonical_hash, expression

    def _family(
        self,
        conn: Connection,
        manifest: FactorManifest | StrategyManifest,
        principal: Role,
        request_id: str,
        now: datetime,
    ) -> tuple[UUID, bool]:
        provenance = manifest.provenance
        if manifest.family_id is None:
            existing = conn.execute(
                text("""SELECT family_id FROM artifact_families WHERE kind = :kind
                        AND program_id IS NOT DISTINCT FROM :program AND name = :name"""),
                {"kind": manifest.kind, "program": provenance.program_id, "name": manifest.name},
            ).scalar()
            if existing is not None:
                raise RegistryError(
                    409,
                    "NAME_CONFLICT",
                    "the name already belongs to a family; publish with its family_id",
                    [{"field": "manifest.name", "family_id": str(existing)}],
                )
            family_id = uuid7()
            conn.execute(
                text("""INSERT INTO artifact_families
                        (family_id, kind, program_id, job_id, name, created_at, created_by,
                         request_id)
                        VALUES (:family_id, :kind, :program, :job, :name, :at, :by, :rid)"""),
                {
                    "family_id": family_id,
                    "kind": manifest.kind,
                    "program": provenance.program_id,
                    "job": provenance.job_id,
                    "name": manifest.name,
                    "at": now,
                    "by": principal,
                    "rid": request_id,
                },
            )
            return family_id, True
        family = (
            conn.execute(
                text("SELECT kind, program_id, name FROM artifact_families WHERE family_id = :f"),
                {"f": manifest.family_id},
            )
            .mappings()
            .first()
        )
        if family is None:
            raise RegistryError(
                400,
                "FAMILY_UNKNOWN",
                "family_id does not name a family",
                [{"field": "manifest.family_id"}],
            )
        if family["kind"] != manifest.kind:
            raise RegistryError(409, "KIND_CONFLICT", "the family holds another artifact kind")
        if family["name"] != manifest.name:
            raise RegistryError(409, "NAME_MISMATCH", "a version must keep its family's name")
        if family["program_id"] != provenance.program_id:
            raise RegistryError(409, "PROGRAM_MISMATCH", "the family belongs to another program")
        return manifest.family_id, False

    def _parents(
        self, conn: Connection, manifest: FactorManifest | StrategyManifest, canonical: str
    ) -> list[dict[str, Any]]:
        ids = manifest.provenance.parent_version_ids
        if len(ids) != len(set(ids)):
            raise RegistryError(
                400,
                "SCHEMA_INVALID",
                "parent versions must be distinct",
                [{"field": "manifest.provenance.parent_version_ids"}],
            )
        rows = {
            row["version_id"]: row
            for row in conn.execute(
                text("""SELECT version_id, kind, manifest, analysis FROM artifact_versions
                        WHERE version_id = ANY(:ids)"""),
                {"ids": list(ids)},
            ).mappings()
        }
        unknown: list[JsonValue] = [str(v) for v in ids if v not in rows]
        if unknown:
            code = (
                "COMPONENT_INVALID" if isinstance(manifest, StrategyManifest) else "PARENT_UNKNOWN"
            )
            raise RegistryError(
                400,
                code,
                "parent versions must be published",
                [{"field": "manifest.provenance.parent_version_ids", "unknown": unknown}],
            )
        edges: list[dict[str, Any]] = []
        if isinstance(manifest, FactorManifest):
            child = parse_fragment(canonical)
            for version_id in ids:
                parent = rows[version_id]
                if parent["kind"] != "factor":
                    raise RegistryError(409, "KIND_CONFLICT", "a factor's parents are factors")
                diff = ast_diff(parse_fragment(parent["analysis"]["canonical"]), child)
                edges.append({"parent": version_id, "relation": "parent", "diff": diff})
            return edges
        components = {c.version_id for c in manifest.implementation.components}
        for version_id in ids:
            parent = rows[version_id]
            if version_id in components:
                if parent["kind"] != "factor":
                    raise RegistryError(
                        400,
                        "COMPONENT_INVALID",
                        "strategy components must be published factor versions",
                        [
                            {
                                "field": "manifest.implementation.components",
                                "version_id": str(version_id),
                            }
                        ],
                    )
                edges.append({"parent": version_id, "relation": "component", "diff": None})
                continue
            if parent["kind"] != "strategy":
                raise RegistryError(
                    409, "KIND_CONFLICT", "a strategy's non-component parents are strategies"
                )
            previous = StrategyManifest.model_validate(parent["manifest"]).implementation
            diff = strategy_diff(previous, manifest.implementation)
            edges.append({"parent": version_id, "relation": "parent", "diff": diff})
        return edges

    def publish(self, request: PublishRequest, principal: Role, request_id: str) -> PublishResponse:
        manifest = request.manifest
        provenance = manifest.provenance
        if principal == "control" and not provenance.is_setup_import:
            raise RegistryError(
                403,
                "CONTROL_SEEDS_ONLY",
                "the control token publishes only setup-import human_seed versions",
            )
        if principal == "publisher" and provenance.is_setup_import:
            raise RegistryError(
                403,
                "SETUP_IMPORT_CONTROL_ONLY",
                "setup imports are published only by the front door's control token",
            )
        digest = content_hash(manifest)
        analysis, canonical, payload = self._analyze(manifest)
        now = datetime.now(UTC)
        with self.db.transaction() as conn:
            existing = (
                conn.execute(
                    text(
                        f"SELECT {VERSION_COLUMNS} FROM artifact_versions v "
                        "WHERE v.content_hash = :h"
                    ),
                    {"h": digest},
                )
                .mappings()
                .first()
            )
            if existing is not None:
                record = _version(existing)
                with bind(version_id=str(record.version_id), family_id=str(record.family_id)):
                    self.logger.logger.info(
                        "artifact_publish_idempotent",
                        outcome="skipped",
                        payload={"content_hash": digest, "publish_key": request.publish_key},
                    )
                return PublishResponse(created=False, version=record)
            reused = conn.execute(
                text("""SELECT version_id FROM artifact_versions
                        WHERE publisher = :p AND publish_key = :k"""),
                {"p": principal, "k": request.publish_key},
            ).scalar()
            if reused is not None:
                raise RegistryError(
                    409,
                    "PUBLISH_KEY_REUSED",
                    "the publish key already published different content",
                    [{"field": "publish_key", "version_id": str(reused)}],
                )
            family_id, created_family = self._family(conn, manifest, principal, request_id, now)
            edges = self._parents(conn, manifest, str(analysis.get("canonical", "")))
            version_no: int = conn.execute(
                text(
                    "SELECT COALESCE(max(version_no), 0) + 1 FROM artifact_versions "
                    "WHERE family_id = :f"
                ),
                {"f": family_id},
            ).scalar_one()
            version_id = uuid7()
            row = (
                conn.execute(
                    text(f"""INSERT INTO artifact_versions AS v
                        (version_id, family_id, version_no, kind, manifest, payload_text,
                         content_hash, canonical_hash, published_at, publisher, publish_key,
                         analysis, request_id)
                        VALUES (:vid, :fid, :no, :kind, CAST(:manifest AS jsonb), :payload,
                                :digest, :canonical, :at, :publisher, :key,
                                CAST(:analysis AS jsonb), :rid)
                        RETURNING {VERSION_COLUMNS}"""),
                    {
                        "vid": version_id,
                        "fid": family_id,
                        "no": version_no,
                        "kind": manifest.kind,
                        "manifest": _json(manifest.model_dump(mode="json")),
                        "payload": payload,
                        "digest": digest,
                        "canonical": canonical,
                        "at": now,
                        "publisher": principal,
                        "key": request.publish_key,
                        "analysis": _json(analysis),
                        "rid": request_id,
                    },
                )
                .mappings()
                .one()
            )
            for edge in edges:
                conn.execute(
                    text("""INSERT INTO artifact_parents
                            (version_id, parent_version_id, relation, ast_diff)
                            VALUES (:v, :p, :r, CAST(:d AS jsonb))"""),
                    {
                        "v": version_id,
                        "p": edge["parent"],
                        "r": edge["relation"],
                        "d": None if edge["diff"] is None else _json(edge["diff"]),
                    },
                )
            self._audit(
                conn,
                principal,
                "VERSION_PUBLISHED",
                request_id,
                now,
                version_id=version_id,
                payload={
                    "family_id": str(family_id),
                    "family_created": created_family,
                    "version_no": version_no,
                    "kind": manifest.kind,
                    "operator": provenance.operator,
                    "content_hash": digest,
                    "canonical_hash": canonical,
                    "publish_key": request.publish_key,
                    "parents": [
                        {"version_id": str(e["parent"]), "relation": e["relation"]} for e in edges
                    ],
                },
            )
        record = _version(row)
        with bind(version_id=str(version_id), family_id=str(family_id)):
            self.logger.logger.info(
                "artifact_published",
                outcome="ok",
                payload={
                    "kind": manifest.kind,
                    "version_no": version_no,
                    "operator": provenance.operator,
                    "content_hash": digest,
                    "canonical_hash": canonical,
                    "published_seq": record.published_seq,
                    "family_created": created_family,
                    "parents": len(edges),
                },
            )
        return PublishResponse(created=True, version=record)

    def _audit(
        self,
        conn: Connection,
        principal: Role,
        action: str,
        request_id: str,
        at: datetime,
        payload: dict[str, JsonValue],
        version_id: UUID | None = None,
        entry_id: UUID | None = None,
    ) -> None:
        conn.execute(
            text("""INSERT INTO registry_events
                    (event_id, at, principal, action, version_id, entry_id, request_id, payload)
                    VALUES (:id, :at, :p, :a, :v, :e, :rid, CAST(:payload AS jsonb))"""),
            {
                "id": uuid7(),
                "at": at,
                "p": principal,
                "a": action,
                "v": version_id,
                "e": entry_id,
                "rid": request_id,
                "payload": _json(payload),
            },
        )

    # ------------------------------------------------------------------ reads

    def get_version(self, version_id: UUID) -> VersionRecord:
        with self.db.read() as conn:
            row = (
                conn.execute(
                    text(
                        f"SELECT {VERSION_COLUMNS} FROM artifact_versions v WHERE v.version_id = :v"
                    ),
                    {"v": version_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise RegistryError(404, "VERSION_NOT_FOUND", "no such version")
        return _version(row)

    def list_versions(self, since_seq: int, limit: int) -> VersionPage:
        with self.db.read() as conn:
            rows = conn.execute(
                text(f"""SELECT {VERSION_COLUMNS} FROM artifact_versions v
                         WHERE v.published_seq > :s ORDER BY v.published_seq LIMIT :n"""),
                {"s": since_seq, "n": limit},
            ).mappings()
            items = [_version(r) for r in rows]
        next_seq = items[-1].published_seq if items else since_seq
        return VersionPage(items=items, next_since_seq=next_seq)

    def summary(self) -> RegistrySummary:
        with self.db.read() as conn:
            totals = (
                conn.execute(
                    text("""SELECT
                        (SELECT count(*) FROM artifact_versions WHERE kind = 'factor') AS f,
                        (SELECT count(*) FROM artifact_versions WHERE kind = 'strategy') AS s,
                        (SELECT count(*) FROM artifact_families) AS families,
                        (SELECT coalesce(max(published_seq), 0) FROM artifact_versions) AS pub,
                        (SELECT coalesce(max(event_seq), 0) FROM pool_events) AS ev""")
                )
                .mappings()
                .one()
            )
            counts: dict[str, dict[str, int]] = {"factor": {}, "strategy": {}}
            for row in conn.execute(
                text("SELECT pool, status, count(*) AS n FROM pool_current_v GROUP BY pool, status")
            ).mappings():
                counts[row["pool"]][row["status"]] = int(row["n"])

        def pool(name: str) -> PoolCounts:
            by_status = counts[name]
            return PoolCounts(**by_status, total=sum(by_status.values()))

        return RegistrySummary(
            factor_versions=int(totals["f"]),
            strategy_versions=int(totals["s"]),
            families=int(totals["families"]),
            factor_pool=pool("factor"),
            strategy_pool=pool("strategy"),
            last_published_seq=int(totals["pub"]),
            last_event_seq=int(totals["ev"]),
        )

    def get_family(self, family_id: UUID) -> FamilyView:
        with self.db.read() as conn:
            family = (
                conn.execute(
                    text("""SELECT family_id, kind, name, program_id, job_id, created_at,
                            created_by FROM artifact_families WHERE family_id = :f"""),
                    {"f": family_id},
                )
                .mappings()
                .first()
            )
            if family is None:
                raise RegistryError(404, "FAMILY_NOT_FOUND", "no such family")
            versions = [
                VersionSummary.model_validate(dict(r))
                for r in conn.execute(
                    text("""SELECT version_id, version_no, content_hash, canonical_hash,
                            published_seq, published_at, publisher FROM artifact_versions
                            WHERE family_id = :f ORDER BY version_no"""),
                    {"f": family_id},
                ).mappings()
            ]
        return FamilyView.model_validate(dict(family) | {"versions": versions})

    def lineage(self, version_id: UUID, depth: int) -> LineageView:
        with self.db.read() as conn:
            if (
                conn.execute(
                    text("SELECT 1 FROM artifact_versions WHERE version_id = :v"), {"v": version_id}
                ).scalar()
                is None
            ):
                raise RegistryError(404, "VERSION_NOT_FOUND", "no such version")
            distance: dict[UUID, int] = {version_id: 0}
            edges: dict[tuple[UUID, UUID], LineageEdge] = {}
            for column, other, sign in (
                ("version_id", "parent_version_id", -1),
                ("parent_version_id", "version_id", 1),
            ):
                frontier = [version_id]
                for level in range(1, depth + 1):
                    if not frontier:
                        break
                    rows = conn.execute(
                        text(f"""SELECT version_id, parent_version_id, relation, ast_diff
                                 FROM artifact_parents WHERE {column} = ANY(:ids)
                                 ORDER BY version_id, parent_version_id"""),
                        {"ids": frontier},
                    ).mappings()
                    nxt = []
                    for row in rows:
                        edge = LineageEdge.model_validate(dict(row))
                        edges[(edge.version_id, edge.parent_version_id)] = edge
                        node = row[other]
                        if node not in distance:
                            distance[node] = sign * level
                            nxt.append(node)
                    frontier = nxt
            nodes = [
                LineageNode(
                    version_id=r["version_id"],
                    family_id=r["family_id"],
                    version_no=r["version_no"],
                    kind=r["kind"],
                    name=r["manifest"]["name"],
                    operator=r["manifest"]["provenance"]["operator"],
                    canonical_hash=r["canonical_hash"],
                    distance=distance[r["version_id"]],
                )
                for r in conn.execute(
                    text("""SELECT version_id, family_id, version_no, kind, manifest,
                            canonical_hash FROM artifact_versions WHERE version_id = ANY(:ids)"""),
                    {"ids": list(distance)},
                ).mappings()
            ]
        nodes.sort(key=lambda n: (n.distance, str(n.version_id)))
        ordered = [edges[k] for k in sorted(edges, key=lambda k: (str(k[0]), str(k[1])))]
        return LineageView(version_id=version_id, depth=depth, nodes=nodes, edges=ordered)

    def pool_entries(
        self, pool: Pool, status: str | None, limit: int, after: UUID | None
    ) -> PoolPage:
        with self.db.read() as conn:
            rows = conn.execute(
                text("""SELECT * FROM pool_current_v WHERE pool = :pool
                        AND (CAST(:status AS text) IS NULL OR status = :status)
                        AND (CAST(:after AS uuid) IS NULL OR entry_id > :after)
                        ORDER BY entry_id LIMIT :n"""),
                {"pool": pool, "status": status, "after": after, "n": limit + 1},
            ).mappings()
            items = [_entry(r) for r in rows]
        more = len(items) > limit
        items = items[:limit]
        return PoolPage(items=items, next_cursor=str(items[-1].entry_id) if more else None)

    def pool_events(self, pool: Pool, since_seq: int, limit: int) -> PoolEventPage:
        with self.db.read() as conn:
            items = [
                _event(r)
                for r in conn.execute(
                    text(f"""SELECT {EVENT_COLUMNS} FROM pool_events pe
                             JOIN pool_entries e USING (entry_id)
                             WHERE e.pool = :pool AND pe.event_seq > :s
                             ORDER BY pe.event_seq LIMIT :n"""),
                    {"pool": pool, "s": since_seq, "n": limit},
                ).mappings()
            ]
        next_seq = items[-1].event_seq if items else since_seq
        return PoolEventPage(items=items, next_since_seq=next_seq)

    def _current(self, conn: Connection, pool: Pool, entry_id: UUID) -> PoolEntry:
        row = (
            conn.execute(
                text("SELECT * FROM pool_current_v WHERE pool = :pool AND entry_id = :e"),
                {"pool": pool, "e": entry_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise RegistryError(404, "ENTRY_NOT_FOUND", "no such entry in this pool")
        return _entry(row)

    def _entry_events(self, conn: Connection, entry_id: UUID) -> list[PoolEvent]:
        return [
            _event(r)
            for r in conn.execute(
                text(f"""SELECT {EVENT_COLUMNS} FROM pool_events pe
                         JOIN pool_entries e USING (entry_id)
                         WHERE pe.entry_id = :e ORDER BY pe.event_seq"""),
                {"e": entry_id},
            ).mappings()
        ]

    def pool_entry(self, pool: Pool, entry_id: UUID) -> PoolEntryDetail:
        with self.db.read() as conn:
            entry = self._current(conn, pool, entry_id)
            return PoolEntryDetail(entry=entry, events=self._entry_events(conn, entry_id))

    # ------------------------------------------------------------------ pool writes

    @staticmethod
    def _check_approval(
        approval: ApprovalRef,
        decision: Literal["approve", "retire"],
        pool: Pool,
        version_id: UUID,
        entry_id: UUID | None,
        tier: str | None,
    ) -> None:
        """POOL-01: the approval's scope must cover this write (Section 10.5)."""
        scope = approval.scope
        problems = []
        if approval.decision != decision:
            problems.append(f"decision {approval.decision} does not authorize {decision}")
        covered = version_id in scope.version_ids or (
            entry_id is not None and entry_id in scope.entry_ids
        )
        if not covered:
            problems.append("the scope does not name this version or entry")
        if scope.pool is not None and scope.pool != pool:
            problems.append(f"the scope names the {scope.pool} pool")
        if tier is not None and scope.tier != tier:
            problems.append(f"the scope's tier {scope.tier} differs from {tier}")
        if problems:
            raise RegistryError(
                403,
                "APPROVAL_SCOPE_MISMATCH",
                "the approval does not cover this pool write",
                [{"field": "approval", "problem": p} for p in problems],
            )

    def add_entry(
        self, pool: Pool, request: AddEntryRequest, principal: Role, request_id: str
    ) -> AddEntryResponse:
        now = datetime.now(UTC)
        with self.db.transaction() as conn:
            version = (
                conn.execute(
                    text("SELECT kind, manifest FROM artifact_versions WHERE version_id = :v"),
                    {"v": request.version_id},
                )
                .mappings()
                .first()
            )
            if version is None:
                raise RegistryError(
                    400,
                    "VERSION_UNKNOWN",
                    "the version is not published",
                    [{"field": "version_id"}],
                )
            if version["kind"] != pool:
                raise RegistryError(
                    409, "KIND_POOL_CONFLICT", f"a {version['kind']} cannot enter the {pool} pool"
                )
            if request.status == "seed":
                provenance = version["manifest"]["provenance"]
                if provenance["operator"] != "human_seed" or provenance["job_id"] is not None:
                    raise RegistryError(
                        409,
                        "NOT_A_SETUP_IMPORT",
                        "only setup-import human_seed versions enter a pool as seeds",
                    )
            else:
                assert request.approval is not None
                self._check_approval(
                    request.approval,
                    "approve",
                    pool,
                    request.version_id,
                    None,
                    request.approved_tier,
                )
            existing = conn.execute(
                text("SELECT entry_id FROM pool_entries WHERE pool = :pool AND version_id = :v"),
                {"pool": pool, "v": request.version_id},
            ).scalar()
            if existing is not None:
                first = conn.execute(
                    text("""SELECT to_status FROM pool_events WHERE entry_id = :e
                            AND action = 'ADDED'"""),
                    {"e": existing},
                ).scalar()
                if request.status == "seed" and first == "seed":
                    entry = self._current(conn, pool, existing)
                    with bind(version_id=str(request.version_id)):
                        self.logger.logger.info(
                            "pool_entry_idempotent",
                            outcome="skipped",
                            payload={"pool": pool, "entry_id": str(existing)},
                        )
                    return AddEntryResponse(created=False, entry=entry, event=None)
                raise RegistryError(
                    409,
                    "ENTRY_EXISTS",
                    "the version already has an entry; append an event to change it",
                    [{"entry_id": str(existing)}],
                )
            entry_id = uuid7()
            approval_id = request.approval.approval_id if request.approval else None
            conn.execute(
                text("""INSERT INTO pool_entries
                        (entry_id, pool, version_id, title, created_at, created_by,
                         approval_id, setup_ref, request_id)
                        VALUES (:e, :pool, :v, :title, :at, :by, :a, :s, :rid)"""),
                {
                    "e": entry_id,
                    "pool": pool,
                    "v": request.version_id,
                    "title": request.title,
                    "at": now,
                    "by": principal,
                    "a": approval_id,
                    "s": request.setup_ref,
                    "rid": request_id,
                },
            )
            event = self._insert_event(
                conn,
                entry_id,
                now,
                principal,
                "ADDED",
                None,
                request.status,
                request.approved_tier,
                approval_id,
                request.setup_ref,
                request.tags,
                request.note,
                request_id,
            )
            self._audit(
                conn,
                principal,
                "POOL_ENTRY_ADDED",
                request_id,
                now,
                version_id=request.version_id,
                entry_id=entry_id,
                payload={
                    "pool": pool,
                    "status": request.status,
                    "approved_tier": request.approved_tier,
                    "approval_id": str(approval_id) if approval_id else None,
                    "approval_scope": (
                        request.approval.scope.model_dump(mode="json") if request.approval else None
                    ),
                    "setup_ref": str(request.setup_ref) if request.setup_ref else None,
                    "event_seq": event.event_seq,
                },
            )
            entry = self._current(conn, pool, entry_id)
        with bind(version_id=str(request.version_id)):
            self.logger.logger.info(
                "pool_entry_added",
                outcome="ok",
                payload={
                    "pool": pool,
                    "entry_id": str(entry_id),
                    "status": request.status,
                    "approved_tier": request.approved_tier,
                    "approval_id": str(approval_id) if approval_id else None,
                    "setup_ref": str(request.setup_ref) if request.setup_ref else None,
                    "event_seq": event.event_seq,
                },
            )
        return AddEntryResponse(created=True, entry=entry, event=event)

    def _insert_event(
        self,
        conn: Connection,
        entry_id: UUID,
        at: datetime,
        principal: Role,
        action: str,
        from_status: str | None,
        to_status: str | None,
        tier: str | None,
        approval_id: UUID | None,
        setup_ref: UUID | None,
        tags: list[str],
        note: str | None,
        request_id: str,
    ) -> PoolEvent:
        event_id = uuid7()
        conn.execute(
            text("""INSERT INTO pool_events
                    (event_id, entry_id, at, principal, action, from_status, to_status,
                     approved_tier, approval_id, setup_ref, tags, note, request_id)
                    VALUES (:id, :e, :at, :p, :action, :f, :t, :tier, :a, :s, :tags,
                            :note, :rid)"""),
            {
                "id": event_id,
                "e": entry_id,
                "at": at,
                "p": principal,
                "action": action,
                "f": from_status,
                "t": to_status,
                "tier": tier,
                "a": approval_id,
                "s": setup_ref,
                "tags": sorted(set(tags)),
                "note": note,
                "rid": request_id,
            },
        )
        row = (
            conn.execute(
                text(f"""SELECT {EVENT_COLUMNS} FROM pool_events pe
                         JOIN pool_entries e USING (entry_id) WHERE pe.event_id = :id"""),
                {"id": event_id},
            )
            .mappings()
            .one()
        )
        return _event(row)

    def append_event(
        self,
        pool: Pool,
        entry_id: UUID,
        request: AppendEventRequest,
        principal: Role,
        request_id: str,
    ) -> PoolEvent:
        now = datetime.now(UTC)
        with self.db.transaction() as conn:
            current = self._current(conn, pool, entry_id)
            from_status: str | None = None
            approval_id: UUID | None = None
            if request.action == "STATUS_CHANGED":
                assert request.approval is not None and request.to_status is not None
                decision: Literal["approve", "retire"] = (
                    "approve" if request.to_status == "approved" else "retire"
                )
                self._check_approval(
                    request.approval,
                    decision,
                    pool,
                    current.version_id,
                    entry_id,
                    request.approved_tier,
                )
                if (
                    request.to_status == current.status
                    and request.approved_tier == current.approved_tier
                ):
                    raise RegistryError(
                        409, "STATUS_UNCHANGED", "the entry already has this status and tier"
                    )
                from_status, approval_id = current.status, request.approval.approval_id
            event = self._insert_event(
                conn,
                entry_id,
                now,
                principal,
                request.action,
                from_status,
                request.to_status,
                request.approved_tier,
                approval_id,
                None,
                request.tags,
                request.note,
                request_id,
            )
            self._audit(
                conn,
                principal,
                "POOL_EVENT_APPENDED",
                request_id,
                now,
                version_id=current.version_id,
                entry_id=entry_id,
                payload={
                    "pool": pool,
                    "action": request.action,
                    "from_status": from_status,
                    "to_status": request.to_status,
                    "approved_tier": request.approved_tier,
                    "approval_id": str(approval_id) if approval_id else None,
                    "approval_scope": (
                        request.approval.scope.model_dump(mode="json") if request.approval else None
                    ),
                    "event_seq": event.event_seq,
                },
            )
        with bind(version_id=str(current.version_id)):
            self.logger.logger.info(
                "pool_event_appended",
                outcome="ok",
                payload={
                    "pool": pool,
                    "entry_id": str(entry_id),
                    "action": request.action,
                    "from_status": from_status,
                    "to_status": request.to_status,
                    "approved_tier": request.approved_tier,
                    "approval_id": str(approval_id) if approval_id else None,
                    "event_seq": event.event_seq,
                },
            )
        return event
