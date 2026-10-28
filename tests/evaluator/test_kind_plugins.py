"""Trusted structural fixtures; actual runsc execution is tested separately."""

import base64
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import polars as pl
import pytest
from qfr_core.configuration import load_yaml
from qfr_core.contracts.artifacts import ArtifactManifest
from qfr_core.contracts.execution import ResearchNoteDocument, RunnerInput, RunnerOutput
from qfr_core.contracts.intake import ExecutionContract
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.contracts.reports import ReleasedReport
from qfr_core.dsl.language import DSLConfig
from qfr_core.runner_tables import pack_table
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.sandbox.models import SandboxProfile
from qfr_eval.sandbox.runner import SandboxRunner, SandboxUnavailable
from qfr_eval.screening.adapters import OutputAdapter, replay_strategy
from qfr_eval.screening.documents import ReleasedEvidence, check_note
from qfr_eval.screening.execution import StaticFailure, prepare_execution
from qfr_eval.screening.models import KindAdapterProfile, ScreeningExecutionPolicy
from qfr_eval.screening.pilot import PilotOutputError
from qfr_eval.screening.plugins import PLUGINS
from qfr_registry.seeds import dsl_seeds, note_seed, package_seed

ROOT = Path(__file__).resolve().parents[2]


def structural_artifact(request):
    """Not a registry receipt: tests below do not claim publication acceptance."""
    body = request.manifest.model_dump(mode="json")
    body.update(
        artifact_version_id=str(uuid4()),
        artifact_id=str(uuid4()),
        family_id=str(uuid4()),
        content_hash="0" * 64,
        implementation_fingerprint="0" * 64,
        canonical_fingerprint=None,
        created_at="2026-10-26T00:00:00Z",
        created_by="synthetic-test",
    )
    return PublishedArtifact(
        manifest=ArtifactManifest.model_validate(body),
        profile=request.profile,
        version_no=1,
        published_seq=1,
        dsl_policy_hash=None,
        payload_digest="0" * 64,
    )


@pytest.fixture
def case():
    policy = ScreeningExecutionPolicy.model_validate_json(
        (ROOT / "configs/evaluation/screening_execution_v1.json").read_bytes()
    )
    profile = KindAdapterProfile.model_validate_json(
        (ROOT / "configs/evaluation/kind_adapter_fixture_v1.json").read_bytes()
    )
    protocol = load_yaml(
        ROOT / "configs/evaluation/pilot_p0_p1_verification_v1.yaml", FrozenProtocol
    )
    sandbox_profile = SandboxProfile.model_validate_json(
        (ROOT / "configs/evaluation/sandbox_pilot_v2.json").read_bytes()
    )
    sandbox = SandboxRunner(sandbox_profile, "sha256:" + "0" * 64)
    limits = dict(
        cpu_seconds=sandbox_profile.cpu_seconds,
        memory_bytes=sandbox_profile.memory_bytes,
        timeout_seconds=sandbox_profile.timeout_seconds,
        max_output_bytes=sandbox_profile.max_output_bytes,
        network="none",
        read_only_root=True,
        non_root=True,
        dropped_capabilities="ALL",
    )
    contract = ExecutionContract(
        runner="qfr-json-runner/1",
        image_digest=sandbox.image,
        dependency_lock_sha256=sandbox_profile.dependency_lock_sha256,
        interface="function",
        command=None,
        function="runner.py:run",
        input_schema_ref="RunnerInput/1",
        output_schema_ref="RunnerOutput/1",
        seeds=[123],
        limits=limits,
        approved_sandbox_profile_ref=sandbox_profile.profile_id,
    )

    def artifact(kind):
        req = package_seed(
            ROOT,
            "program-example",
            "kind-" + kind,
            kind,
            contract,
            source=(ROOT / "fixtures/artifacts/runners/generic.py").read_bytes(),
            weights={"kind": kind, "coefficient": 0.5},
            source_hashes=[],
        )
        return structural_artifact(req), {
            item.asset_id: base64.b64decode(item.data_base64) for item in req.files
        }

    prices = pl.DataFrame(
        [
            (date(2021, 1, 1) + timedelta(days=i), code, float(10 + i * j))
            for i in range(8)
            for j, code in enumerate(("a", "b"), start=1)
        ],
        schema={"date": pl.Date, "code": pl.String, "close": pl.Float64},
        orient="row",
    )
    request = RunnerInput(schema_version="1", seed=123, tables={"prices": pack_table(prices)})
    return artifact, request, prices, policy, profile, protocol, sandbox


def test_every_kind_has_explicit_stages_and_no_later_stage(case):
    make, request, _, policy, profile, protocol, _ = case
    assert {k.value for k in PLUGINS} == {
        "factor",
        "model",
        "strategy",
        "research_note",
        "data_product",
    }
    artifact, _ = make("model")
    plugin = PLUGINS["model"]
    assert plugin.stages == ("screening",)
    with pytest.raises(ValueError, match="not implemented"):
        plugin.run(
            "release",
            artifact,
            adapter=OutputAdapter(artifact, profile, protocol),
            execution_policy=policy,
            development=request,
            probes=None,
            prepared=None,
            first=None,
            document=None,
            released=ReleasedEvidence({}, {}, frozenset()),
        )


def test_model_freezes_weights_inference_and_static_imports_without_execution(case):
    make, _, _, policy, _, _, sandbox = case
    artifact, assets = make("model")
    prepared = prepare_execution(artifact, assets, policy, None, sandbox, anonymous_universe=())
    assert prepared.mode == "sandbox"
    assert sandbox._ready is None  # Static inspection did not start Docker or execute a module.
    with pytest.raises(StaticFailure, match="DECLARATION_MISMATCH"):
        prepare_execution(
            artifact,
            {**assets, "weights": b'{"coefficient":100}'},
            policy,
            None,
            sandbox,
            anonymous_universe=(),
        )
    with pytest.raises(SandboxUnavailable):
        prepare_execution(artifact, assets, policy, None, None, anonymous_universe=())
    # A self-consistent external asset checksum still cannot replace the frozen
    # weights actually present in the immutable inference package.
    substituted = b'{"kind":"model","coefficient":100}'
    new_files = [
        p.model_copy(update={"sha256": hashlib.sha256(substituted).hexdigest()})
        if p.asset_id == "weights"
        else p
        for p in artifact.manifest.payload_files
    ]
    altered = artifact.model_copy(
        update={"manifest": artifact.manifest.model_copy(update={"payload_files": new_files})}
    )
    with pytest.raises(StaticFailure, match="DECLARATION_MISMATCH"):
        prepare_execution(
            altered,
            {**assets, "weights": substituted},
            policy,
            None,
            sandbox,
            anonymous_universe=(),
        )
    changed = artifact.manifest.model_copy(
        update={"payload": artifact.manifest.payload.model_copy(update={"serialization": "pickle"})}
    )
    with pytest.raises(StaticFailure, match="KIND_UNSUPPORTED"):
        prepare_execution(
            artifact.model_copy(update={"manifest": changed}),
            assets,
            policy,
            None,
            sandbox,
            anonymous_universe=(),
        )


def test_registry_dsl_adapter_executes_expression_not_a_builtin_substitute(case):
    _, request, prices, policy, profile, protocol, _ = case
    config = DSLConfig.load(ROOT / "configs/dsl/pilot_industry_v1.json")
    artifact = structural_artifact(dsl_seeds(ROOT, "program-example")[0])
    expression = "Ref($close, 1)"
    manifest = artifact.manifest.model_copy(
        update={
            "implementation": artifact.manifest.implementation.model_copy(
                update={"expression": expression}
            ),
            "payload": artifact.manifest.payload.model_copy(
                update={"max_lookback_days": 1, "fields_used": ["close"]}
            ),
        }
    )
    artifact = artifact.model_copy(update={"manifest": manifest})
    prepared = prepare_execution(artifact, {}, policy, config, None, anonymous_universe=())
    result = prepared.execute(request)
    assert result.code == "ok" and result.output is not None
    actual = result.output.tables["output"]
    expected = (
        prices.sort("code", "date")
        .select("date", "code", pl.col("close").shift(1).over("code").alias("score"))
        .sort("date", "code")
    )
    assert actual == pack_table(expected)
    adapter = OutputAdapter(artifact, profile, protocol)
    assert adapter.quality(result.output, request).status == "passed"
    behavior = adapter.behavior(result.output, request, "0" * 64)
    assert behavior.tables["output"].rows
    invalid = artifact.model_copy(
        update={
            "manifest": artifact.manifest.model_copy(
                update={
                    "implementation": artifact.manifest.implementation.model_copy(
                        update={"expression": "Unknown($close, 1)"}
                    )
                }
            )
        }
    )
    assert (
        prepare_execution(invalid, {}, policy, config, None, anonymous_universe=())
        .execute(request)
        .code
        == "failed:invalid_output"
    )


def test_strategy_replays_own_weights_next_close_drift_cash_and_declared_cost(case):
    make, request, prices, _, profile, protocol, _ = case
    artifact, _ = make("strategy")
    frame = prices.select("date", "code", pl.lit(0.5).alias("weight"))
    output = RunnerOutput(schema_version="1", kind="strategy", tables={"output": pack_table(frame)})
    adapter = OutputAdapter(artifact, profile, protocol)
    assert PLUGINS["strategy"].eligibility(artifact, profile) is None
    assert adapter.quality(output, request).status == "passed"
    ledger = replay_strategy(output, request, profile)
    first = ledger.row(0, named=True)
    assert first["entry_date"] == date(2021, 1, 2)
    assert first["exit_date"] == date(2021, 1, 3)
    assert first["one_way_turnover"] == 1  # Explicit initial cash-to-position transfer.
    assert first["gross_return"] == pytest.approx(0.5 * (12 / 11 - 1) + 0.5 * (14 / 12 - 1))
    assert ledger["status"].to_list()[-2:] == ["unmatured", "unmatured"]
    assert 0 < ledger["one_way_turnover"][1] < 1  # Drift, not a fabricated zero.
    # This synthetic arithmetic variation is not an activated pilot cost change.
    cost_profile = profile.model_copy(update={"strategy_cost_bps": 10})
    charged = replay_strategy(output, request, cost_profile)
    assert first["gross_return"] - charged["net_return"][0] == pytest.approx(0.001)
    assert (
        PLUGINS["strategy"].eligibility(
            artifact, profile.model_copy(update={"strategy_cost_policy_ref": "unknown"})
        )
        == "DECLARATION_MISMATCH"
    )


@pytest.mark.parametrize("corruption", ["missing", "future", "wrong_value"])
def test_data_product_rejects_missing_future_or_changed_identity_data(case, corruption):
    make, request, prices, _, profile, protocol, _ = case
    artifact, _ = make("data_product")
    adapter = OutputAdapter(artifact, profile, protocol)
    good = RunnerOutput(
        schema_version="1", kind="data_product", tables={"output": pack_table(prices)}
    )
    assert adapter.quality(good, request).status == "passed"
    bad = (
        prices.slice(1)
        if corruption == "missing"
        else prices.with_columns(
            (pl.col("date") + timedelta(days=1))
            if corruption == "future"
            else (pl.col("close") * 2)
        )
    )
    with pytest.raises(PilotOutputError):
        adapter.quality(good.model_copy(update={"tables": {"output": pack_table(bad)}}), request)


def note_case(case):
    *_, policy, _profile, _protocol, _sandbox = case
    request = note_seed(ROOT, "program-example")
    artifact = structural_artifact(request)
    report = json.loads((ROOT / "contracts/examples/ReleasedReport.valid.json").read_bytes())
    report["content"]["scalar"]["measurement"] = {"value": 0.5, "missing_reason": None}
    released = ReleasedReport.model_validate(report)
    path = ["content", "scalar", "measurement", "value"]
    doc = ResearchNoteDocument(
        schema_version="1",
        title="Structured note",
        body="The cited scalar is reproduced below.",
        citation_refs=[released.report_id],
        numeric_claims=[dict(report_id=released.report_id, field_path=path, value=0.501)],
    )
    manifest = artifact.manifest.model_copy(
        update={
            "implementation": artifact.manifest.implementation.model_copy(
                update={"format": "json"}
            ),
            "payload": artifact.manifest.payload.model_copy(
                update={
                    "citation_refs": [released.report_id],
                    "released_report_refs": [released.report_id],
                }
            ),
        }
    )
    view = ReleasedEvidence(
        {released.report_id: released}, {(released.report_id, tuple(path)): 0.01}, frozenset()
    )
    return artifact.model_copy(update={"manifest": manifest}), doc, policy, view


@pytest.mark.parametrize(
    "corruption",
    [
        "none",
        "missing",
        "cross_program",
        "withheld",
        "private_field",
        "out_of_rounding",
        "unstructured_numeric",
        "unknown_precision",
    ],
)
def test_notes_only_validate_known_released_claims_and_rounding(case, corruption):
    artifact, doc, policy, view = note_case(case)
    if corruption == "missing":
        view.reports.clear()
    elif corruption == "cross_program":
        view.reports["report-example"] = view.reports["report-example"].model_copy(
            update={"program_id": "another"}
        )
    elif corruption == "withheld":
        body = view.reports["report-example"].model_dump(mode="json")
        body["content"]["scalar"]["measurement"] = {"value": None, "missing_reason": "withheld"}
        view.reports["report-example"] = ReleasedReport.model_validate(body)
    elif corruption == "private_field":
        doc = doc.model_copy(
            update={
                "numeric_claims": [
                    doc.numeric_claims[0].model_copy(
                        update={"field_path": ["content", "W3", "sharpe"]}
                    )
                ]
            }
        )
    elif corruption == "out_of_rounding":
        doc = doc.model_copy(
            update={"numeric_claims": [doc.numeric_claims[0].model_copy(update={"value": 0.52})]}
        )
    elif corruption == "unstructured_numeric":
        doc = doc.model_copy(update={"body": "Claims 99 percent without structured evidence."})
    elif corruption == "unknown_precision":
        view.granularities.clear()
    outcome = check_note(artifact, doc.model_dump_json().encode(), policy, view)
    assert outcome.status == ("passed" if corruption == "none" else "failed")
    assert outcome.output_sha256 is None
    assert "99 percent" not in outcome.model_dump_json()


def test_plain_seed_note_is_a_document_not_a_factor(case):
    _, _, _, policy, _, _, _ = case
    request = note_seed(ROOT, "program-example")
    data = base64.b64decode(request.files[0].data_base64)
    assert hashlib.sha256(data).hexdigest() == request.manifest.payload_files[0].sha256
    result = check_note(
        structural_artifact(request), data, policy, ReleasedEvidence({}, {}, frozenset())
    )
    assert result.status == "passed" and result.kind == "research_note"


@pytest.mark.parametrize("format", ["json", "csv", "parquet"])
def test_data_document_schema_temporal_checks_and_resource_bounds(case, format):
    import io

    from qfr_core.contracts.artifacts import DocumentImplementation
    from qfr_eval.screening.documents import check_data_document

    make, request, prices, policy, profile, protocol, _ = case
    artifact, _ = make("data_product")
    artifact = artifact.model_copy(
        update={
            "manifest": artifact.manifest.model_copy(
                update={
                    "implementation": DocumentImplementation(
                        type="document", asset_id="data", format=format
                    )
                }
            )
        }
    )
    if format == "json":
        data = (
            RunnerOutput(
                schema_version="1", kind="data_product", tables={"output": pack_table(prices)}
            )
            .model_dump_json()
            .encode()
        )
    elif format == "csv":
        data = prices.write_csv().encode()
    else:
        stream = io.BytesIO()
        prices.write_parquet(stream)
        data = stream.getvalue()
    adapter = OutputAdapter(artifact, profile, protocol)
    outcome, _ = check_data_document(artifact, data, request, adapter, policy)
    assert outcome.status == "passed" and outcome.document_checks["temporal"] == "pass"
    limited = policy.model_copy(update={"document_rows": 1})
    assert check_data_document(artifact, data, request, adapter, limited)[0].status == "failed"


def test_kind_status_projection_cannot_leak_budget_withheld_failure_reasons():
    from qfr_eval.screening.records import ScreeningRecord

    record = ScreeningRecord.model_validate_json(
        (
            ROOT / "packages/qfr_eval/src/qfr_eval/private_contracts/ScreeningRecord.valid.json"
        ).read_bytes()
    )
    assert record.outcome.reason_codes
    status, reasons = PLUGINS[record.outcome.kind].release_mapping(record)
    assert status.status == "failed" and reasons == record.outcome.reason_codes
    withheld = record.model_copy(update={"feedback_disposition": "withheld:budget"})
    status, reasons = PLUGINS[record.outcome.kind].release_mapping(withheld)
    assert status.status == "withheld" and reasons == []
