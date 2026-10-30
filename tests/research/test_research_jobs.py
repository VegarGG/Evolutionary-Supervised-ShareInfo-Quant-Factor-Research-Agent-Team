"""P4.9 durable job transactions with real PostgreSQL and explicit synthetic inputs.

The public-protocol reader below is a unit fixture, not an evaluator gate or MCP
acceptance. HTTP/service integration is verified separately.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import polars as pl
import pytest
from pydantic import ValidationError
from qfr_core.access import ServicePrincipal
from qfr_core.contracts.data import ExposureAndQuality, ResearchDatasetRegistration
from qfr_core.contracts.enums import JobState
from qfr_core.contracts.research import (
    DatasetRegistrationRequest,
    JobAdmission,
    JobControl,
    ProgramCreate,
    ResearchApiPolicy,
)
from qfr_core.data_layer.catalog import registration_hash
from qfr_core.data_layer.snapshots import TableInput
from qfr_core.delivery_rules import (
    PILOT_DELIVERY_CHECKS,
    content_sha256,
    gate_hash,
    job_config_hash,
)
from qfr_eval.ingest.build import build_zones
from qfr_eval.ingest.service import publish_catalog
from qfr_research.api.errors import InvalidResearchRequest, ResearchConflict, ResearchNotFound
from qfr_research.api.jobs import Jobs
from qfr_research.api.storage import Storage

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.database


class SyntheticPublicEvidence:
    def protocol_exists(self, program, version):
        assert isinstance(program, UUID) and version == "synthetic-protocol:1"


def changed(value, **updates):
    return type(value).model_validate({**value.model_dump(), **updates})


def setup_service(research_connect, tmp_path, *, register=True, service_class=Jobs):
    program = uuid4()
    principal = ServicePrincipal(
        "synthetic-owner", "research", frozenset({"research_lead"}), frozenset({str(program)})
    )
    policy = ResearchApiPolicy.model_validate_json(
        (ROOT / "configs/research/api_v1.json").read_bytes()
    )
    service = service_class(
        Storage(research_connect, policy), SyntheticPublicEvidence(), tmp_path / "research"
    )
    create = ProgramCreate(
        program_id=program, name="Synthetic research API fixture", charter={"calls": "none"}
    )
    service.create(principal, create, uuid4())
    exposure = ExposureAndQuality.model_validate(
        json.loads((ROOT / "contracts/examples/ExposureAndQuality.valid.json").read_text())
    )
    research, full = build_zones(
        tmp_path,
        [
            TableInput(
                "prices",
                pl.DataFrame(dict(date=[date(2020, 1, 1)], value=[1.0])),
                ("date",),
                exposure.quality,
                "Synthetic",
                "date",
                None,
            )
        ],
        cutoff=date(2020, 1, 1),
        as_of=date(2020, 1, 1),
        profile="pilot_industry_v1",
        source="synthetic-api-fixture",
        build_code_version="fixture",
        exposure=exposure,
        conventions={},
        principal="synthetic-owner",
        request_id=str(uuid4()),
    )
    registration = ResearchDatasetRegistration(
        schema_version="1",
        registration_id="0" * 64,
        program_id=str(program),
        dataset_version_id=full.manifest.snapshot_id,
        source_ref="synthetic-api-fixture",
        research_manifest=research.manifest,
        research_manifest_sha256=content_sha256(research.manifest.model_dump(mode="json")),
    )
    registration = changed(registration, registration_id=registration_hash(registration))
    publish_catalog(tmp_path, registration, 1048576)
    if register:
        service.dataset(
            principal,
            program,
            DatasetRegistrationRequest(registration_id=registration.registration_id),
            uuid4(),
        )
    value = json.loads((ROOT / "contracts/examples/JobAdmission.valid.json").read_text())
    bundle, brief = value["input_bundle"], value["brief"]
    bundle.update(
        source_assets=[],
        baseline_refs=[],
        readiness="ready",
        unresolved_requirements=[],
        data_requirements=[],
        data_refs=[full.manifest.snapshot_id],
        bundle_id=str(uuid4()),
    )
    bundle["definition"]["unresolved_questions"] = []
    bundle["job_config"].update(permitted_dataset_ids=bundle["data_refs"], role_profile_refs=[])
    brief.update(
        project_id=str(program),
        input_bundle_id=bundle["bundle_id"],
        brief_id=str(uuid4()),
        objective=bundle["objective"],
        baseline_artifact_ids=[],
        role_profiles=[],
    )
    gate = brief["exit_gate"]
    gate.update(
        required_checks=list(PILOT_DELIVERY_CHECKS),
        protocol_refs=["synthetic-protocol:1"],
        reproducibility_criteria=["exact_results_and_series_replay"],
        evidence_release_requirements=["verified_released_reports_only"],
        allowed_conclusions=["supported_negative"],
        human_signoff_required=False,
        forward_evidence_required=False,
        frozen_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        required_deliverables=[
            dict(
                name="research note",
                schema_ref="ResearchNotePayload",
                required=True,
                evidence_refs_required=True,
            )
        ],
    )
    bundle["requested_deliverables"] = ["research note"]
    bundle["job_config"]["proposed_exit_gate_ref"] = gate["gate_id"]
    value["idempotency_key"] = str(uuid4())
    admission = JobAdmission.model_validate(value)
    frozen_gate = changed(admission.brief.exit_gate, spec_hash=gate_hash(admission.brief.exit_gate))
    admission = changed(
        admission,
        brief=changed(
            admission.brief,
            exit_gate=frozen_gate,
            frozen_config_hash=job_config_hash(admission.input_bundle),
        ),
    )
    return SimpleNamespace(
        service=service,
        program=program,
        principal=principal,
        admission=admission,
        registration=registration,
        create=create,
    )


def control(case, status, action, key=None):
    value = JobControl(
        operation_key=key or str(uuid4()), expected_revision=status.revision, action=action
    )
    return case.service.control(case.principal, UUID(status.job.job_id), value, uuid4())


def test_admission_lost_ack_concurrent_retry_and_restart(research_connect, tmp_path):
    case = setup_service(research_connect, tmp_path)
    with ThreadPoolExecutor(4) as pool:
        values = list(
            pool.map(
                lambda _: case.service.admit(case.principal, case.program, case.admission, uuid4()),
                range(4),
            )
        )
    assert len({v.job.job_id for v in values}) == 1
    status = values[0]
    assert status.job.state == JobState.READY and status.next_action == "start"
    assert case.admission.input_bundle.job_config.max_generations is None
    assert case.admission.input_bundle.job_config.max_wall_clock_seconds is None
    restarted = Jobs(
        Storage(research_connect, case.service.policy),
        SyntheticPublicEvidence(),
        tmp_path / "research",
    )
    assert restarted.get_job(case.principal, UUID(status.job.job_id)) == status
    restarted.evidence = None  # lost-submit lookup does not depend on another service being alive
    assert restarted.admit(case.principal, case.program, case.admission, uuid4()) == status
    with research_connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM research.research_jobs WHERE program_id=%s", [case.program]
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM research.jobs WHERE program_id=%s", [case.program]
        ).fetchone() == (1,)
        assert (
            conn.execute(
                "SELECT count(*) FROM research.events WHERE program_id=%s", [case.program]
            ).fetchone()[0]
            >= 8
        )
    conflict = changed(
        case.admission, brief=changed(case.admission.brief, constraints=["new intent"])
    )
    with pytest.raises(ResearchConflict):
        case.service.admit(case.principal, case.program, conflict, uuid4())


def test_control_is_fenced_idempotent_and_never_controls_evaluation(research_connect, tmp_path):
    case = setup_service(research_connect, tmp_path)
    status = case.service.admit(case.principal, case.program, case.admission, uuid4())
    running = control(case, status, "start")
    paused = control(case, running, "pause", "pause-once")
    assert paused.job.reason == "operator_pause"
    same = case.service.control(
        case.principal,
        UUID(status.job.job_id),
        JobControl(operation_key="pause-once", expected_revision=running.revision, action="pause"),
        uuid4(),
    )
    assert same == paused
    with pytest.raises(ResearchConflict):
        control(case, running, "cancel")
    resumed = control(case, paused, "resume")
    waiting = control(case, resumed, "await_evaluation")
    assert waiting.job.state == JobState.AWAITING_EVALUATION
    cancelled = control(case, waiting, "cancel")
    assert cancelled.job.state == JobState.CANCELLED and cancelled.job.receipt is None
    with pytest.raises(ResearchConflict):
        control(case, cancelled, "resume")
    with pytest.raises(ValidationError):
        JobControl(operation_key="forged", expected_revision=1, action="completed")
    with research_connect() as conn:
        assert conn.execute(
            "SELECT state FROM research.jobs WHERE program_id=%s", [case.program]
        ).fetchall() == [("cancelled",)]


def test_unavailable_dataset_is_explicit_and_register_then_resume(research_connect, tmp_path):
    case = setup_service(research_connect, tmp_path, register=False)
    status = case.service.admit(case.principal, case.program, case.admission, uuid4())
    assert status.job.state == JobState.WAITING_FOR_DATA and status.job.reason == "blocked_on_data"
    with pytest.raises(ResearchConflict, match="unresolved"):
        control(case, status, "resume")
    case.service.dataset(
        case.principal,
        case.program,
        DatasetRegistrationRequest(registration_id=case.registration.registration_id),
        uuid4(),
    )
    resumed = control(case, status, "resume")
    assert resumed.job.state == JobState.READY and resumed.job.reason is None
    assert resumed.job.payload_hash == status.job.payload_hash


def test_cross_program_and_reader_mutations_are_refused(research_connect, tmp_path):
    case = setup_service(research_connect, tmp_path)
    status = case.service.admit(case.principal, case.program, case.admission, uuid4())
    stranger = ServicePrincipal(
        "stranger", "research", frozenset({"research_lead"}), frozenset({str(uuid4())})
    )
    with pytest.raises(ResearchNotFound):
        case.service.get_job(stranger, UUID(status.job.job_id))
    reader = ServicePrincipal("reader", "research", frozenset({"reader"}), case.principal.programs)
    assert case.service.get_job(reader, UUID(status.job.job_id)) == status
    with pytest.raises(PermissionError):
        case.service.admit(reader, case.program, case.admission, uuid4())
    with pytest.raises(PermissionError):
        case.service.control(
            reader,
            UUID(status.job.job_id),
            JobControl(operation_key="deny", expected_revision=1, action="cancel"),
            uuid4(),
        )


@pytest.mark.parametrize("issue", ["config", "gate", "budget", "scope", "baseline"])
def test_inconsistent_frozen_intent_is_refused_before_writes(research_connect, tmp_path, issue):
    case = setup_service(research_connect, tmp_path)
    brief = case.admission.brief
    updates = {
        "config": {"frozen_config_hash": "a" * 64},
        "gate": {"exit_gate": changed(brief.exit_gate, spec_hash="a" * 64)},
        "budget": {"budgets": changed(brief.budgets, max_generations=1)},
        "scope": {"project_id": str(uuid4())},
        "baseline": {"baseline_artifact_ids": [str(uuid4())]},
    }[issue]
    with pytest.raises(ValueError):
        case.service.admit(
            case.principal,
            case.program,
            changed(case.admission, brief=changed(brief, **updates)),
            uuid4(),
        )
    with research_connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM research.research_jobs WHERE program_id=%s", [case.program]
        ).fetchone() == (0,)


def test_page_bounds_and_program_scoped_cursors(research_connect, tmp_path):
    case = setup_service(research_connect, tmp_path)
    for n in range(3):
        case.service.admit(
            case.principal, case.program, changed(case.admission, idempotency_key=str(n)), uuid4()
        )
    first = case.service.jobs(case.principal, case.program, after=None, limit=2)
    second = case.service.jobs(case.principal, case.program, after=first.next_after_id, limit=2)
    assert len(first.items) == 2 and first.has_more
    assert len(second.items) == 1 and not second.has_more
    assert len({v.job.job_id for v in [*first.items, *second.items]}) == 3
    with pytest.raises(ResearchNotFound):
        case.service.jobs(case.principal, case.program, after=uuid4(), limit=2)
    with pytest.raises(InvalidResearchRequest):
        case.service.jobs(case.principal, case.program, after=None, limit=100000)
