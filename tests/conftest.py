"""Real-database migration setup shared by all stage boundary suites."""

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
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
from qfr_research.db import migrate as migrate_research

ROOT = Path(__file__).resolve().parents[1]
POSTGRES_TEST_POLICY = json.loads((ROOT / "configs/testing/postgres_v1.json").read_text())


@pytest.fixture
def backend_runner(monkeypatch):
    """Opt-in native acceptance uses a separate credential-free controller.

    The test process never passes its PostgreSQL/provider environment to it.
    This is an actual-engine fixture, not an offline replacement for isolation.
    """
    from qfr_eval.sandbox.client import DockerControllerClient
    from qfr_eval.sandbox.models import DockerControllerConfiguration, DockerNativeProfile
    from qfr_eval.sandbox.runner import SandboxRunner

    @contextlib.contextmanager
    def create(profile, image):
        backend = os.environ.get("QFR_TEST_SANDBOX_BACKEND", "runsc")
        if backend == "runsc":
            yield SandboxRunner(profile, image)
            return
        if backend != "docker-native":
            pytest.fail("unknown explicitly selected sandbox backend")
        docker_socket = os.environ.get("QFR_TEST_DOCKER_SOCKET")
        if not docker_socket:
            pytest.fail("native acceptance requires explicit existing QFR_TEST_DOCKER_SOCKET")
        if not isinstance(profile, DockerNativeProfile):
            native = json.loads(
                (ROOT / "configs/evaluation/sandbox_docker_native_v3.json").read_bytes()
            )
            # Preserve each existing bounded negative fixture's distinct CPU/
            # memory/deadline budgets. The backend's security fields stay frozen.
            native.update(
                {
                    key: value
                    for key, value in profile.model_dump().items()
                    if key not in {"schema_version", "runtime", "process_limit", "pids_limit"}
                }
            )
            native["profile_id"] += "-docker-native-v2"
            profile = DockerNativeProfile.model_validate(native)
        with tempfile.TemporaryDirectory(prefix="qfr-ctl-", dir="/tmp") as directory:
            root = Path(directory)
            socket_path = str(root / "controller.sock")
            config = DockerControllerConfiguration(
                schema_version="1",
                profile=profile,
                image_digest=image,
                docker_socket=docker_socket,
                control_socket=socket_path,
                max_parallel_jobs=1,
            )
            path = root / "configuration.json"
            path.write_text(config.model_dump_json())
            with (root / "controller.stderr").open("wb") as errors:
                child = subprocess.Popen(
                    [sys.executable, "-m", "qfr_eval.sandbox.controller", str(path)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=errors,
                    env={
                        "PATH": os.defpath,
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "POLARS_MAX_THREADS": "1",
                        "OPENBLAS_NUM_THREADS": "1",
                        "OMP_NUM_THREADS": "1",
                    },
                )
                try:
                    deadline = time.monotonic() + 30
                    while not Path(socket_path).exists() and child.poll() is None:
                        if time.monotonic() >= deadline:
                            pytest.fail("native controller startup exceeded 30 seconds")
                        time.sleep(0.05)
                    assert child.poll() is None, (
                        "native controller startup failed; check prerequisites"
                    )
                    with monkeypatch.context() as environment:
                        # Reproduction subprocesses inherit only the private evaluator
                        # channel; they are not granted the engine socket.
                        environment.setenv("QFR_SANDBOX_CONTROLLER_SOCKET", socket_path)
                        yield DockerControllerClient(profile, image, socket_path)
                finally:
                    if child.poll() is None:
                        child.terminate()
                    try:
                        child.wait(
                            timeout=2 * profile.timeout_seconds
                            + 60 * profile.control_timeout_seconds
                        )
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                        pytest.fail(
                            "controller shutdown uncertain; native resources require inspection"
                        )
                    assert not Path(socket_path).exists(), (
                        "controller did not confirm graceful shutdown"
                    )

    return create


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
            migrate_research(database_dsn(database="research_db"))
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


@pytest.fixture
def migration_dsn():
    return lambda database: database_dsn(database=database)


@pytest.fixture
def research_connect():
    def factory(role="research_rw"):
        try:
            return psycopg.connect(database_dsn(role, "research_db"), autocommit=True)
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
