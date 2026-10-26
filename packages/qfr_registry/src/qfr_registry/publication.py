"""Immutable publication transactions; no evaluator imports or notifications."""

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from qfr_core.contracts.artifacts import ArtifactManifest, CompositeImplementation
from qfr_core.contracts.publication import (
    PublicationRequest,
    PublicationResponse,
    PublishedArtifact,
)
from qfr_core.dsl.language import DSLConfig

from qfr_registry.policy import RegistryPolicy
from qfr_registry.storage.objects import PayloadStore
from qfr_registry.validation import InvalidPublication, PublicationConflict, validate


def uuid7() -> UUID:
    """RFC 9562 layout; database publication sequence provides commit ordering."""
    milliseconds = time.time_ns() // 1_000_000
    random = secrets.randbits(74)
    return UUID(
        int=(milliseconds << 80)
        | (7 << 76)
        | ((random >> 62) << 64)
        | (2 << 62)
        | (random & ((1 << 62) - 1))
    )


@dataclass(frozen=True)
class Principal:
    name: str
    roles: frozenset[str]
    programs: frozenset[str]

    def require(self, program: str, *, publish: bool = False) -> None:
        roles = {"publisher"} if publish else {"publisher", "reader", "evaluator"}
        if (
            not self.name.strip()
            or program not in self.programs
            or not self.roles.intersection(roles)
        ):
            raise PermissionError("publication program or role not authorized")


def from_row(row: dict[str, Any] | None) -> PublishedArtifact:
    if row is None:
        raise ValueError("committed publication is missing")
    return PublishedArtifact(
        manifest=ArtifactManifest.model_validate(row["payload"]["manifest"]),
        profile=row["payload"]["profile"],
        version_no=row["version_no"],
        published_seq=row["published_seq"],
        dsl_policy_hash=row["payload"]["dsl_policy_hash"],
        payload_digest=row["payload_digest"],
    )


def audit(conn: Connection, principal: str, request_id: UUID, action: str, entity: UUID) -> None:
    conn.execute(
        "INSERT INTO registry.registry_events(id,payload,created_by,request_id) "
        "VALUES(%s,%s,%s,%s)",
        [
            uuid7(),
            Jsonb({"action": action, "entity_type": "publication", "entity_id": str(entity)}),
            principal,
            request_id,
        ],
    )


class Registry:
    def __init__(
        self,
        connect: Callable[[], Connection],
        store: PayloadStore,
        policy: RegistryPolicy,
        dsl_configs: dict[str, DSLConfig],
    ):
        self.connect = connect
        self.store = store
        self.policy = policy
        self.dsl_configs = dsl_configs

    def publish(
        self, request: PublicationRequest, principal: Principal, request_id: UUID
    ) -> PublicationResponse:
        program = request.manifest.provenance.program_id
        principal.require(program, publish=True)
        checked = validate(request, self.policy, self.dsl_configs)
        with self.connect() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            conn.execute("SELECT pg_advisory_xact_lock(72460302)")
            existing = cur.execute(
                "SELECT request_digest,version_id FROM registry.publication_requests "
                "WHERE created_by=%s AND publish_key=%s",
                [principal.name, request.publish_key],
            ).fetchone()
            if existing:
                if existing["request_digest"] != checked.request_digest:
                    raise PublicationConflict("publish key reused with different content")
                row = cur.execute(
                    "SELECT * FROM registry.artifact_versions WHERE id=%s", [existing["version_id"]]
                ).fetchone()
                audit(conn, principal.name, request_id, "publication_retry", existing["version_id"])
                return PublicationResponse(artifact=from_row(row), created=False)
            row = cur.execute(
                "SELECT * FROM registry.artifact_versions WHERE content_hash=%s",
                [checked.content_hash],
            ).fetchone()
            created = row is None
            if row is None:
                manifest = request.manifest
                parents = []
                for parent_id in manifest.parent_version_ids:
                    parent = cur.execute(
                        "SELECT * FROM registry.artifact_versions WHERE id=%s "
                        "AND published_seq IS NOT NULL",
                        [UUID(parent_id)],
                    ).fetchone()
                    if parent is None or parent["program_id"] != program:
                        raise InvalidPublication("lineage parent unavailable in this program")
                    parents.append(parent)
                if isinstance(manifest.implementation, CompositeImplementation):
                    for component in manifest.implementation.components:
                        try:
                            component_id = UUID(component.artifact.artifact_version_id)
                        except ValueError:
                            raise InvalidPublication("invalid composite reference") from None
                        source = cur.execute(
                            "SELECT content_hash,program_id FROM "
                            "registry.artifact_versions WHERE id=%s",
                            [component_id],
                        ).fetchone()
                        if (
                            source is None
                            or source["program_id"] != program
                            or source["content_hash"] != component.artifact.content_hash
                        ):
                            raise InvalidPublication(
                                "composite reference unavailable or mismatched"
                            )
                if manifest.family_id is None:
                    family = cur.execute(
                        "SELECT id FROM registry.artifact_families WHERE program_id=%s AND name=%s",
                        [program, manifest.name],
                    ).fetchone()
                    if family:
                        raise PublicationConflict(
                            "existing name requires explicit family and lineage"
                        )
                    family_id = uuid7()
                    conn.execute(
                        "INSERT INTO registry.artifact_families"
                        "(id,payload,created_by,request_id,program_id,kind,name) "
                        "VALUES(%s,'{}',%s,%s,%s,%s,%s)",
                        [
                            family_id,
                            principal.name,
                            request_id,
                            program,
                            manifest.kind.value,
                            manifest.name,
                        ],
                    )
                    number = 1
                else:
                    family_id = UUID(manifest.family_id)
                    family = cur.execute(
                        "SELECT * FROM registry.artifact_families WHERE id=%s", [family_id]
                    ).fetchone()
                    if (
                        family is None
                        or family["program_id"] != program
                        or family["kind"] != manifest.kind.value
                    ):
                        raise PublicationConflict("family kind or program mismatch")
                    maximum = cur.execute(
                        "SELECT coalesce(max(version_no),0)+1 AS n FROM "
                        "registry.artifact_versions WHERE family_id=%s",
                        [family_id],
                    ).fetchone()
                    if maximum is None:
                        raise ValueError("family revision query failed")
                    number = maximum["n"]
                    if number > 1 and not any(p["family_id"] == family_id for p in parents):
                        raise InvalidPublication("revision requires a parent from its family")
                version_id = uuid7()
                published = ArtifactManifest.model_validate(
                    {
                        **manifest.model_dump(mode="json"),
                        "family_id": str(family_id),
                        "artifact_version_id": str(version_id),
                        "artifact_id": str(family_id),
                        "content_hash": checked.content_hash,
                        "implementation_fingerprint": checked.implementation_hash,
                        "canonical_fingerprint": checked.canonical_hash,
                        "created_at": datetime.now(UTC),
                        "created_by": principal.name,
                    }
                )
                for data in [checked.bundle, *checked.files.values()]:
                    identity = self.store.put(data)
                    conn.execute(
                        "INSERT INTO registry.payload_objects"
                        "(id,payload,created_by,request_id,sha256,object_ref,size_bytes) "
                        "VALUES(%s,'{}',%s,%s,%s,%s,%s) ON CONFLICT(sha256) DO NOTHING",
                        [uuid7(), principal.name, request_id, identity, identity, len(data)],
                    )
                row = cur.execute(
                    "INSERT INTO registry.artifact_versions"
                    "(id,artifact_version_id,payload,created_by,request_id,content_hash,"
                    "family_id,version_no,program_id,kind,canonical_hash,implementation_hash,"
                    "implementation_kind,payload_ref,payload_digest) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                    [
                        version_id,
                        version_id,
                        Jsonb(
                            {
                                "manifest": published.model_dump(mode="json"),
                                "profile": request.profile,
                                "dsl_policy_hash": checked.dsl_policy_hash,
                                "hash_spec": "qfr-publication/1",
                            }
                        ),
                        principal.name,
                        request_id,
                        checked.content_hash,
                        family_id,
                        number,
                        program,
                        manifest.kind.value,
                        checked.canonical_hash,
                        checked.implementation_hash,
                        manifest.implementation.type,
                        checked.content_hash,
                        checked.content_hash,
                    ],
                ).fetchone()
                relation = {
                    "syntactic_mutation": "mutation",
                    "llm_mutation": "mutation",
                    "explore": "revision",
                }.get(manifest.provenance.operator, manifest.provenance.operator)
                for parent in parents:
                    conn.execute(
                        "INSERT INTO registry.artifact_parents"
                        "(id,payload,created_by,request_id,version_id,parent_version_id,relation) "
                        "VALUES(%s,'{}',%s,%s,%s,%s,%s)",
                        [uuid7(), principal.name, request_id, version_id, parent["id"], relation],
                    )
            if row is None:
                raise ValueError("publication insert returned no identity")
            conn.execute(
                "INSERT INTO registry.publication_requests"
                "(id,payload,created_by,request_id,publish_key,request_digest,version_id) "
                "VALUES(%s,'{}',%s,%s,%s,%s,%s)",
                [
                    uuid7(),
                    principal.name,
                    request_id,
                    request.publish_key,
                    checked.request_digest,
                    row["id"],
                ],
            )
            if not created:
                audit(conn, principal.name, request_id, "identical_publication", row["id"])
            return PublicationResponse(artifact=from_row(row), created=created)
