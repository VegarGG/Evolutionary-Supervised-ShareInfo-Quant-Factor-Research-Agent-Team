"""Independent decisions over synthetic evidence; real PostgreSQL and signatures.

Registry responses and replay journal entries here are explicit test fixtures.
They do not establish actual Registry/pilot execution or financial acceptance.
"""

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from psycopg.types.json import Jsonb
from pydantic import ValidationError
from qfr_core.contracts.artifacts import ArtifactDefinition, ArtifactReference
from qfr_core.contracts.delivery import AdmittedDeliveryContext, DeliveryProposal
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.delivery_rules import (
    PILOT_DELIVERY_CHECKS,
    admission_hash,
    content_sha256,
    gate_hash,
    job_config_hash,
    validate_pilot_delivery_gate,
)
from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.delivery.checker import check_delivery
from qfr_eval.delivery.models import PilotDeliveryPolicy
from qfr_eval.records import RegistryExecutionBinding
from qfr_eval.release.publish import publish_one
from qfr_eval.release.store import enqueue_source
from qfr_eval.scheduler.dedup import digest
from qfr_eval.signing import EvaluatorSigner
from qfr_eval.statistics.bootstrap import Interval
from test_release_preparation import ROOT, pilot_policy, store_pilot
from test_release_projection import evidence

pytestmark = pytest.mark.database


def sample(name):
    return json.loads((ROOT / f"contracts/examples/{name}.valid.json").read_bytes())


def changed(model, **updates):
    return type(model).model_validate({**model.model_dump(), **updates})


def artifact(program, reports=None):
    body = sample("PublishedArtifact")
    manifest = body["manifest"]
    manifest["artifact_version_id"] = str(uuid4())
    manifest["provenance"]["program_id"] = program
    payload = b'{"synthetic_fixture":true}'
    manifest["payload_files"][0]["sha256"] = hashlib.sha256(payload).hexdigest()
    if reports is not None:
        manifest.update(
            kind="research_note",
            implementation=dict(type="document", asset_id="asset-example", format="markdown"),
            payload=dict(
                kind="research_note",
                document_asset_id="asset-example",
                citation_refs=[],
                released_report_refs=reports,
            ),
        )
    definition = {k: manifest[k] for k in ArtifactDefinition.model_fields if k != "family_id"}
    sha = digest(
        dict(
            hash_spec="qfr-publication/1",
            profile=body["profile"],
            dsl_policy_hash=body["dsl_policy_hash"],
            manifest=definition,
        )
    )
    manifest["content_hash"] = body["payload_digest"] = sha
    return PublishedArtifact.model_validate(body), payload


def reference(value):
    return ArtifactReference(
        artifact_version_id=value.manifest.artifact_version_id,
        content_hash=value.manifest.content_hash,
    )


class SyntheticRegistry:
    def __init__(self, values):
        self.values = {v.manifest.artifact_version_id: (v, payload) for v, payload in values}

    def get(self, identity):
        return self.values[str(identity)][0]

    def payload(self, value, asset_id):
        assert asset_id == "asset-example"
        return self.values[value.manifest.artifact_version_id][1]


def delivery_case(factory, root, *, overall="fail", replay=True, insufficient=False):
    program = str(uuid4())
    factor, factor_bytes = artifact(program)
    store = EvidenceStore(root / "evidence")
    signer = EvaluatorSigner(
        secrets.token_bytes(32),
        purposes=[
            "released_report",
            "measurement_receipt",
            "delivery_receipt",
        ],
    )
    verifier = signer.verifier(maximum_document_bytes=1048576)
    policy = PilotDeliveryPolicy.model_validate_json(
        (ROOT / "configs/delivery/pilot_research_delivery_v1.json").read_bytes()
    )
    record, request, measured, protocol = evidence()
    request = changed(
        request,
        variant="registry",
        program_id=program,
        family_id=str(uuid4()),
        generation_id=str(uuid4()),
        epoch_id=str(uuid4()),
        economic_lineage_id=str(uuid4()),
        artifact_version_id=UUID(factor.manifest.artifact_version_id),
        content_hash=factor.manifest.content_hash,
        registry_execution=RegistryExecutionBinding(
            screening_record_id=uuid4(),
            screening_receipt_hash="1" * 64,
            execution_bundle=store.json({"synthetic_fixture": True}),
        ),
    )
    measured = changed(
        measured,
        reason_codes=[],
        uncertainty=Interval(
            status="insufficient_data" if insufficient else "estimated",
            estimate=0.0,
            ci_lower=-0.1,
            ci_upper=0.1,
            standard_error=0.05,
            valid_periods=100,
            time_slots=100,
            block_length=5,
            draws=10000,
            valid_draws=10000,
            seed=123,
            confidence=0.95,
            index_sha256="2" * 64,
            small_sample_warning=False,
        ),
        hurdle={"overall": overall, "coverage": "pass", "paired_primary": overall},
    )
    record = changed(
        record,
        reason_codes=[],
        metrics=measured.metrics,
        identity=changed(
            record.identity,
            artifact_version_id=str(request.artifact_version_id),
            content_hash=request.content_hash,
        ),
    )
    with factory() as conn:
        release = pilot_policy(conn, version=2)
        assert release.sha256 == policy.release_policy_sha256
        record, request = store_pilot(
            conn,
            completed_at=datetime.now(UTC) - timedelta(hours=7),
            evidence_store=store,
            source_case=(record, request, measured, protocol),
        )
        queued = enqueue_source(
            conn,
            "official_record",
            UUID(record.record_id),
            release.sha256,
            principal="synthetic-fixture",
            request_id=uuid4(),
        )
        report = publish_one(
            conn,
            queued,
            signer,
            verifier,
            principal="synthetic-fixture",
            request_id=uuid4(),
            evidence_store=store,
        )
        if replay:
            # A declared fixture of the protected evaluator audit, not a real replay.
            conn.execute(
                "INSERT INTO eval.events(id,payload,created_by,request_id) "
                "VALUES(%s,%s,'synthetic-replay-fixture',%s)",
                [
                    uuid4(),
                    Jsonb(
                        dict(
                            action="reproduction_match",
                            entity_type="official_records",
                            entity_id=record.record_id,
                            results_hash=record.results_hash,
                        )
                    ),
                    uuid4(),
                ],
            )
    note, note_bytes = artifact(program, [report.report_id])
    body = sample("AdmittedDeliveryContext")
    bundle, brief, job = body["input_bundle"], body["brief"], body["job"]
    bundle.update(
        readiness="ready",
        unresolved_requirements=[],
        data_requirements=[],
        data_refs=[request.snapshot_id],
    )
    bundle["job_config"]["permitted_dataset_ids"] = [request.snapshot_id]
    gate = brief["exit_gate"]
    gate.update(
        required_checks=list(PILOT_DELIVERY_CHECKS),
        protocol_refs=[record.identity.protocol_version],
        reproducibility_criteria=["exact_results_and_series_replay"],
        evidence_release_requirements=["verified_released_reports_only"],
        required_deliverables=[
            dict(
                name="research note",
                schema_ref="ResearchNotePayload",
                required=True,
                evidence_refs_required=True,
            )
        ],
        allowed_conclusions=["supported_negative", "supported_positive", "empty_shortlist"],
        human_signoff_required=False,
        forward_evidence_required=False,
    )
    brief.update(project_id=program, baseline_artifact_ids=[factor.manifest.artifact_version_id])
    job.update(
        project_id=program,
        state="validating_delivery",
        reason=None,
        receipt=None,
        exit_gate=gate,
        job_id=str(uuid4()),
    )
    context = AdmittedDeliveryContext.model_validate(body)
    frozen_gate = changed(context.job.exit_gate, spec_hash=gate_hash(context.job.exit_gate))
    brief = changed(
        context.brief,
        exit_gate=frozen_gate,
        frozen_config_hash=job_config_hash(context.input_bundle),
    )
    job = changed(
        context.job,
        exit_gate=frozen_gate,
        config_hash=brief.frozen_config_hash,
        payload_hash=admission_hash(context.input_bundle, brief),
    )
    context = changed(context, job=job, brief=brief)
    proposal = DeliveryProposal(
        schema_version="1",
        proposal_id=str(uuid4()),
        job_id=job.job_id,
        conclusion="supported_negative",
        artifact_refs=[reference(factor), reference(note)],
        released_report_refs=[
            dict(reference_id=report.report_id, sha256=digest(report.model_dump(mode="json")))
        ],
        deliverables=[dict(name="research note", artifact=reference(note))],
        shortlist=[],
    )
    return SimpleNamespace(
        context=context,
        proposal=proposal,
        policy=policy,
        signer=signer,
        verifier=verifier,
        store=store,
        report=report,
        record=record,
        factor=factor,
        note=note,
        registry=SyntheticRegistry([(factor, factor_bytes), (note, note_bytes)]),
    )


def check(factory, case, **changes):
    arguments = dict(
        context=case.context,
        proposal=case.proposal,
        registry=case.registry,
        policy=case.policy,
        verifier=case.verifier,
        signer=case.signer,
        evidence_store=case.store,
        receipt_id=uuid4(),
        at=datetime.now(UTC),
    )
    arguments.update(changes)
    with factory() as conn:
        return check_delivery(conn, **arguments)


def failed(receipt):
    assert receipt.result == "fail"
    return {c.check_id for c in receipt.checks if c.result == "fail"}


def test_dlv_01_03_supported_negative_links_exact_evidence_and_is_signed(eval_connect, tmp_path):
    case = delivery_case(eval_connect, tmp_path)
    receipt = check(eval_connect, case)
    assert receipt.result == "pass" and receipt.conclusion == "supported_negative"
    assert case.verifier.delivery(receipt) == receipt
    assert receipt.artifact_refs == case.proposal.artifact_refs
    assert receipt.released_report_refs == case.proposal.released_report_refs
    assert receipt.dataset_refs[0].reference_id == case.record.identity.dataset_version_id
    assert receipt.gate_spec_hash == case.context.job.exit_gate.spec_hash
    assert {c.check_id for c in receipt.checks} == set(PILOT_DELIVERY_CHECKS)
    assert {r.sha256 for r in receipt.config_refs} >= {
        case.context.job.config_hash,
        content_sha256(case.proposal.model_dump(mode="json")),
    }
    empty = changed(case.proposal, conclusion="empty_shortlist")
    assert check(eval_connect, case, proposal=empty).result == "pass"


def test_dlv_03_positive_and_negative_must_match_resolved_hurdle(eval_connect, tmp_path):
    case = delivery_case(eval_connect, tmp_path, overall="pass")
    assert "conclusion_support" in failed(check(eval_connect, case))
    positive = changed(
        case.proposal, conclusion="supported_positive", shortlist=[reference(case.factor)]
    )
    assert check(eval_connect, case, proposal=positive).result == "pass"
    assert "conclusion_support" in failed(
        check(eval_connect, case, proposal=changed(positive, shortlist=[reference(case.note)]))
    )


def test_delivery_v2_binds_input_without_relabelling_v1_evidence(eval_connect, tmp_path):
    case = delivery_case(eval_connect, tmp_path)
    original = check(eval_connect, case)
    assert len(original.config_refs) == 4 and original.independent_checker.endswith("-v1")
    policy = PilotDeliveryPolicy.model_validate_json(
        (ROOT / "configs/delivery/pilot_research_delivery_v2.json").read_bytes()
    )
    assert {
        k: v for k, v in policy.model_dump().items() if k not in {"schema_version", "checker_id"}
    } == {
        k: v
        for k, v in case.policy.model_dump().items()
        if k not in {"schema_version", "checker_id"}
    }
    current = check(eval_connect, case, policy=policy)
    assert current.result == "pass" and len(current.config_refs) == 6
    refs = {r.reference_id: r.sha256 for r in current.config_refs}
    assert refs["input-bundle:" + case.context.input_bundle.bundle_id] == content_sha256(
        case.context.input_bundle.model_dump(mode="json")
    )
    assert refs["admission:" + case.context.job.job_id] == case.context.job.payload_hash
    assert case.verifier.delivery(original) == original  # No legacy rewrite or verification bypass.


@pytest.mark.parametrize("issue", ["missing_replay", "insufficient", "unresolved_hurdle"])
def test_dlv_03_missing_or_insufficient_is_not_supported_negative(eval_connect, tmp_path, issue):
    case = delivery_case(
        eval_connect,
        tmp_path,
        replay=issue != "missing_replay",
        insufficient=issue == "insufficient",
        overall="insufficient_data" if issue == "unresolved_hurdle" else "fail",
    )
    names = failed(check(eval_connect, case))
    assert {
        "missing_replay": "reproduction",
        "insufficient": "measurement_quality",
        "unresolved_hurdle": "conclusion_support",
    }[issue] in names


@pytest.mark.parametrize("issue", ["missing", "hash", "cross_program", "payload", "receipt"])
def test_dlv_01_substitution_corruption_or_omission_refuses_pass(eval_connect, tmp_path, issue):
    case = delivery_case(eval_connect, tmp_path)
    if issue == "missing":
        case.proposal = changed(case.proposal, released_report_refs=[])
    elif issue == "hash":
        case.proposal = changed(
            case.proposal,
            released_report_refs=[changed(case.proposal.released_report_refs[0], sha256="e" * 64)],
        )
    elif issue == "cross_program":
        case.context = changed(case.context, job=changed(case.context.job, project_id=str(uuid4())))
    elif issue == "payload":
        identity = case.factor.manifest.artifact_version_id
        case.registry.values[identity] = (case.factor, b"tampered")
    else:
        with eval_connect() as conn:
            wrapper = conn.execute(
                "SELECT payload FROM eval.signed_measurement_receipts WHERE official_record_id=%s",
                [case.record.record_id],
            ).fetchone()[0]
        path = case.store.root / wrapper["receipt"]["files"]["measurement"]["relative_path"]
        path.write_bytes(b"tampered")
    assert check(eval_connect, case).result == "fail"


@pytest.mark.parametrize("issue", ["config", "brief", "paused", "budget", "baseline"])
def test_frozen_context_or_wait_cannot_pass_delivery(eval_connect, tmp_path, issue):
    case = delivery_case(eval_connect, tmp_path)
    context = case.context
    if issue == "config":
        context = changed(context, job=changed(context.job, config_hash="a" * 64))
    elif issue == "brief":
        context = changed(context, brief=changed(context.brief, objective="changed after freeze"))
    elif issue == "paused":
        context = changed(
            context, job=changed(context.job, state="paused", reason="operator_pause")
        )
    elif issue == "budget":
        context = changed(context, job=changed(context.job, reason="budget_exhausted"))
    else:
        context = changed(
            context, brief=changed(context.brief, baseline_artifact_ids=[str(uuid4())])
        )
    assert "frozen_context" in failed(check(eval_connect, case, context=context))


def test_unknown_requirements_or_self_supplied_results_are_rejected(eval_connect, tmp_path):
    case = delivery_case(eval_connect, tmp_path)
    gate = changed(case.context.job.exit_gate, required_checks=[*PILOT_DELIVERY_CHECKS, "unknown"])
    gate = changed(gate, spec_hash=gate_hash(gate))
    with pytest.raises(ValueError, match="unsupported"):
        validate_pilot_delivery_gate(gate)
    with pytest.raises(ValidationError):
        changed(case.proposal, checks=[dict(result="pass")])
    with pytest.raises(ValidationError):
        changed(case.proposal, conclusion="supported_positive", shortlist=[])


def test_frozen_human_signoff_exactly_binds_proposal_and_gate(eval_connect, tmp_path):
    case = delivery_case(eval_connect, tmp_path)
    gate = changed(case.context.job.exit_gate, human_signoff_required=True)
    gate = changed(gate, spec_hash=gate_hash(gate))
    brief = changed(case.context.brief, exit_gate=gate)
    job = changed(
        case.context.job,
        exit_gate=gate,
        payload_hash=admission_hash(case.context.input_bundle, brief),
    )
    context = changed(case.context, brief=brief, job=job)
    assert "human_signoff" in failed(check(eval_connect, case, context=context))
    approval = dict(
        approval_id=str(uuid4()),
        gate_spec_hash=gate.spec_hash,
        proposal_sha256=digest(case.proposal.model_dump(mode="json")),
        decision="approve",
        principal="synthetic-human",
        recorded_at=datetime.now(UTC),
    )
    context = changed(context, human_approval=approval)
    assert check(eval_connect, case, context=context).result == "pass"
    approval["proposal_sha256"] = "b" * 64
    assert "human_signoff" in failed(
        check(eval_connect, case, context=changed(context, human_approval=approval))
    )


def test_checker_payload_budget_is_independent_of_declared_artifact_hash(eval_connect, tmp_path):
    case = delivery_case(eval_connect, tmp_path)
    assert "artifact_integrity" in failed(
        check(eval_connect, case, policy=changed(case.policy, maximum_payload_bytes=1))
    )


def test_every_frozen_required_protocol_needs_matching_released_evidence(eval_connect, tmp_path):
    case = delivery_case(eval_connect, tmp_path)
    gate = changed(
        case.context.job.exit_gate,
        protocol_refs=[*case.context.job.exit_gate.protocol_refs, "another@1"],
    )
    gate = changed(gate, spec_hash=gate_hash(gate))
    brief = changed(case.context.brief, exit_gate=gate)
    context = changed(
        case.context,
        brief=brief,
        job=changed(
            case.context.job,
            exit_gate=gate,
            payload_hash=admission_hash(case.context.input_bundle, brief),
        ),
    )
    assert "released_evidence" in failed(check(eval_connect, case, context=context))
