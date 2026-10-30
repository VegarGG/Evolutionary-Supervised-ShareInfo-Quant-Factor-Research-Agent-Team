"""Audited on-demand snapshot builds, with recovery across DB/file boundaries."""

import hashlib
import os
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb
from qfr_core.contracts.data import ResearchDatasetRegistration
from qfr_core.data_layer.catalog import registration_hash
from qfr_core.data_layer.snapshots import Snapshot, canonical_json

from qfr_eval.ingest.build import build_zones
from qfr_eval.ingest.models import SnapshotBuildAuthorization, SnapshotBuildPlan
from qfr_eval.ingest.sources import load_source
from qfr_eval.scheduler.dedup import digest


class IngestConflict(ValueError):
    pass


def publish_catalog(root: Path, value: ResearchDatasetRegistration, maximum_bytes: int) -> None:
    raw = canonical_json(value.model_dump(mode="json"))
    if len(raw) > maximum_bytes or registration_hash(value) != value.registration_id:
        raise ValueError("invalid research catalog size or identity")
    folder = root / "research" / "catalog"
    folder.mkdir(parents=True, exist_ok=True)
    if folder.is_symlink() or (root / "research").is_symlink():
        raise ValueError("research catalog must be an owned volume directory")
    target = folder / (value.registration_id + ".json")
    descriptor, name = tempfile.mkstemp(prefix=".staging-", dir=folder)
    staging = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o444)
        try:
            os.link(staging, target)
        except FileExistsError:
            if (
                target.is_symlink()
                or target.stat().st_size != len(raw)
                or target.read_bytes() != raw
            ):
                raise ValueError("immutable research registration already differs") from None
    finally:
        staging.unlink(missing_ok=True)


def _outcome(
    conn: Connection,
    plan: SnapshotBuildPlan,
    state: str,
    body: dict[str, object],
    principal: str,
    request_id: UUID,
) -> None:
    conn.execute(
        "INSERT INTO eval.ingest_outcomes(id,ingest_request_id,state,payload,created_by,"
        "request_id) VALUES(%s,%s,%s,%s,%s,%s)",
        [uuid4(), plan.plan_id, state, Jsonb(body), principal, request_id],
    )


def ingest_once(
    conn: Connection,
    plan: SnapshotBuildPlan,
    authorization: SnapshotBuildAuthorization,
    *,
    source_root: Path,
    fixtures_root: Path,
    output_root: Path,
    principal: str,
    request_id: UUID,
) -> ResearchDatasetRegistration:
    plan = SnapshotBuildPlan.model_validate(plan.model_dump())
    authorization = SnapshotBuildAuthorization.model_validate(authorization.model_dump())
    if (
        not authorization.enabled
        or authorization.plan_sha256 != plan.sha256
        or authorization.authorized_principal != principal
        or not principal.strip()
    ):
        raise PermissionError("ingest is inactive or lacks exact plan authorization")
    if not conn.autocommit or conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("ingest requires its own idle autocommit connection")
    if conn.execute("SELECT current_user,current_database()").fetchone() != ("eval_rw", "eval_db"):
        raise PermissionError("ingest requires its evaluation-side database identity")
    authorization_sha = digest(authorization.model_dump(mode="json"))
    with conn.transaction():
        clock = conn.execute("SELECT clock_timestamp()").fetchone()
        assert clock is not None
        if authorization.authorized_at > clock[0]:
            raise PermissionError("ingest authorization has not taken effect")
        conn.execute(
            "INSERT INTO eval.ingest_requests(id,program_id,plan_sha256,"
            "authorization_sha256,payload,created_by,request_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
            [
                plan.plan_id,
                plan.program_id,
                plan.sha256,
                authorization_sha,
                Jsonb(
                    dict(
                        plan=plan.model_dump(mode="json"),
                        authorization=authorization.model_dump(mode="json"),
                    )
                ),
                principal,
                request_id,
            ],
        )
        original = conn.execute(
            "SELECT plan_sha256,authorization_sha256 FROM eval.ingest_requests WHERE id=%s",
            [plan.plan_id],
        ).fetchone()
        if original != (plan.sha256, authorization_sha):
            raise IngestConflict("ingest plan ID already binds different immutable intent")
    try:
        with conn.transaction():
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ["qfr-ingest:" + str(plan.plan_id)],
            )
            previous = conn.execute(
                "SELECT payload FROM eval.ingest_outcomes "
                "WHERE ingest_request_id=%s AND state='built'",
                [plan.plan_id],
            ).fetchone()
            if previous is not None:
                registration = ResearchDatasetRegistration.model_validate(
                    previous[0]["registration"]
                )
                research = Snapshot.load(
                    output_root / "research" / registration.research_manifest.snapshot_id
                )
                full = Snapshot.load(output_root / "full" / registration.dataset_version_id)
                if research.manifest != registration.research_manifest or (
                    digest(full.manifest.model_dump(mode="json"))
                    != previous[0]["full_manifest_sha256"]
                ):
                    raise ValueError("original built snapshot differs during recovery")
            else:
                imported = load_source(plan, authorization, source_root, fixtures_root)
                research, full = build_zones(
                    output_root,
                    imported.tables,
                    cutoff=plan.research_cutoff,
                    as_of=plan.as_of,
                    profile=imported.profile,
                    source=plan.source_ref,
                    build_code_version=plan.build_code_version,
                    exposure=imported.exposure,
                    conventions=imported.conventions,
                    principal=principal,
                    request_id=str(request_id),
                    audit_root=output_root / "full" / "_audit",
                )
                registration = ResearchDatasetRegistration(
                    schema_version="1",
                    registration_id="0" * 64,
                    program_id=plan.program_id,
                    dataset_version_id=full.manifest.snapshot_id,
                    source_ref=plan.source_ref,
                    research_manifest=research.manifest,
                    research_manifest_sha256=digest(research.manifest.model_dump(mode="json")),
                )
                registration = registration.model_copy(
                    update={"registration_id": registration_hash(registration)}
                )
                if (
                    len(canonical_json(registration.model_dump(mode="json")))
                    > authorization.maximum_metadata_bytes
                ):
                    raise ValueError("built registration exceeds metadata bounds")
                _outcome(
                    conn,
                    plan,
                    "built",
                    dict(
                        registration=registration.model_dump(mode="json"),
                        full_manifest_sha256=digest(full.manifest.model_dump(mode="json")),
                        source_hashes=imported.source_hashes,
                    ),
                    principal,
                    request_id,
                )
    except (ValueError, OSError, KeyError, TypeError):
        with conn.transaction():
            _outcome(
                conn,
                plan,
                "failed",
                {"reason": "source_or_snapshot_invalid"},
                principal,
                request_id,
            )
        raise
    # Publishing after the private DB commit makes a crash recoverable: either
    # catalog is absent, or it identifies an already durable verified build.
    # The catalog contains no source paths, full manifest or private source bytes.
    publish_catalog(output_root, registration, authorization.maximum_metadata_bytes)
    with conn.transaction():
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            ["qfr-ingest:" + str(plan.plan_id)],
        )
        if (
            conn.execute(
                "SELECT 1 FROM eval.ingest_outcomes WHERE ingest_request_id=%s "
                "AND state='catalog_available'",
                [plan.plan_id],
            ).fetchone()
            is None
        ):
            _outcome(
                conn,
                plan,
                "catalog_available",
                dict(
                    registration_id=registration.registration_id,
                    sha256=hashlib.sha256(
                        canonical_json(registration.model_dump(mode="json"))
                    ).hexdigest(),
                ),
                principal,
                request_id,
            )
    return registration
