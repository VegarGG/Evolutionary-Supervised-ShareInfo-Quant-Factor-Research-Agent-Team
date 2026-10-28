"""Private evaluator schemas/examples, excluded from every public export catalog."""

import argparse
import json
from pathlib import Path

from qfr_core.configuration import load_yaml
from qfr_core.contracts.artifacts import ArtifactDefinition
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.dsl.language import analyze, canonical_hash, parse
from qfr_eval.backtest.prefix import PrefixCheck
from qfr_eval.execution_bundle import ArtifactExecutionBundle
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import (
    EvaluationRequest,
    Measurement,
    MeasurementReceipt,
    OfficialRecord,
    RegistryExecutionBinding,
    ReproductionResult,
    RuntimeIdentity,
    StoredFile,
    TrialLedgerEntry,
)
from qfr_eval.runtime_contracts import (
    THREAD_VARIABLES,
    AccelerateImage,
    AppleAccelerateExecution,
    NumericalExecution,
    NumericalLibrary,
)
from qfr_eval.sandbox.models import SandboxProfile, SandboxReadiness
from qfr_eval.scheduler.dedup import digest
from qfr_eval.scheduler.models import (
    DevelopmentBehavior,
    IntakeCampaign,
    IntakePolicy,
    PilotScreeningPolicy,
)
from qfr_eval.screening.models import (
    CausalityEvidence,
    CoverageEvidence,
    KindAdapterProfile,
    ScreeningExecutionPolicy,
    ScreeningSessionConfiguration,
)
from qfr_eval.screening.records import (
    ScreeningOutcome,
    ScreeningReceipt,
    ScreeningRecord,
    ScreeningRequest,
    ScreeningTrial,
)
from qfr_eval.statistics.bootstrap import Interval
from qfr_eval.statistics.clustering import BehavioralFingerprint, ClusterSnapshot
from qfr_eval.statistics.family import FamilyInterval, FamilyStatistics, TrialObservation
from qfr_eval.statistics.hurdles import TurnoverResult
from qfr_eval.statistics.incremental import IncrementalResult

ROOT = Path(__file__).resolve().parents[1]


def generate(check=False):
    protocol = load_yaml(
        ROOT / "configs/evaluation/pilot_p0_p1_verification_v1.yaml", FrozenProtocol
    )
    valid = protocol.model_dump(mode="json")
    invalid = dict(valid)
    invalid.pop("approval_ref")
    outputs = {
        "FrozenProtocol.schema.json": FrozenProtocol.model_json_schema(),
        "FrozenProtocol.valid.json": valid,
        "FrozenProtocol.invalid.json": invalid,
    }
    interval = dict(
        status="insufficient_data",
        estimate=None,
        ci_lower=None,
        ci_upper=None,
        standard_error=None,
        valid_periods=0,
        time_slots=0,
        block_length=4,
        draws=10000,
        valid_draws=0,
        seed=123,
        confidence=0.95,
        index_sha256=None,
        small_sample_warning=True,
    )
    Interval.model_validate(interval)
    outputs.update(
        {
            "Interval.schema.json": Interval.model_json_schema(),
            "Interval.valid.json": interval,
            "Interval.invalid.json": {**interval, "status": "pass_despite_missing"},
        }
    )
    missing = {"value": None, "missing_reason": "insufficient_data"}
    samples = [
        (
            PrefixCheck,
            dict(
                cutoff="2021-12-31",
                compared_cells=0,
                full_prefix_hashes={"weekly": "0" * 64},
                rebuilt_hashes={"weekly": "0" * 64},
            ),
        ),
        (
            FamilyInterval,
            dict(
                status="insufficient_data",
                raw_trials=1,
                means=[None],
                standard_errors=[None],
                adjusted_p=[None],
                ci_lower=[None],
                ci_upper=[None],
                block_length=4,
                draws=10000,
                index_sha256=None,
                method="romano_wolf_stepdown_studentized_maxT",
                interval_method="simultaneous_full_family_maxT_envelope",
            ),
        ),
        (
            FamilyStatistics,
            dict(
                raw_trials=1,
                effective_trials=None,
                failed_trials=1,
                withheld_trials=0,
                diagnostic_trials=0,
                dsr=missing,
                pbo=missing,
                pbo_cohort="insufficient_data",
                hlz_t=missing,
                hlz_status="insufficient_data",
                rank_in_family=None,
            ),
        ),
        (
            TrialObservation,
            dict(
                trial_id="fixture",
                artifact_version_id="fixture",
                family_id="fixture",
                economic_lineage_id="fixture",
                generation_id="fixture",
                program_id="fixture",
                protocol_hash="0" * 64,
                snapshot_id="fixture",
                window="validation",
                cohort_id="fixture",
                status="failed",
                selectable=False,
                sampling_unit="mature_matched_decision",
                returns=[None],
                observation_ids=["date1"],
            ),
        ),
    ]
    samples.append(
        (
            IncrementalResult,
            dict(
                convention="partial_spearman_ols_intercept",
                status="insufficient_data",
                period_rank_ic={},
                mean_rank_ic=missing,
                pool_correlations={"baseline": missing},
                max_pool_correlation=missing,
                pool_argmax=None,
                valid_periods=0,
            ),
        )
    )
    samples.append(
        (
            TurnoverResult,
            dict(
                status="insufficient_data",
                eligible_decisions=0,
                missing_decisions=0,
                excluded_initial=0,
                exceedances=None,
                threshold=None,
                mean=None,
                p95=None,
                maximum=None,
            ),
        )
    )
    for model, sample in samples:
        model.model_validate(sample)
        outputs.update(
            {
                model.__name__ + ".schema.json": model.model_json_schema(),
                model.__name__ + ".valid.json": sample,
                model.__name__ + ".invalid.json": {**sample, "unapproved": True},
            }
        )
    from datetime import UTC, datetime
    from uuid import UUID

    from qfr_core.contracts.reports import EvidenceIdentity

    runtime = RuntimeIdentity(
        evaluator_git_sha="1" * 40,
        implementation_sha256="1" * 64,
        image_digest="2" * 64,
        software={"python": "3.12.14"},
    )
    library = NumericalLibrary(
        user_api="blas",
        internal_api="openblas",
        prefix="fixture",
        version="fixture",
        num_threads=1,
        architecture=None,
        threading_layer="pthreads",
        binary_sha256="0" * 64,
    )
    execution = NumericalExecution(
        schema_version="1",
        system="fixture",
        machine="fixture",
        polars_threads=1,
        thread_environment={
            key: "1" if key in {"POLARS_MAX_THREADS", "OPENBLAS_NUM_THREADS"} else None
            for key in THREAD_VARIABLES
        },
        libraries=[library],
    )
    pinned_runtime = runtime.model_copy(
        update={"schema_version": "2", "numerical_execution": execution}
    )
    apple_image = AccelerateImage(
        install_name="/System/Library/Frameworks/Accelerate.framework/libBLAS.dylib",
        image_uuid="00000000-0000-0000-0000-000000000001",
        cpu_type=16777228,
        cpu_subtype=0,
        text_bytes=4096,
        text_sha256="0" * 64,
    )
    apple = AppleAccelerateExecution(
        schema_version="1",
        policy_sha256="0" * 64,
        threading_mode="single_threaded",
        threading_scope="calling_thread",
        effective_threads=1,
        os_version="fixture",
        os_build="fixture",
        hardware_model="fixture",
        cpu_brand="fixture",
        consumers={"numpy": "accelerate", "scipy": "accelerate"},
        extension_hashes={"fixture": "0" * 64},
        images=[
            apple_image,
            apple_image.model_copy(
                update={"install_name": apple_image.install_name.replace("libBLAS", "libLAPACK")}
            ),
        ],
    )
    for value in (library, execution, pinned_runtime, apple_image, apple):
        model = type(value)
        name = "RuntimeIdentityV2" if model is RuntimeIdentity else model.__name__
        sample = value.model_dump(mode="json")
        outputs.update(
            {
                name + ".schema.json": model.model_json_schema(),
                name + ".valid.json": sample,
                name + ".invalid.json": {**sample, "unapproved": True},
            }
        )
    request = EvaluationRequest(
        schema_version="1",
        variant="baseline",
        artifact_version_id=UUID(int=1),
        content_hash="3" * 64,
        protocol_id=protocol.protocol_id,
        protocol_version=protocol.version,
        protocol_hash=protocol.sha256,
        snapshot_id="4" * 64,
        epoch_id="fixture",
        window="validation",
        cycle="weekly",
        program_id="fixture",
        family_id="fixture",
        economic_lineage_id="fixture",
        generation_id="fixture",
        cohort_id="fixture",
        intent="evaluated",
        runtime=runtime,
    )
    observation = TrialObservation.model_validate(samples[3][1])
    identity = EvidenceIdentity(
        artifact_version_id=str(request.artifact_version_id),
        content_hash=request.content_hash,
        protocol_version=request.protocol_version,
        dataset_version_id=request.snapshot_id,
        evaluator_version=runtime.evaluator_git_sha,
    )
    measured = Measurement(
        status="failed",
        metrics={"extreme_macro_recall": missing},
        reason_codes=["LOW_COVERAGE"],
        observation=observation,
        period_count=0,
        used_seeds={},
        uncertainty=None,
        sensitivity=[],
        family_interval=None,
        family_statistics=None,
        incremental=None,
        turnover={},
        hurdle={"overall": "insufficient_data"},
        diagnostics={},
    )
    record = OfficialRecord(
        schema_version="1",
        record_id="fixture",
        identity=identity,
        epoch_id="fixture",
        window="validation",
        stage="measurement",
        run_ids=["fixture"],
        image_digest=runtime.image_digest,
        protocol_hash=protocol.sha256,
        request_hash=request.sha256,
        sampling_unit="mature_matched_decision",
        cycle="weekly",
        seed=1,
        status="failed",
        metrics=measured.metrics,
        series_refs=[],
        results_hash=measured.results_hash,
        reason_codes=measured.reason_codes,
        created_by="fixture",
        request_id="fixture",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    trial = TrialLedgerEntry(
        schema_version="1",
        trial_id=observation.trial_id,
        official_record_id=record.record_id,
        identity=identity,
        window="validation",
        epoch_id="fixture",
        family_id="fixture",
        program_id="fixture",
        status="failed",
        selectable=False,
        sampling_unit="mature_matched_decision",
        sharpe_per_period=missing,
        n_obs=0,
        skew=missing,
        kurt_raw=missing,
        fingerprint_ref=None,
        observation=observation,
        counted_at=record.created_at,
    )
    file = StoredFile(
        sha256="5" * 64,
        bytes=12,
        relative_path="objects/fixture.json",
        media_type="application/json",
        logical_sha256=None,
    )
    receipt = MeasurementReceipt(
        schema_version="1",
        kind="private_measurement",
        authenticity="internal_unsigned",
        record_id=record.record_id,
        trial_id=trial.trial_id,
        identity=identity,
        protocol_hash=protocol.sha256,
        dataset_manifest_hash="6" * 64,
        implementation_sha256=runtime.implementation_sha256,
        image_digest=runtime.image_digest,
        request_hash=request.sha256,
        results_hash=record.results_hash,
        files={"record": file},
        receipt_hash="7" * 64,
    )
    reproduction = ReproductionResult(
        record_id="fixture",
        status="match",
        expected_results_hash=record.results_hash,
        actual_results_hash=record.results_hash,
        series_match=True,
        fingerprint_match=True,
        clusters_match=True,
        checked_files=1,
        verification_only=True,
    )
    fingerprint = BehavioralFingerprint(
        schema_version="1",
        definition="pilot_full_development_weekly_v1",
        protocol_hash=protocol.sha256,
        snapshot_id=request.snapshot_id,
        epoch_id=request.epoch_id,
        artifact_version_id=str(request.artifact_version_id),
        content_hash=request.content_hash,
        seed=protocol.diagnostics.purpose_seeds["fingerprint"],
        start="2020-01-01",
        end="2022-12-31",
        grid=[("2020-01-02", "a"), ("2020-01-02", "b")],
        ranks=[1, 2],
    )
    clusters = ClusterSnapshot(
        schema_version="1",
        algorithm="mean_absolute_spearman_single_linkage",
        status="insufficient_data",
        basis="behavioral_clusters",
        threshold=0.7,
        maximum_trials=20000,
        trial_ids=[trial.trial_id],
        raw_trials=1,
        effective_trials=None,
        groups=[],
        fingerprint_hashes={trial.trial_id: None},
        missing_trials=[trial.trial_id],
        reason="missing_fingerprint",
    )
    for value in [
        runtime,
        request,
        measured,
        record,
        trial,
        file,
        receipt,
        reproduction,
        fingerprint,
        clusters,
    ]:
        model = type(value)
        sample = value.model_dump(mode="json")
        outputs.update(
            {
                model.__name__ + ".schema.json": model.model_json_schema(),
                model.__name__ + ".valid.json": sample,
                model.__name__ + ".invalid.json": {**sample, "unapproved": True},
            }
        )
    screening = PilotScreeningPolicy.model_validate_json(
        (ROOT / "configs/evaluation/pilot_screening_v1.json").read_bytes()
    )
    intake = IntakePolicy.model_validate_json(
        (ROOT / "configs/evaluation/intake_v1.json").read_bytes()
    )
    campaign = IntakeCampaign.model_validate(
        {
            "schema_version": "1",
            "campaign_id": "00000000-0000-4000-8000-000000000001",
            "active": False,
            "owner_authorization_ref": "synthetic-owner-scope",
            "program_ids": ["synthetic-program"],
            "protocol_ref": protocol.protocol_id,
            "protocol_hash": protocol.sha256,
            "snapshot_id": "0" * 64,
            "runtime_hash": "0" * 64,
            "screening_policy_hash": screening.sha256,
            "server_generation_id": "synthetic-generation",
            "allowed_kinds": ["factor"],
            "root_lineages": {},
        }
    )
    behavior = DevelopmentBehavior.model_validate(
        {
            "schema_version": "1",
            "semantic_scope_sha256": "0" * 64,
            "complete_original_eligible_outputs": True,
            "tables": {"scores": {"columns": ["score"], "dtypes": ["Float64"], "rows": [[1.0]]}},
            "score_columns": {"scores": ["score"]},
        }
    )
    sandbox = SandboxProfile.model_validate_json(
        (ROOT / "configs/evaluation/sandbox_pilot_v2.json").read_bytes()
    )
    readiness = SandboxReadiness(
        schema_version="1",
        status="unavailable",
        profile_sha256=sandbox.sha256,
        image_digest="sha256:" + "0" * 64,
        host_os="unknown",
        architecture="unknown",
        runtime="runsc",
        checks={},
        reason_code="failed:backend_unavailable",
    )
    execution = ScreeningExecutionPolicy.model_validate_json(
        (ROOT / "configs/evaluation/screening_execution_v1.json").read_bytes()
    )
    adapter = KindAdapterProfile.model_validate_json(
        (ROOT / "configs/evaluation/kind_adapter_fixture_v1.json").read_bytes()
    )
    from qfr_core.contracts.publication import RegistryClientConfiguration
    from qfr_core.dsl.language import DSLConfig

    session = ScreeningSessionConfiguration(
        schema_version="1",
        campaign=campaign,
        intake_policy=intake,
        screening_policy=screening,
        execution_policy=execution,
        adapter_profiles={"generic": adapter},
        registry_client=RegistryClientConfiguration.model_validate_json(
            (ROOT / "contracts/examples/RegistryClientConfiguration.valid.json").read_bytes()
        ),
        dsl_configs={
            "pilot_industry_v1": DSLConfig.load(ROOT / "configs/dsl/pilot_industry_v1.json")
        },
        protocol_version=protocol.version,
        runtime=runtime,
        sandbox_profile=None,
        sandbox_image_digest=None,
    )
    causality = CausalityEvidence(
        schema_version="1",
        status="insufficient_data",
        code="insufficient_data",
        output_sha256=None,
        deterministic=None,
        prefix=[],
        perturbation=[],
        prefix_passed=None,
        perturbation_passed=None,
        label="lookahead tested, not certified",
    )
    coverage = CoverageEvidence(
        schema_version="1",
        status="insufficient_data",
        reason_codes=["LOW_COVERAGE"],
        required_observations=0,
        complete_observations=0,
        scored_cross_sections=0,
        constant_cross_sections=0,
        fixed_position_exempt=False,
        diagnostics=[],
    )
    screening_outcome = ScreeningOutcome(
        schema_version="1",
        kind="factor",
        execution="dsl",
        status="insufficient_data",
        reason_codes=["LOW_COVERAGE"],
        coverage=coverage,
        causality=causality,
        output_sha256=None,
        document_checks={},
    )
    screening_request = ScreeningRequest(
        schema_version="1",
        stage="screening",
        window="development",
        intake_id=UUID(int=11),
        campaign_id=campaign.campaign_id,
        artifact_version_id=request.artifact_version_id,
        content_hash=request.content_hash,
        program_id=request.program_id,
        family_id=request.family_id,
        protocol_id=protocol.protocol_id,
        protocol_version=protocol.version,
        protocol_hash=protocol.sha256,
        snapshot_id=request.snapshot_id,
        screening_policy_hash=screening.sha256,
        execution_policy_hash="0" * 64,
        adapter_profile_hash="0" * 64,
        development_input_sha256="0" * 64,
        probe_input_sha256=None,
        runtime=runtime,
        runner_image_digest=None,
        generation_id=campaign.server_generation_id,
    )
    screening_identity = identity.model_copy(
        update={"protocol_version": f"{protocol.protocol_id}@{protocol.version}"}
    )
    screening_record = ScreeningRecord(
        schema_version="1",
        stage="screening",
        record_id=UUID(int=12),
        trial_id=UUID(int=13),
        identity=screening_identity,
        request=screening_request,
        request_hash=screening_request.sha256,
        outcome=screening_outcome,
        results_hash=screening_outcome.sha256,
        feedback_disposition="eligible",
        created_by="fixture",
        request_id=UUID(int=14),
        created_at=record.created_at,
    )
    screening_trial = ScreeningTrial(
        schema_version="1",
        stage="screening",
        trial_id=screening_record.trial_id,
        official_record_id=screening_record.record_id,
        identity=screening_identity,
        program_id=request.program_id,
        family_id=request.family_id,
        generation_id=campaign.server_generation_id,
        window="development",
        status="failed",
        sampling_unit="eligible_observation",
        required_observations=0,
        complete_observations=0,
        results_hash=screening_outcome.sha256,
        counted_at=record.created_at,
    )
    screening_receipt = ScreeningReceipt(
        schema_version="1",
        kind="private_screening",
        authenticity="internal_unsigned",
        record_id=screening_record.record_id,
        trial_id=screening_trial.trial_id,
        identity=screening_identity,
        request_hash=screening_request.sha256,
        results_hash=screening_outcome.sha256,
        files={"record": file},
        receipt_hash="0" * 64,
    )
    # Self-consistent synthetic DSL publication, never a sandbox-readiness claim.
    publication = json.loads(
        (ROOT / "contracts/examples/PublishedArtifact.valid.json").read_bytes()
    )
    dsl = DSLConfig.load(ROOT / "configs/dsl/pilot_industry_v1.json")
    manifest = publication["manifest"]
    expression = "Ref($close,1)"
    analysis = analyze(parse(expression, dsl), dsl)
    manifest["implementation"]["expression"] = expression
    manifest["payload_files"] = []
    manifest["payload"]["fields_used"] = sorted(analysis.fields)
    manifest["payload"]["max_lookback_days"] = analysis.lookback
    manifest["complexity"] = analysis.complexity
    manifest["canonical_fingerprint"] = canonical_hash(expression, dsl)
    manifest["implementation_fingerprint"] = digest(
        {"implementation": manifest["implementation"], "payloads": []}
    )
    publication["dsl_policy_hash"] = digest(dsl.model_dump(mode="json"))
    definition = ArtifactDefinition.model_validate(
        {key: manifest[key] for key in ArtifactDefinition.model_fields}
    )
    manifest["content_hash"] = publication["payload_digest"] = digest(
        {
            "hash_spec": "qfr-publication/1",
            "profile": publication["profile"],
            "dsl_policy_hash": publication["dsl_policy_hash"],
            "manifest": definition.model_dump(mode="json", exclude={"family_id"}),
        }
    )
    bundle = ArtifactExecutionBundle(
        schema_version="1",
        artifact=PublishedArtifact.model_validate(publication),
        payloads_base64={},
        execution_policy=execution,
        adapter_profile=adapter,
        dsl_config=dsl,
        sandbox_profile=None,
        screening_backend=None,
    )
    binding = RegistryExecutionBinding(
        screening_record_id=UUID(int=1), screening_receipt_hash="0" * 64, execution_bundle=file
    )
    for value in (
        bundle,
        binding,
        screening,
        intake,
        campaign,
        behavior,
        sandbox,
        readiness,
        execution,
        adapter,
        session,
        causality,
        coverage,
        screening_outcome,
        screening_request,
        screening_record,
        screening_trial,
        screening_receipt,
    ):
        model = type(value)
        sample = value.model_dump(mode="json")
        outputs.update(
            {
                model.__name__ + ".schema.json": model.model_json_schema(),
                model.__name__ + ".valid.json": sample,
                model.__name__ + ".invalid.json": {**sample, "unapproved": True},
            }
        )
    for name, value in outputs.items():
        path = ROOT / "packages/qfr_eval/src/qfr_eval/private_contracts" / name
        content = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
        if check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(f"Private evaluator schema drift: {name}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    print(
        "Private evaluator contracts verified." if check else "Private evaluator contracts written."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    generate(parser.parse_args().check)
