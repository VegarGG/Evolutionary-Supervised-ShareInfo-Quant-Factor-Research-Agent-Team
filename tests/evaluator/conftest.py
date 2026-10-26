import os
from pathlib import Path

import pytest
from qfr_core.configuration import load_yaml
from qfr_core.data_layer.pilot import PilotConfig, import_pilot
from qfr_eval.backtest.pilot import evaluate_pilot
from qfr_eval.backtest.scorers import ScorerSpec, built_in_history
from qfr_eval.protocols.models import FrozenProtocol


@pytest.fixture(scope="session")
def pilot_sources():
    root = os.environ.get("QFR_PILOT_ROOT")
    if not root:
        pytest.skip("PIL-02 requires original licensed packages: QFR_PILOT_ROOT")
    root = Path(root)
    imported = import_pilot(
        root / "P1_English_Delivery_20261022",
        Path("fixtures/pilot"),
        PilotConfig.model_validate_json(Path("configs/data/pilot_import.json").read_bytes()),
    )
    protocol = load_yaml(
        Path("configs/evaluation/pilot_package_ledger_oracle.yaml"), FrozenProtocol
    )
    return root, {t.name: t.frame for t in imported.tables}, protocol


@pytest.fixture(scope="session")
def pilot_runs(pilot_sources):
    root, tables, protocol = pilot_sources
    result = {}
    for variant in ("baseline", "P1_reversal_momentum"):
        spec = None if variant == "baseline" else ScorerSpec(variant, 0.5, 5, 20, 120)
        panel, history = built_in_history(
            tables["features"],
            tables["prices_daily"],
            tables["universe"]["code"].to_list(),
            protocol,
            spec=spec,
        )
        result[variant] = evaluate_pilot(
            panel,
            history,
            tables["prices_daily"],
            tables["calendar"],
            tables["universe"],
            protocol,
            variant=variant,
        )
    return result


@pytest.fixture(scope="session")
def pilot_full_snapshot(pilot_sources, tmp_path_factory):
    from qfr_core.data_layer.snapshots import Snapshot, write_snapshot

    root, _, _ = pilot_sources
    imported = import_pilot(
        root / "P1_English_Delivery_20261022",
        Path("fixtures/pilot"),
        PilotConfig.model_validate_json(Path("configs/data/pilot_import.json").read_bytes()),
    )
    as_of = max(
        table.frame[column].max()
        for table in imported.tables
        for column in [table.date_column, table.available_date_column]
        if column
    )
    snapshot = write_snapshot(
        tmp_path_factory.mktemp("evaluator-full-snapshot"),
        imported.tables,
        profile="pilot_industry_v1",
        zone="full",
        cutoff=None,
        as_of=as_of,
        source="authorized P1 pilot transaction fixture",
        build_code_version="test-fixture",
        exposure=imported.exposure,
        conventions={"exposure": "previously_seen"},
        principal="evaluator-test",
        request_id="evaluator-snapshot-fixture",
    )
    return Snapshot.load(snapshot.path)
