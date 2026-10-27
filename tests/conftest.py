"""Real-database migration setup shared by all stage boundary suites."""

import json
import os
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from qfr_core.configuration import load_yaml
from qfr_core.data_layer.pilot import PilotConfig, import_pilot
from qfr_eval.backtest.pilot import evaluate_pilot
from qfr_eval.backtest.scorers import ScorerSpec, built_in_history
from qfr_eval.db import migrate
from qfr_eval.protocols.models import FrozenProtocol
from qfr_registry.storage.migrations import migrate as migrate_registry

ROOT = Path(__file__).resolve().parents[1]
POSTGRES_TEST_POLICY = json.loads((ROOT / "configs/testing/postgres_v1.json").read_text())


def pytest_addoption(parser):
    parser.addoption(
        "--require-postgres",
        action="store_true",
        help="Fail before running tests if QFR_TEST_POSTGRES_DSN is not configured.",
    )


def pytest_configure(config):
    if config.getoption("--require-postgres") and not os.environ.get("QFR_TEST_POSTGRES_DSN"):
        raise pytest.UsageError(
            "PostgreSQL is required for this run: configure QFR_TEST_POSTGRES_DSN and "
            "QFR_TEST_SECRET_DIR for the initialized test database. No database checks ran."
        )


def pytest_runtest_setup(item):
    # A skip raised inside ASGI/thread-pool work cannot safely propagate through
    # an HTTP response. Resolve declared prerequisites on pytest's own thread,
    # before a TestClient or loopback server starts.
    if item.get_closest_marker("database") and not os.environ.get("QFR_TEST_POSTGRES_DSN"):
        pytest.skip("Live PostgreSQL required: QFR_TEST_POSTGRES_DSN (database checks unrun)")


def database_dsn(role="postgres", database="eval_db"):
    base = os.environ.get("QFR_TEST_POSTGRES_DSN")
    if not base:
        pytest.skip("Live PostgreSQL required: QFR_TEST_POSTGRES_DSN")
    directory = Path(os.environ.get("QFR_TEST_SECRET_DIR", ROOT / ".secrets"))
    return make_conninfo(
        base,
        user=role,
        dbname=database,
        password=(directory / f"{role}_password").read_text().strip(),
        connect_timeout=POSTGRES_TEST_POLICY["connect_timeout_seconds"],
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_evaluator():
    if os.environ.get("QFR_TEST_POSTGRES_DSN"):
        try:
            migrate(database_dsn())
            migrate_registry(database_dsn(database="registry_db"))
        except Exception as error:
            # Never render a driver/SQLAlchemy frame with the credential-bearing DSN.
            raise pytest.fail.Exception(
                f"Database migration failed ({type(error).__name__})", pytrace=False
            ) from None


@pytest.fixture
def eval_connect():
    def factory(role="eval_rw"):
        try:
            return psycopg.connect(database_dsn(role), autocommit=True)
        except psycopg.OperationalError as error:
            raise psycopg.OperationalError(str(error)) from None

    return factory


@pytest.fixture
def registry_connect():
    def factory(role="registry_app"):
        try:
            return psycopg.connect(database_dsn(role, "registry_db"), autocommit=True)
        except psycopg.OperationalError as error:
            raise psycopg.OperationalError(str(error)) from None

    return factory


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
