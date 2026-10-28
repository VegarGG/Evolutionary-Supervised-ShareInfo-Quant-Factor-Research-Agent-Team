"""Actual published P0/P1 execution gates, reserved for the approved validation host.

An absent explicitly built core-only image is UNRUN. A supplied but unavailable
backend is a failure, never a skip or an in-process substitute. Numerical code on
the host is separately pinned from the real executable image used by runsc.
"""

import os
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import polars as pl
import pytest
from qfr_core.configuration import load_yaml
from qfr_core.contracts.execution import RunnerInput
from qfr_core.contracts.intake import ExecutionContract
from qfr_core.data_layer.pilot import PilotConfig
from qfr_core.dsl.language import DSLConfig
from qfr_core.pilot.features import PilotFeatureConfig, price_features
from qfr_core.pilot.parity import assert_parity
from qfr_core.registry_client import RegistryClient
from qfr_core.runner_tables import pack_table, unpack_table
from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.backtest.pilot import evaluate_pilot
from qfr_eval.measurement import measure_pilot
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.protocols.store import activate_protocol, create_protocol
from qfr_eval.registry_execution import request_from_screen
from qfr_eval.reproduce import reproduce
from qfr_eval.runtime import builtin_definition, capture_runtime
from qfr_eval.sandbox.models import DockerNativeProfile, SandboxProfile
from qfr_eval.scheduler.dedup import digest
from qfr_eval.scheduler.intake import IntakeScheduler
from qfr_eval.scheduler.models import IntakeCampaign, IntakePolicy, PilotScreeningPolicy
from qfr_eval.screening.documents import ReleasedEvidence
from qfr_eval.screening.execution import prepare_execution
from qfr_eval.screening.models import KindAdapterProfile, ScreeningExecutionPolicy
from qfr_eval.screening.pilot import validate_pilot_output
from qfr_eval.screening.worker import InputSlices, ScreeningWorker
from qfr_eval.service import evaluate
from qfr_registry.seeds import dsl_seeds, pilot_seed

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.database
@pytest.mark.pilot
def test_registry_six_v4_dsl_features_equal_independent_polars(
    registry_http, program, pilot_sources
):
    _, tables, _ = pilot_sources
    policy = ScreeningExecutionPolicy.model_validate_json(
        (ROOT / "configs/evaluation/screening_execution_v1.json").read_bytes()
    )
    features = PilotFeatureConfig.model_validate_json(
        (ROOT / "configs/pilot/stage1_features.json").read_bytes()
    )
    tolerance = PilotConfig.model_validate_json(
        (ROOT / "configs/data/pilot_import.json").read_bytes()
    )
    dsl = DSLConfig.load(ROOT / "configs/dsl/pilot_industry_v1.json")
    panel = tables["features"].select("date", "code")
    codes = tables["universe"]["code"].to_list()
    prices = tables["prices_daily"].filter(pl.col("code").is_in(codes))
    expected = price_features(panel, prices, codes, features)
    inputs = RunnerInput(schema_version="1", seed=0, tables={"prices": pack_table(prices)})
    for publication in dsl_seeds(ROOT, program):
        artifact = registry_http.publish(publication).artifact
        prepared = prepare_execution(artifact, {}, policy, dsl, None, anonymous_universe=())
        result = prepared.execute(inputs)
        assert result.code == "ok" and result.output is not None and prepared.mode == "dsl"
        column = "v4_raw_" + artifact.manifest.name.removeprefix("v4-")
        daily = unpack_table(result.output.tables["output"]).rename(
            {"score": column, "date": "price_date"}
        )
        actual = panel.sort("code", "date").join_asof(
            daily.sort("code", "price_date"),
            left_on="date",
            right_on="price_date",
            by="code",
            strategy="backward",
            check_sortedness=False,
        )
        assert_parity(
            actual,
            expected,
            keys=["date", "code"],
            columns=[column],
            atol=tolerance.feature_parity_atol,
            rtol=tolerance.feature_parity_rtol,
        )


@pytest.fixture
def pilot_sandbox(backend_runner):
    image = os.environ.get("QFR_TEST_PILOT_SANDBOX_IMAGE")
    if image is None:
        pytest.skip("UNRUN: full pilot requires the explicitly built core-only sandbox image")
    profile = SandboxProfile.model_validate_json(
        (ROOT / "configs/evaluation/sandbox_pilot_v4.json").read_bytes()
    )
    if os.environ.get("QFR_TEST_SANDBOX_BACKEND") == "docker-native":
        profile = DockerNativeProfile.model_validate_json(
            (ROOT / "configs/evaluation/sandbox_docker_native_v3.json").read_bytes()
        )
    with backend_runner(profile, image) as runner:
        readiness = runner.readiness()
        assert readiness.status == "ready", readiness.model_dump(mode="json")
        yield runner


@pytest.fixture(params=[("P0", "baseline"), ("P1", "P1_reversal_momentum")])
def published_pilot(
    pilot_sandbox, request, registry_http, program, pilot_sources, eval_connect, tmp_path
):
    model, variant = request.param
    root, _, _ = pilot_sources
    protocol = load_yaml(
        ROOT / "configs/evaluation/pilot_p0_p1_verification_v1.yaml", FrozenProtocol
    )
    p = pilot_sandbox.profile
    contract = ExecutionContract(
        runner="qfr-json-runner/1",
        image_digest=pilot_sandbox.image,
        dependency_lock_sha256=p.dependency_lock_sha256,
        interface="function",
        command=None,
        function="runner.py:run",
        input_schema_ref="RunnerInput/1",
        output_schema_ref="RunnerOutput/1",
        seeds=[protocol.diagnostics.root_seed],
        limits=dict(
            cpu_seconds=p.cpu_seconds,
            memory_bytes=p.memory_bytes,
            timeout_seconds=p.timeout_seconds,
            max_output_bytes=p.max_output_bytes,
            network="none",
            read_only_root=True,
            non_root=True,
            dropped_capabilities="ALL",
        ),
        approved_sandbox_profile_ref=p.profile_id,
    )
    publication = pilot_seed(ROOT, root, program, model, contract)
    first = registry_http.publish(publication)
    assert registry_http.publish(publication).artifact == first.artifact
    artifact = first.artifact
    assets = {
        p.asset_id: registry_http.payload(artifact, p.asset_id)
        for p in artifact.manifest.payload_files
    }
    execution = ScreeningExecutionPolicy.model_validate_json(
        (ROOT / "configs/evaluation/screening_execution_v1.json").read_bytes()
    )
    return variant, artifact, assets, protocol, execution, EvidenceStore(tmp_path / "evidence")


@pytest.mark.database
@pytest.mark.pilot
def test_registry_p0_p1_original_oracle_is_reproduced_from_actual_outputs(
    published_pilot, pilot_sandbox, pilot_sources, pilot_runs
):
    variant, artifact, assets, protocol, execution, _ = published_pilot
    _, tables, oracle = pilot_sources
    # Historical preservation only: the original oracle is separate from the
    # approved protocol and creates no confirmation query or official trial.
    inputs = RunnerInput(
        schema_version="1",
        seed=protocol.diagnostics.root_seed,
        tables={
            name: pack_table(tables[source])
            for name, source in {
                "prices": "prices_daily",
                "features": "features",
                "universe": "universe",
            }.items()
        },
    )
    prepared = prepare_execution(
        artifact, assets, execution, None, pilot_sandbox, anonymous_universe=()
    )
    result = prepared.execute(inputs)
    assert result.code == "ok" and result.output is not None
    parsed = validate_pilot_output(result.output, inputs, oracle)
    actual = evaluate_pilot(
        parsed.panel,
        parsed.history,
        tables["prices_daily"],
        tables["calendar"],
        tables["universe"],
        oracle,
        variant="registry:" + artifact.manifest.artifact_version_id,
    )
    expected = pilot_runs[variant]
    for name in ("ledger", "periods", "predictions", "outcomes"):
        left, right = getattr(actual, name), getattr(expected, name)
        assert left.schema == right.schema and left.height == right.height
        keys = ["model_cycle", "period_key"] + (
            ["code"] if name in ("predictions", "outcomes") else []
        )
        # Only the explicit artifact label changes. Every value, rank, membership,
        # missing cell, coverage slot and timestamp remains hash/float exact.
        labels = {"variant", "decision_id"}
        assert_parity(
            left,
            right,
            keys=keys,
            columns=[c for c in left.columns if c not in keys and c not in labels],
            atol=0,
            rtol=0,
        )
        for label in labels & set(left.columns):
            assert (
                left[label]
                .str.replace(
                    "registry:" + artifact.manifest.artifact_version_id, variant, literal=True
                )
                .equals(right[label])
            )


@pytest.mark.database
@pytest.mark.pilot
def test_registry_p0_p1_screen_measure_and_reproduce_without_registry_network(
    published_pilot, pilot_sandbox, pilot_full_snapshot, registry_http, eval_connect, monkeypatch
):
    variant, artifact, _, protocol, execution, store = published_pilot
    runtime = capture_runtime(
        evaluator_git_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        image_digest=pilot_sandbox.image.removeprefix("sha256:"),
    )
    screening = PilotScreeningPolicy.model_validate_json(
        (ROOT / "configs/evaluation/pilot_screening_v1.json").read_bytes()
    )
    campaign = IntakeCampaign(
        schema_version="1",
        campaign_id=uuid4(),
        active=True,
        owner_authorization_ref="stage-3-original-pilot-acceptance",
        program_ids=[artifact.manifest.provenance.program_id],
        protocol_ref=protocol.protocol_id,
        protocol_hash=protocol.sha256,
        snapshot_id=pilot_full_snapshot.manifest.snapshot_id,
        runtime_hash=digest(runtime.model_dump(mode="json")),
        screening_policy_hash=screening.sha256,
        server_generation_id="original-pilot-verification",
        allowed_kinds=["model"],
        root_lineages={UUID(artifact.manifest.family_id): "frozen-original-pilot"},
    )
    scheduler = IntakeScheduler(
        registry_http,
        eval_connect,
        campaign,
        IntakePolicy.model_validate_json((ROOT / "configs/evaluation/intake_v1.json").read_bytes()),
        screening,
        {},
        principal="registry-pilot-test",
    )
    with eval_connect() as conn:
        create_protocol(
            conn,
            ROOT / "configs/evaluation/pilot_p0_p1_verification_v1.yaml",
            principal="registry-pilot-test",
            request_id=uuid4(),
        )
        activate_protocol(
            conn,
            protocol.protocol_id,
            protocol.version,
            expected_hash=protocol.sha256,
            principal="registry-pilot-test",
            request_id=uuid4(),
        )
    worker = ScreeningWorker(
        scheduler,
        protocol,
        runtime,
        InputSlices.from_snapshot(pilot_full_snapshot),
        store,
        execution,
        {
            "pilot_industry_v1": KindAdapterProfile.model_validate_json(
                (ROOT / "configs/evaluation/kind_adapter_pilot_v1.json").read_bytes()
            )
        },
        pilot_sandbox,
        worker="registry-pilot-test",
        released=ReleasedEvidence({}, {}, frozenset()),
    )
    assert scheduler.poll_once()["queued"] == 1
    screened = worker.run_once()
    assert screened.status == "recorded" and screened.receipt is not None

    def unavailable(*args, **kwargs):
        raise AssertionError("measurement/reproduction cannot access Registry transport")

    monkeypatch.setattr(RegistryClient, "request", unavailable)
    tables = {t.name: pilot_full_snapshot.read(t.name) for t in pilot_full_snapshot.manifest.tables}
    with eval_connect() as conn:
        for cycle in ("weekly", "monthly", "quarterly", "fixed_quarter"):
            request = request_from_screen(
                conn,
                screened.receipt.record_id,
                store,
                epoch_id="pilot-verification",
                cohort_id="registry-parity",
                window="validation",
                cycle=cycle,
            )
            record, receipt = evaluate(
                conn,
                request,
                pilot_full_snapshot,
                store,
                principal="registry-pilot-test",
                request_id=uuid4(),
            )
            assert record.status == "complete"
            assert record.identity.artifact_version_id == artifact.manifest.artifact_version_id
            builtin_id, builtin_hash, _ = builtin_definition(variant)
            trusted = request.model_copy(
                update={
                    "variant": variant,
                    "artifact_version_id": builtin_id,
                    "content_hash": builtin_hash,
                    "registry_execution": None,
                }
            )
            original = measure_pilot(
                trusted,
                protocol,
                tables,
                trial_id=receipt.trial_id,
                prior=[],
                prior_deltas={},
                effective_trials=1,
            )
            assert record.results_hash == original.summary.results_hash
            assert {
                "registry_execution_bundle",
                "registry_screening_receipt",
            } <= receipt.files.keys()
            if cycle == "weekly":
                before = conn.execute(
                    "SELECT count(*) FROM eval.trial_ledger WHERE payload->>'program_id'=%s",
                    [request.program_id],
                ).fetchone()
                replay = reproduce(
                    conn,
                    UUID(record.record_id),
                    pilot_full_snapshot,
                    store,
                    principal="registry-pilot-test",
                    request_id=uuid4(),
                )
                assert replay.status == "match" and replay.series_match and replay.fingerprint_match
                assert (
                    conn.execute(
                        "SELECT count(*) FROM eval.trial_ledger WHERE payload->>'program_id'=%s",
                        [request.program_id],
                    ).fetchone()
                    == before
                )
        assert conn.execute(
            "SELECT count(*) FROM eval.feedback_reservations WHERE artifact_version_id=%s",
            [request.artifact_version_id],
        ).fetchone() == (1,)
