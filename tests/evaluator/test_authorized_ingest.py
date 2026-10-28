"""P3.8 real-DB and filesystem boundaries using tiny synthetic source datasets."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import polars as pl
import psycopg
import pytest
from pydantic import ValidationError
from qfr_core.configuration import load_yaml
from qfr_core.contracts.data import ExposureAndQuality
from qfr_core.data_layer.catalog import read_registration, registered_snapshot
from qfr_core.data_layer.pilot import PilotConfig
from qfr_core.data_layer.snapshots import Snapshot, TableInput, file_hash, write_snapshot
from qfr_core.data_layer.synthetic import SyntheticConfig
from qfr_eval.ingest import command, service
from qfr_eval.ingest.cli import _quality
from qfr_eval.ingest.command import main
from qfr_eval.ingest.models import SnapshotBuildAuthorization, SnapshotBuildPlan
from qfr_eval.ingest.service import IngestConflict, ingest_once
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.scheduler.dedup import digest
from test_release_preparation import ROOT

pytestmark = pytest.mark.database


def changed(value, **changes):
    return type(value).model_validate({**value.model_dump(), **changes})


def fixture(root):
    source_root, output = root / "sources", root / "output"
    quality = _quality(True)
    dates = [date(2020, 1, 1) + timedelta(days=x) for x in range(10)]
    frame = pl.DataFrame(
        dict(date=dates, available=[d + timedelta(days=1) for d in dates], value=list(range(10)))
    )
    exposure = ExposureAndQuality(
        history="previously_seen",
        inspected_periods=[],
        training_tuning_history="Synthetic fixture",
        provider_knowledge_exposure="unknown",
        quality=quality,
        licence_constraints=["Synthetic"],
        unknowns=[],
    )
    source = write_snapshot(
        source_root,
        [
            TableInput("observations", frame, ("date",), quality, "Synthetic", "date", "available"),
            TableInput(
                "private_marker",
                frame,
                ("date",),
                quality,
                "Synthetic",
                "date",
                "available",
                research_visible=False,
            ),
        ],
        profile="synthetic-contract-fixture",
        zone="full",
        cutoff=None,
        as_of=date(2020, 1, 11),
        source="synthetic-source",
        build_code_version="fixture",
        exposure=exposure,
        conventions={"private_window": "private-marker-never-export"},
        principal="fixture",
        request_id=str(uuid4()),
    )
    plan = SnapshotBuildPlan(
        schema_version="1",
        plan_id=uuid4(),
        program_id=str(uuid4()),
        source_ref="authorized-synthetic-input",
        source=dict(
            kind="snapshot_replay",
            relative_path=source.path.relative_to(source_root).as_posix(),
            manifest_sha256=file_hash(source.path / "manifest.json"),
        ),
        research_cutoff=date(2020, 1, 5),
        as_of=date(2020, 1, 10),
        build_code_version="synthetic-test",
    )
    authorization = SnapshotBuildAuthorization(
        schema_version="1",
        enabled=True,
        plan_sha256=plan.sha256,
        authorization_ref="synthetic-test-authorization",
        authorized_principal="synthetic-owner",
        authorized_at=datetime.now(UTC) - timedelta(minutes=1),
        maximum_source_files=100,
        maximum_source_bytes=1048576,
        maximum_metadata_bytes=1048576,
        maximum_table_cells=1000,
        network="none",
        schedule="on_demand_only",
    )
    return SimpleNamespace(
        plan=plan,
        authorization=authorization,
        source_root=source_root,
        output=output,
        source=source,
    )


def run(factory, case, **kwargs):
    with factory() as conn:
        return ingest_once(
            conn,
            case.plan,
            case.authorization,
            source_root=case.source_root,
            fixtures_root=ROOT / "fixtures/pilot",
            output_root=case.output,
            principal="synthetic-owner",
            request_id=uuid4(),
            **kwargs,
        )


def test_ingest_publishes_only_authorized_research_slice_and_preserves_original(
    eval_connect, tmp_path
):
    case = fixture(tmp_path)
    before = {str(p): file_hash(p) for p in case.source.path.rglob("*") if p.is_file()}
    result = run(eval_connect, case)
    assert (
        read_registration(case.output / "research", result.registration_id, case.plan.program_id)
        == result
    )
    research = registered_snapshot(case.output / "research", result)
    full = Snapshot.load(case.output / "full" / result.dataset_version_id)
    assert research.read("observations")["value"].to_list() == [0, 1, 2, 3]
    assert full.read("observations")["value"].to_list() == list(range(9))
    assert {t.name for t in research.manifest.tables} == {"observations"}
    assert {t.name for t in full.manifest.tables} == {"observations", "private_marker"}
    assert "private-marker-never-export" not in result.model_dump_json()
    assert result.research_manifest.exposure == case.source.manifest.exposure
    assert all(file_hash(Path(p)) == value for p, value in before.items())
    assert (case.output / "full/_audit/events.jsonl").is_file()
    assert not (case.output / "events.jsonl").exists()
    with pytest.raises(ValueError, match="scope"):
        read_registration(case.output / "research", result.registration_id, "another-program")


def test_ingest_concurrent_retry_and_append_only_audit(eval_connect, tmp_path):
    case = fixture(tmp_path)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: run(eval_connect, case), range(2)))
    assert results[0] == results[1]
    with eval_connect() as conn:
        assert conn.execute(
            "SELECT state FROM eval.ingest_outcomes WHERE ingest_request_id=%s ORDER BY created_at",
            [case.plan.plan_id],
        ).fetchall() == [("built",), ("catalog_available",)]
        for table in ("ingest_requests", "ingest_outcomes"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"DELETE FROM eval.{table}")
        assert conn.execute(
            "SELECT count(*) FROM eval.events WHERE payload->>'entity_id'=%s",
            [str(case.plan.plan_id)],
        ).fetchone() == (1,)
    case.plan = changed(case.plan, source_ref="different-intent")
    case.authorization = changed(case.authorization, plan_sha256=case.plan.sha256)
    with pytest.raises(IngestConflict):
        run(eval_connect, case)


@pytest.mark.skipif(os.geteuid() == 0, reason="requires an unprivileged filesystem identity")
def test_ingest_writes_with_read_only_root_and_only_two_writable_zones(eval_connect, tmp_path):
    case = fixture(tmp_path)
    (case.output / "full").mkdir(parents=True)
    (case.output / "research").mkdir()
    case.output.chmod(0o555)
    try:
        result = run(eval_connect, case)
        assert (
            read_registration(
                case.output / "research", result.registration_id, case.plan.program_id
            )
            == result
        )
        assert not (case.output / "events.jsonl").exists()
    finally:
        case.output.chmod(0o755)


def test_ingest_rejects_nested_transaction_that_could_publish_before_commit(eval_connect, tmp_path):
    case = fixture(tmp_path)
    with eval_connect() as conn, conn.transaction():
        with pytest.raises(ValueError, match="idle autocommit"):
            ingest_once(
                conn,
                case.plan,
                case.authorization,
                source_root=case.source_root,
                fixtures_root=ROOT / "fixtures/pilot",
                output_root=case.output,
                principal="synthetic-owner",
                request_id=uuid4(),
            )
    assert not case.output.exists()


@pytest.mark.parametrize("issue", ["disabled", "hash", "principal", "future"])
def test_missing_exact_authorization_produces_no_build_or_catalog(eval_connect, tmp_path, issue):
    case = fixture(tmp_path)
    change = {
        "disabled": {"enabled": False},
        "hash": {"plan_sha256": "0" * 64},
        "principal": {"authorized_principal": "not-this-operator"},
        "future": {"authorized_at": datetime.now(UTC) + timedelta(days=1)},
    }[issue]
    case.authorization = changed(case.authorization, **change)
    with pytest.raises(PermissionError):
        run(eval_connect, case)
    assert not case.output.exists()
    with eval_connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM eval.ingest_requests WHERE id=%s", [case.plan.plan_id]
        ).fetchone() == (0,)


def test_ingest_crash_after_private_commit_recovers_without_replacing_evidence(
    eval_connect, tmp_path, monkeypatch
):
    case = fixture(tmp_path)
    original = service.publish_catalog
    monkeypatch.setattr(
        service, "publish_catalog", lambda *args: (_ for _ in ()).throw(OSError("fixture"))
    )
    with pytest.raises(OSError):
        run(eval_connect, case)
    with eval_connect() as conn:
        assert conn.execute(
            "SELECT state FROM eval.ingest_outcomes WHERE ingest_request_id=%s", [case.plan.plan_id]
        ).fetchall() == [("built",)]
    assert not (case.output / "research/catalog").exists()
    # Recovery verifies already built immutable snapshots, not regenerated outputs.
    case.source_root.rename(tmp_path / "source-unavailable")
    monkeypatch.setattr(service, "publish_catalog", original)
    result = run(eval_connect, case)
    assert (
        registered_snapshot(case.output / "research", result).manifest == result.research_manifest
    )


@pytest.mark.parametrize("issue", ["symlink", "fifo", "bytes", "cells", "corrupt"])
def test_invalid_source_is_logged_as_failure_never_catalog_success(eval_connect, tmp_path, issue):
    case = fixture(tmp_path)
    if issue == "symlink":
        (case.source.path / "escape").symlink_to(tmp_path)
    elif issue == "fifo":
        os.mkfifo(case.source.path / "not-a-file")
    elif issue == "bytes":
        case.authorization = changed(case.authorization, maximum_source_bytes=1)
    elif issue == "cells":
        case.authorization = changed(case.authorization, maximum_table_cells=1)
    else:
        path = case.source.path / case.source.manifest.tables[0].files[0].path
        path.write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        run(eval_connect, case)
    assert not (case.output / "research/catalog").exists()
    with eval_connect() as conn:
        assert conn.execute(
            "SELECT state FROM eval.ingest_outcomes WHERE ingest_request_id=%s", [case.plan.plan_id]
        ).fetchall() == [("failed",)]


def test_recovery_does_not_regenerate_a_corrupt_frozen_snapshot(eval_connect, tmp_path):
    case = fixture(tmp_path)
    result = run(eval_connect, case)
    (
        case.output
        / "research"
        / result.research_manifest.snapshot_id
        / result.research_manifest.tables[0].files[0].path
    ).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        run(eval_connect, case)


def test_synthetic_replay_is_explicit_bounded_and_keeps_truth_private(eval_connect, tmp_path):
    case = fixture(tmp_path)
    config = SyntheticConfig.model_validate_json(
        (ROOT / "configs/data/synthetic.json").read_bytes()
    )
    config = changed(config, days=80, instruments=20, min_names=10)
    case.plan = changed(
        case.plan,
        source=dict(kind="synthetic", world="null", configuration=config),
        research_cutoff=date(2010, 3, 1),
        as_of=date(2010, 12, 31),
    )
    case.authorization = changed(
        case.authorization, plan_sha256=case.plan.sha256, maximum_table_cells=100000
    )
    result = run(eval_connect, case)
    assert "ground_truth" not in {t.name for t in result.research_manifest.tables}
    full = Snapshot.load(case.output / "full" / result.dataset_version_id)
    assert "ground_truth" in {t.name for t in full.manifest.tables}
    assert result.research_manifest.conventions["new_supplier_requests"] == "0"
    assert result.research_manifest.exposure.history == "previously_seen"


def test_plan_paths_and_schedule_fail_closed_and_disabled_cli_does_not_connect(tmp_path, capsys):
    case = fixture(tmp_path)
    for path in ("/tmp/source", "../source", "full/../source", "./source", "full//source"):
        with pytest.raises(ValidationError):
            changed(case.plan, source=changed(case.plan.source, relative_path=path))
    with pytest.raises(ValidationError):
        changed(case.authorization, schedule="daily", network="internet")
    plan, authorization = tmp_path / "plan.json", tmp_path / "authorization.json"
    plan.write_text(case.plan.model_dump_json())
    authorization.write_text(changed(case.authorization, enabled=False).model_dump_json())
    main(["plan-hash", str(plan)])
    assert capsys.readouterr().out.strip() == case.plan.sha256
    with pytest.raises(SystemExit) as stopped:
        main(
            [
                "once",
                "--plan",
                str(plan),
                "--authorization",
                str(authorization),
                "--source-root",
                str(case.source_root),
                "--fixture-root",
                str(tmp_path),
                "--output",
                str(case.output),
                "--principal",
                "synthetic-owner",
                "--request-id",
                str(uuid4()),
            ]
        )
    assert stopped.value.code == 2 and "inactive" in capsys.readouterr().err
    assert not case.output.exists()


def test_authorized_cli_outputs_only_verified_catalog_ids(
    eval_connect, evaluator_dsn, tmp_path, monkeypatch, capsys
):
    case = fixture(tmp_path)
    plan, authorization = tmp_path / "plan.json", tmp_path / "authorization.json"
    plan.write_text(case.plan.model_dump_json())
    authorization.write_text(case.authorization.model_dump_json())
    monkeypatch.setattr(command, "connection_dsn", lambda: evaluator_dsn)
    arguments = [
        "once",
        "--plan",
        str(plan),
        "--authorization",
        str(authorization),
        "--source-root",
        str(case.source_root),
        "--fixture-root",
        str(tmp_path),
        "--output",
        str(case.output),
        "--principal",
        "synthetic-owner",
        "--request-id",
        str(uuid4()),
    ]
    main(arguments)
    result = capsys.readouterr()
    value = json.loads(result.out)
    assert not result.err and str(tmp_path) not in result.out
    assert set(value) == {"status", "registration_id", "dataset_version_id", "research_snapshot_id"}
    assert value["status"] == "catalog_available"
    registration = read_registration(
        case.output / "research", value["registration_id"], case.plan.program_id
    )
    assert (
        registered_snapshot(case.output / "research", registration).manifest.snapshot_id
        == value["research_snapshot_id"]
    )
    main(arguments)
    assert json.loads(capsys.readouterr().out) == value
    with eval_connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM eval.ingest_outcomes WHERE ingest_request_id=%s",
            [case.plan.plan_id],
        ).fetchone() == (2,)


@pytest.mark.pilot
def test_authorized_original_pilot_ingest_preserves_inputs_and_private_slice(
    eval_connect, tmp_path
):
    root = os.environ.get("QFR_PILOT_ROOT")
    if not root:
        pytest.skip("Original licensed pilot inputs required: QFR_PILOT_ROOT; ingest gate unrun")
    source_root = Path(root)
    package = source_root / "P1_English_Delivery_20261022"
    before = {p: file_hash(p) for p in source_root.rglob("*") if p.is_file()}
    protocol = load_yaml(
        ROOT / "configs/evaluation/pilot_p0_p1_verification_v1.yaml", FrozenProtocol
    )
    manifests = ROOT / "fixtures/pilot/manifests"
    plan = SnapshotBuildPlan(
        schema_version="1",
        plan_id=uuid4(),
        program_id=str(uuid4()),
        source_ref="original-pilot-P1",
        source=dict(
            kind="pilot",
            package=package.name,
            inventory_sha256=file_hash(package / "SHA256SUMS.json"),
            fixture_manifests_sha256=digest(
                {
                    p.relative_to(manifests).as_posix(): file_hash(p)
                    for p in manifests.rglob("*")
                    if p.is_file()
                }
            ),
            adapter=PilotConfig.model_validate_json(
                (ROOT / "configs/data/pilot_import.json").read_bytes()
            ),
        ),
        research_cutoff=protocol.windows["development"].end,
        as_of=protocol.windows["confirmation"].end,
        build_code_version="P3.8-original-input-acceptance",
    )
    authorization = SnapshotBuildAuthorization(
        schema_version="1",
        enabled=True,
        plan_sha256=plan.sha256,
        authorization_ref="local-pilot-test-only",
        authorized_principal="pilot-test",
        authorized_at=datetime.now(UTC) - timedelta(minutes=1),
        maximum_source_files=10000,
        maximum_source_bytes=1073741824,
        maximum_metadata_bytes=1048576,
        maximum_table_cells=100000000,
        network="none",
        schedule="on_demand_only",
    )
    with eval_connect() as conn:
        result = ingest_once(
            conn,
            plan,
            authorization,
            source_root=source_root,
            fixtures_root=ROOT / "fixtures/pilot",
            output_root=tmp_path,
            principal="pilot-test",
            request_id=uuid4(),
        )
    research = registered_snapshot(tmp_path / "research", result)
    full = Snapshot.load(tmp_path / "full" / result.dataset_version_id)
    assert result.research_manifest.research_cutoff == protocol.windows["development"].end
    assert result.research_manifest.exposure.history == "previously_seen"
    assert "evaluation_prices" not in {t.name for t in research.manifest.tables}
    assert "evaluation_prices" in {t.name for t in full.manifest.tables}
    for table in research.manifest.tables:
        frame = research.read(table.name)
        for column in {table.date_column, table.available_date_column} - {None}:
            assert frame[column].max() <= plan.research_cutoff
    assert {p: file_hash(p) for p in source_root.rglob("*") if p.is_file()} == before
