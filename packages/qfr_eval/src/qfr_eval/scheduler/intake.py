"""Evaluator-only pull scheduling with durable cursors and explicit deferral.

No HTTP listener, inbound trigger, research priority or artifact execution lives
here. A private owner supplies a frozen campaign; an idle campaign does nothing.
"""

from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.dsl.language import DSLConfig
from qfr_core.registry_client import RegistryClient

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.db.queue import claim, enqueue
from qfr_eval.records import StoredFile
from qfr_eval.scheduler.dedup import equivalent, semantic_scope, verify_publication
from qfr_eval.scheduler.models import (
    DevelopmentBehavior,
    IntakeCampaign,
    IntakePolicy,
    PilotScreeningPolicy,
)


def transition(
    conn: Connection,
    identity: UUID,
    state: str,
    *,
    reason: str,
    principal: str,
    request_id: UUID,
    duplicate_of: UUID | None = None,
) -> None:
    old = conn.execute(
        "SELECT state FROM eval.intake WHERE id=%s FOR UPDATE", [identity]
    ).fetchone()
    if old is None:
        raise ValueError("unknown intake")
    conn.execute(
        "UPDATE eval.intake SET state=%s,duplicate_of=%s,created_by=%s,request_id=%s WHERE id=%s",
        [state, duplicate_of, principal, request_id, identity],
    )
    conn.execute(
        "INSERT INTO eval.intake_transitions(id,intake_id,payload,created_by,request_id) "
        "VALUES(%s,%s,%s,%s,%s)",
        [
            uuid4(),
            identity,
            Jsonb(
                {
                    "from": old[0],
                    "to": state,
                    "reason": reason,
                    "duplicate_of": str(duplicate_of) if duplicate_of else None,
                }
            ),
            principal,
            request_id,
        ],
    )


class IntakeScheduler:
    def __init__(
        self,
        client: RegistryClient,
        connect: Callable[[], Connection],
        campaign: IntakeCampaign,
        policy: IntakePolicy,
        screening: PilotScreeningPolicy,
        dsl_configs: dict[str, DSLConfig],
        *,
        principal: str,
    ) -> None:
        if (
            not principal.strip()
            or campaign.screening_policy_hash != screening.sha256
            or campaign.protocol_hash != screening.protocol_sha256
        ):
            raise ValueError("campaign does not pin the approved screening scope")
        self.client, self.connect, self.campaign = client, connect, campaign
        self.policy, self.screening, self.principal = policy, screening, principal
        self.dsl_configs = dsl_configs

    @property
    def queue(self) -> str:
        return "screening:" + str(self.campaign.campaign_id)

    def register(self, conn: Connection, request_id: UUID) -> None:
        campaign = self.campaign
        previous = conn.execute(
            "SELECT sha256 FROM eval.intake_campaigns WHERE id=%s", [campaign.campaign_id]
        ).fetchone()
        if previous is not None:
            if previous[0] != campaign.sha256:
                raise ValueError("campaign cannot be changed or reset")
            return
        conn.execute(
            "INSERT INTO eval.intake_campaigns(id,payload,sha256,created_by,request_id) "
            "VALUES(%s,%s,%s,%s,%s)",
            [
                campaign.campaign_id,
                Jsonb(campaign.model_dump(mode="json")),
                campaign.sha256,
                self.principal,
                request_id,
            ],
        )
        conn.execute(
            "INSERT INTO eval.intake_cursor(id,payload,created_by,request_id,campaign_id) "
            "VALUES(%s,'{}',%s,%s,%s)",
            [
                uuid5(campaign.campaign_id, "cursor"),
                self.principal,
                request_id,
                campaign.campaign_id,
            ],
        )

    def _lineages(
        self, conn: Connection, artifact: PublishedArtifact, request_id: UUID
    ) -> list[str]:
        manifest = artifact.manifest
        program, family = manifest.provenance.program_id, manifest.family_id
        inherited: set[str] = set()
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT lineage_id FROM eval.intake_lineages WHERE program_id=%s AND family_id=%s",
                [program, family],
            )
        }
        owner_root = self.campaign.root_lineages.get(UUID(family))
        if owner_root:
            inherited.add(owner_root)
        for parent_id in manifest.parent_version_ids:
            row = conn.execute(
                "SELECT family_id FROM eval.intake WHERE artifact_version_id=%s AND program_id=%s "
                "ORDER BY created_at,id LIMIT 1",
                [UUID(parent_id), program],
            ).fetchone()
            if row:
                inherited.update(
                    r[0]
                    for r in conn.execute(
                        "SELECT lineage_id FROM eval.intake_lineages WHERE "
                        "family_id=%s AND program_id=%s",
                        [row[0], program],
                    )
                )
        if existing and owner_root and owner_root not in existing:
            raise ValueError("owner lineage binding conflicts with existing exposure history")
        inherited |= existing
        for lineage in sorted(inherited - existing):
            conn.execute(
                "INSERT INTO eval.intake_lineages(id,payload,program_id,family_id,lineage_id,"
                "created_by,request_id) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                [
                    uuid4(),
                    Jsonb({"campaign_id": str(self.campaign.campaign_id)}),
                    program,
                    family,
                    lineage,
                    self.principal,
                    request_id,
                ],
            )
        return sorted(inherited)

    def _discover(self, conn: Connection, artifact: PublishedArtifact, request_id: UUID) -> bool:
        campaign, manifest = self.campaign, artifact.manifest
        identity = uuid5(campaign.campaign_id, manifest.artifact_version_id)
        if conn.execute("SELECT 1 FROM eval.intake WHERE id=%s", [identity]).fetchone():
            return False
        scope = semantic_scope(artifact, campaign)
        canonical = manifest.canonical_fingerprint or manifest.implementation_fingerprint
        conn.execute(
            "INSERT INTO "
            "eval.intake(id,payload,created_by,request_id,campaign_id,artifact_version_id,"
            "published_seq,program_id,family_id,semantic_scope_sha256,canonical_key,state) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'discovered')",
            [
                identity,
                Jsonb({"artifact": artifact.model_dump(mode="json")}),
                self.principal,
                request_id,
                campaign.campaign_id,
                UUID(manifest.artifact_version_id),
                artifact.published_seq,
                manifest.provenance.program_id,
                manifest.family_id,
                scope,
                canonical,
            ],
        )
        reason = None
        try:
            verify_publication(artifact, self.dsl_configs)
        except ValueError:
            reason = "SCHEMA_INVALID"
        if manifest.provenance.program_id not in campaign.program_ids:
            reason = "PROGRAM_UNAUTHORIZED"
        elif manifest.kind not in campaign.allowed_kinds:
            reason = "KIND_UNSUPPORTED"
        elif campaign.protocol_ref not in manifest.eligible_protocols:
            reason = "PROTOCOL_INCOMPATIBLE"
        if reason:
            transition(
                conn,
                identity,
                "rejected",
                reason=reason,
                principal=self.principal,
                request_id=request_id,
            )
            return True
        duplicate = conn.execute(
            "SELECT id FROM eval.intake WHERE semantic_scope_sha256=%s AND canonical_key=%s "
            "AND artifact_version_id<>%s AND state NOT IN ('rejected','duplicate') "
            "ORDER BY published_seq,created_at,id LIMIT 1",
            [scope, canonical, UUID(manifest.artifact_version_id)],
        ).fetchone()
        lineages = self._lineages(conn, artifact, request_id)
        if duplicate:
            # Bind renamed canonical clones to earlier exposure even without a parent.
            source = conn.execute(
                "SELECT family_id FROM eval.intake WHERE id=%s", [duplicate[0]]
            ).fetchone()
            assert source is not None
            for row in conn.execute(
                "SELECT lineage_id FROM eval.intake_lineages WHERE family_id=%s AND program_id=%s",
                [source[0], manifest.provenance.program_id],
            ).fetchall():
                conn.execute(
                    "INSERT INTO "
                    "eval.intake_lineages(id,payload,program_id,family_id,lineage_id,created_by,"
                    "request_id) VALUES(%s,'{}',%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    [
                        uuid4(),
                        manifest.provenance.program_id,
                        manifest.family_id,
                        row[0],
                        self.principal,
                        request_id,
                    ],
                )
            transition(
                conn,
                identity,
                "duplicate",
                reason="DUPLICATE_OF",
                principal=self.principal,
                request_id=request_id,
                duplicate_of=duplicate[0],
            )
        else:
            transition(
                conn,
                identity,
                "deferred",
                reason="RESOURCE_CAPACITY" if lineages else "LINEAGE_OWNER_INPUT",
                principal=self.principal,
                request_id=request_id,
            )
        return True

    def _dispatch(self, conn: Connection, request_id: UUID) -> int:
        campaign = self.campaign
        count = conn.execute(
            "SELECT count(*) FROM eval.jobs WHERE queue=%s AND state IN ('queued','running')",
            [self.queue],
        ).fetchone()
        assert count is not None
        capacity = self.policy.max_ready_jobs_per_campaign - count[0]
        queued = 0
        for _ in range(max(capacity, 0)):
            rows = conn.execute(
                "SELECT id,payload,family_id,published_seq,created_at FROM eval.intake "
                "WHERE campaign_id=%s AND state='deferred' ORDER BY published_seq,id",
                [campaign.campaign_id],
            ).fetchall()
            eligible = []
            now = conn.execute("SELECT clock_timestamp()").fetchone()
            assert now is not None
            for row in rows:
                artifact = PublishedArtifact.model_validate(row[1]["artifact"])
                if not self._lineages(conn, artifact, request_id):
                    continue  # An elapsed wait never resolves missing owner input.
                expiry = self.policy.deferral_expiry_seconds
                if expiry is not None and (now[0] - row[4]).total_seconds() >= expiry:
                    transition(
                        conn,
                        row[0],
                        "rejected",
                        reason="QUOTA_EXPIRED",
                        principal=self.principal,
                        request_id=request_id,
                    )
                    continue
                eligible.append(row)
            if not eligible:
                break
            families = [
                r[0]
                for r in conn.execute(
                    "SELECT family_id FROM eval.intake WHERE campaign_id=%s GROUP BY family_id "
                    "ORDER BY min(published_seq),family_id",
                    [campaign.campaign_id],
                )
            ]
            last = conn.execute(
                "SELECT last_family FROM eval.intake_cursor WHERE campaign_id=%s",
                [campaign.campaign_id],
            ).fetchone()
            assert last is not None
            start = families.index(last[0]) + 1 if last[0] in families else 0
            rotated = families[start:] + families[:start]
            family = next(name for name in rotated if any(r[2] == name for r in eligible))
            selected = next(r for r in eligible if r[2] == family)
            job = enqueue(
                conn,
                {"intake_id": str(selected[0]), "campaign_id": str(campaign.campaign_id)},
                principal=self.principal,
                request_id=request_id,
                run_after=now[0],
                queue=self.queue,
                job_id=uuid5(selected[0], "screening"),
            )
            conn.execute(
                "UPDATE eval.intake SET job_id=%s,created_by=%s,request_id=%s WHERE id=%s",
                [job, self.principal, request_id, selected[0]],
            )
            transition(
                conn,
                selected[0],
                "queued",
                reason="FAIR_DISPATCH",
                principal=self.principal,
                request_id=request_id,
            )
            conn.execute(
                "UPDATE eval.intake_cursor SET "
                "last_family=%s,created_by=%s,request_id=%s WHERE campaign_id=%s",
                [family, self.principal, request_id, campaign.campaign_id],
            )
            queued += 1
        return queued

    def poll_once(self) -> dict[str, int | bool]:
        if not self.campaign.active:
            return {"active": False, "discovered": 0, "queued": 0}
        request_id = uuid4()
        with self.connect() as conn, conn.transaction():
            # One serialized intake transaction includes page persistence and cursor.
            # Network calls are bounded by the explicit registry-client timeout.
            conn.execute("SELECT pg_advisory_xact_lock(72460320)")
            self.register(conn, request_id)
            cursor = conn.execute(
                "SELECT published_seq FROM eval.intake_cursor WHERE campaign_id=%s FOR UPDATE",
                [self.campaign.campaign_id],
            ).fetchone()
            assert cursor is not None
            page = self.client.page(since_seq=cursor[0], limit=self.policy.page_size)
            discovered = sum(self._discover(conn, item, request_id) for item in page.items)
            conn.execute(
                "UPDATE eval.intake_cursor SET "
                "published_seq=%s,created_by=%s,request_id=%s WHERE campaign_id=%s",
                [page.next_cursor, self.principal, request_id, self.campaign.campaign_id],
            )
            queued = self._dispatch(conn, request_id)
            return {
                "active": True,
                "discovered": discovered,
                "queued": queued,
                "cursor": page.next_cursor,
            }

    def claim(self, *, worker: str, lease_seconds: int, request_id: UUID) -> dict[str, Any] | None:
        if not self.campaign.active:
            return None
        with self.connect() as conn, conn.transaction():
            job = claim(
                conn,
                worker=worker,
                request_id=request_id,
                lease_seconds=lease_seconds,
                queue=self.queue,
            )
            if job is not None:
                identity = UUID(job["payload"]["intake_id"])
                transition(
                    conn,
                    identity,
                    "screening",
                    reason="WORKER_LEASE",
                    principal=worker,
                    request_id=request_id,
                )
                with conn.cursor(row_factory=dict_row) as cur:
                    job["intake"] = cur.execute(
                        "SELECT * FROM eval.intake WHERE id=%s", [identity]
                    ).fetchone()
            return job

    def behavior_duplicate(
        self,
        conn: Connection,
        identity: UUID,
        behavior: DevelopmentBehavior,
        store: EvidenceStore,
    ) -> UUID | None:
        row = conn.execute(
            "SELECT semantic_scope_sha256 FROM eval.intake WHERE id=%s", [identity]
        ).fetchone()
        if row is None or row[0] != behavior.semantic_scope_sha256:
            raise ValueError("behavior scope differs from its intake")
        references = conn.execute(
            "SELECT b.intake_id,b.payload FROM eval.intake_behavior b JOIN "
            "eval.intake i ON i.id=b.intake_id "
            "WHERE b.semantic_scope_sha256=%s AND b.intake_id<>%s AND i.state='screen_passed' "
            "ORDER BY i.published_seq,i.created_at,i.id",
            [row[0], identity],
        ).fetchall()
        for reference_id, payload in references:
            reference = DevelopmentBehavior.model_validate_json(
                store.read(StoredFile.model_validate(payload))
            )
            if equivalent(behavior, reference, self.screening):
                return UUID(str(reference_id))
        return None

    def reserve_feedback(
        self,
        conn: Connection,
        identity: UUID,
        *,
        request_id: UUID,
    ) -> Literal["eligible", "withheld:budget"]:
        """Reserve a unique evaluated version, never stop its measurement at budget.

        Worker calls this inside the official-record/trial transaction, after
        behavioral dedup. It does not release anything or spend confirmation.
        """
        if conn.info.transaction_status != TransactionStatus.INTRANS:
            raise ValueError("feedback reservation requires the caller's active transaction")
        conn.execute("SELECT pg_advisory_xact_lock(72460321)")
        row = conn.execute(
            "SELECT payload,state FROM eval.intake WHERE id=%s", [identity]
        ).fetchone()
        if row is None or row[1] != "screening":
            raise ValueError("only a screened unique attempt can reserve feedback")
        artifact = PublishedArtifact.model_validate(row[0]["artifact"])
        lineages = self._lineages(conn, artifact, request_id)
        if not lineages:
            raise ValueError("economic lineage owner input is unresolved")
        program, version = (
            artifact.manifest.provenance.program_id,
            UUID(artifact.manifest.artifact_version_id),
        )
        generation = self.campaign.server_generation_id
        ordinals = []
        for lineage in lineages:
            previous = conn.execute(
                "SELECT ordinal FROM eval.feedback_reservations WHERE "
                "program_id=%s AND lineage_id=%s "
                "AND generation_id=%s AND artifact_version_id=%s",
                [program, lineage, generation, version],
            ).fetchone()
            if previous:
                ordinals.append(previous[0])
                continue
            ordinal = conn.execute(
                "SELECT coalesce(max(ordinal),0)+1 FROM eval.feedback_reservations "
                "WHERE program_id=%s AND lineage_id=%s AND generation_id=%s",
                [program, lineage, generation],
            ).fetchone()
            assert ordinal is not None
            conn.execute(
                "INSERT INTO "
                "eval.feedback_reservations(id,payload,program_id,lineage_id,generation_id,"
                "artifact_version_id,ordinal,created_by,request_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    uuid4(),
                    Jsonb({"intake_id": str(identity)}),
                    program,
                    lineage,
                    generation,
                    version,
                    ordinal[0],
                    self.principal,
                    request_id,
                ],
            )
            ordinals.append(ordinal[0])
        disposition: Literal["eligible", "withheld:budget"] = (
            "eligible"
            if max(ordinals) <= self.screening.feedback_versions_per_lineage_generation
            else "withheld:budget"
        )
        conn.execute(
            "UPDATE eval.intake SET "
            "feedback_disposition=%s,created_by=%s,request_id=%s WHERE id=%s",
            [disposition, self.principal, request_id, identity],
        )
        return disposition
