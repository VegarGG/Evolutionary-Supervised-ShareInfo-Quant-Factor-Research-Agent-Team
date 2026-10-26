"""Bounded, authorized registry reads over immutable committed publications."""

import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from qfr_core.contracts.artifacts import ArtifactDefinition
from qfr_core.contracts.publication import (
    ArtifactLineage,
    ArtifactPage,
    FamilyPage,
    LineageEdge,
    LineageNode,
    PublishedArtifact,
)
from qfr_core.data_layer.snapshots import canonical_json

from qfr_registry.policy import RegistryReadPolicy
from qfr_registry.publication import Principal, from_row
from qfr_registry.storage.objects import PayloadStore
from qfr_registry.validation import InvalidPublication


class RegistryNotFound(LookupError):
    pass


def readable(principal: Principal) -> list[str]:
    if (
        not principal.name.strip()
        or not principal.programs
        or not principal.roles.intersection({"reader", "publisher", "evaluator"})
    ):
        raise PermissionError("registry read not authorized")
    return sorted(principal.programs)


class RegistryReader:
    def __init__(
        self, connect: Callable[[], Connection], store: PayloadStore, policy: RegistryReadPolicy
    ):
        self.connect = connect
        self.store = store
        self.policy = policy

    def verified(self, row: dict[str, Any] | None) -> PublishedArtifact:
        if row is None:
            raise RegistryNotFound("registry publication unavailable")
        record = from_row(row)
        definition = record.manifest.model_dump(
            mode="json", include=set(ArtifactDefinition.model_fields), exclude={"family_id"}
        )
        expected = canonical_json(
            {
                "hash_spec": "qfr-publication/1",
                "profile": record.profile,
                "dsl_policy_hash": record.dsl_policy_hash,
                "manifest": definition,
            }
        )
        if (
            row["content_hash"] != record.manifest.content_hash
            or record.payload_digest != record.manifest.content_hash
            or self.store.read(record.payload_digest) != expected
        ):
            raise ValueError("registry publication integrity failure")
        return record

    def get(self, version_id: UUID, principal: Principal) -> PublishedArtifact:
        programs = readable(principal)
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                "SELECT * FROM registry.artifact_versions WHERE id=%s "
                "AND program_id=ANY(%s) AND published_seq IS NOT NULL",
                [version_id, programs],
            ).fetchone()
            if row is None:
                raise RegistryNotFound("registry publication unavailable")
            return self.verified(row)

    def page(
        self, principal: Principal, *, since_seq: int, limit: int, family_id: UUID | None = None
    ) -> ArtifactPage:
        programs = readable(principal)
        if family_id is None and not principal.roles.intersection({"reader", "evaluator"}):
            raise PermissionError("registry listing not authorized")
        if since_seq < 0 or not 1 <= limit <= self.policy.max_page_size:
            raise InvalidPublication("invalid registry page bounds")
        family_filter = " AND family_id=%s" if family_id is not None else ""
        parameters: list[Any] = [programs, since_seq]
        if family_id is not None:
            parameters.append(family_id)
        parameters.append(limit + 1)
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            # Inspect sizes first; never materialize an unbounded page of manifests.
            rows = cur.execute(
                "SELECT id,published_seq,octet_length(payload::text) AS bytes "
                "FROM registry.artifact_versions WHERE program_id=ANY(%s) "
                "AND published_seq>%s" + family_filter + " ORDER BY published_seq LIMIT %s",
                parameters,
            ).fetchall()
            identities = []
            size = 0
            for row in rows[:limit]:
                estimate = row["bytes"] + 1024
                if size + estimate > self.policy.max_page_bytes:
                    break
                identities.append(row["id"])
                size += estimate
            if rows and not identities:
                raise InvalidPublication("publication exceeds configured page byte bound")
            if not identities:
                return ArtifactPage(items=[], next_cursor=since_seq, has_more=False)
            values = cur.execute(
                "SELECT * FROM registry.artifact_versions WHERE id=ANY(%s) ORDER BY published_seq",
                [identities],
            ).fetchall()
            items = [self.verified(value) for value in values]
            return ArtifactPage(
                items=items,
                next_cursor=items[-1].published_seq,
                has_more=len(identities) < len(rows),
            )

    def family(
        self, identity: UUID, principal: Principal, *, since_seq: int, limit: int
    ) -> FamilyPage:
        programs = readable(principal)
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                "SELECT * FROM registry.artifact_families WHERE id=%s AND program_id=ANY(%s)",
                [identity, programs],
            ).fetchone()
            if row is None:
                raise RegistryNotFound("registry family unavailable")
        return FamilyPage(
            family_id=str(identity),
            program_id=row["program_id"],
            kind=row["kind"],
            name=row["name"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            versions=self.page(principal, since_seq=since_seq, limit=limit, family_id=identity),
        )

    def payload(
        self, identity: UUID, asset_id: str, principal: Principal
    ) -> tuple[bytes, str, str]:
        record = self.get(identity, principal)
        for declared in record.manifest.payload_files:
            if declared.asset_id == asset_id:
                if not re.fullmatch(
                    r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", declared.media_type
                ):
                    raise ValueError("invalid stored payload media type")
                return self.store.read(declared.sha256), declared.media_type, declared.sha256
        raise RegistryNotFound("registry payload unavailable")

    def lineage(self, identity: UUID, principal: Principal, *, depth: int) -> ArtifactLineage:
        if not 0 <= depth <= self.policy.max_lineage_depth:
            raise InvalidPublication("invalid lineage depth")
        root = self.get(identity, principal)
        program = root.manifest.provenance.program_id
        seen = {identity}
        frontier = {identity}
        edges: dict[tuple[UUID, UUID], LineageEdge] = {}
        truncated = False
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            for distance in range(depth + 1):
                if not frontier:
                    break
                rows = cur.execute(
                    "SELECT p.version_id,p.parent_version_id,p.relation "
                    "FROM registry.artifact_parents p "
                    "JOIN registry.artifact_versions v ON v.id=p.version_id "
                    "WHERE v.program_id=%s "
                    "AND (p.version_id=ANY(%s) OR p.parent_version_id=ANY(%s)) "
                    "ORDER BY p.version_id,p.parent_version_id LIMIT %s",
                    [
                        program,
                        sorted(frontier),
                        sorted(frontier),
                        self.policy.max_lineage_edges + 1,
                    ],
                ).fetchall()
                if len(rows) > self.policy.max_lineage_edges:
                    raise InvalidPublication("lineage edge bound exceeded")
                next_frontier = set()
                for row in rows:
                    edge_nodes = {row["version_id"], row["parent_version_id"]}
                    if distance == depth and not edge_nodes <= seen:
                        truncated = True
                        continue
                    pair = (row["version_id"], row["parent_version_id"])
                    edges[pair] = LineageEdge(
                        version_id=str(pair[0]),
                        parent_version_id=str(pair[1]),
                        relation=row["relation"],
                    )
                    next_frontier |= edge_nodes - seen
                seen |= next_frontier
                if (
                    len(seen) > self.policy.max_lineage_nodes
                    or len(edges) > self.policy.max_lineage_edges
                ):
                    raise InvalidPublication("lineage resource bound exceeded")
                frontier = next_frontier
            rows = cur.execute(
                "SELECT id,content_hash,family_id,kind,version_no "
                "FROM registry.artifact_versions WHERE id=ANY(%s) ORDER BY published_seq",
                [sorted(seen)],
            ).fetchall()
            nodes = [
                LineageNode(
                    artifact_version_id=str(row["id"]),
                    content_hash=row["content_hash"],
                    family_id=str(row["family_id"]),
                    kind=row["kind"],
                    version_no=row["version_no"],
                )
                for row in rows
            ]
        return ArtifactLineage(
            root_version_id=str(identity),
            depth=depth,
            nodes=nodes,
            edges=[edges[key] for key in sorted(edges)],
            truncated_at_depth=truncated,
        )
