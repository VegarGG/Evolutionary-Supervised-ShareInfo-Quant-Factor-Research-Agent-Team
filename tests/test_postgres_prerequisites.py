"""Exercise real pytest/HTTP fixture setup without opening a database connection."""

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTTP_TESTS = [
    "tests/registry/test_publication.py::test_http_publication_codes_hash_and_closed_mutation_surface",
    "tests/registry/test_seeds.py::test_negative_fixture_publication_is_opaque[network]",
]
BOUNDARY_TEST = "tests/boundary/test_database.py::test_postgres16_databases_and_roles"


def run_pytest(*arguments, environment=None):
    env = dict(os.environ)
    for name in (
        "QFR_TEST_POSTGRES_DSN",
        "QFR_TEST_SECRET_DIR",
        "QFR_PILOT_ROOT",
        "QFR_TEST_SANDBOX_IMAGE",
        "QFR_TEST_PILOT_SANDBOX_IMAGE",
        "PYTEST_ADDOPTS",
    ):
        env.pop(name, None)
    env.update(environment or {})
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short", *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_unconfigured_database_skips_before_http_clients_and_threads_start():
    # Before the prerequisite hook, the TestClient case hangs and the loopback
    # case turns pytest's background-thread skip into an HTTP failure.
    result = run_pytest(*HTTP_TESTS, BOUNDARY_TEST)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "3 skipped" in output and "database checks unrun" in output
    assert "PytestUnhandledThreadExceptionWarning" not in output
    assert "Exception in ASGI application" not in output


@pytest.mark.parametrize("mode", ["argument", "environment"])
def test_required_database_never_becomes_a_successful_skipped_gate(mode):
    args = ["--require-postgres"] if mode == "argument" else []
    env = {"PYTEST_ADDOPTS": "--require-postgres"} if mode == "environment" else {}
    result = run_pytest(*args, BOUNDARY_TEST, environment=env)
    output = result.stdout + result.stderr
    assert result.returncode == pytest.ExitCode.USAGE_ERROR
    assert "PostgreSQL is required for this run" in output
    assert "No database checks ran" in output
    assert "skipped" not in output


def test_configured_but_invalid_database_fails_without_echoing_credentials(tmp_path):
    # Invalid conninfo fails before any socket can open. These are synthetic
    # sentinels, never inherited credentials or the owner's database endpoint.
    secret = "synthetic-prerequisite-password"
    invalid_dsn = "synthetic-private-dsn-no-equals"
    (tmp_path / "postgres_password").write_text(secret)
    result = run_pytest(
        "--require-postgres",
        BOUNDARY_TEST,
        environment={
            "QFR_TEST_POSTGRES_DSN": invalid_dsn,
            "QFR_TEST_SECRET_DIR": str(tmp_path),
        },
    )
    output = result.stdout + result.stderr
    assert result.returncode == pytest.ExitCode.TESTS_FAILED
    assert "Database migration failed" in output
    assert "1 error" in output and "skipped" not in output
    assert secret not in output and invalid_dsn not in output


@pytest.mark.parametrize("listening", [False, True], ids=["refused", "unresponsive"])
def test_required_database_connection_failure_is_bounded_and_never_skipped(tmp_path, listening):
    # A reserved loopback port either refuses TCP or accepts the TCP handshake
    # without answering PostgreSQL. This is a connection-failure fixture, not a
    # substitute database or evidence of any successful database gate.
    secret = "synthetic-connection-timeout-password"
    (tmp_path / "postgres_password").write_text(secret)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        if listening:
            listener.listen(1)
        dsn = f"postgresql://127.0.0.1:{listener.getsockname()[1]}/postgres"
        result = run_pytest(
            "--require-postgres",
            BOUNDARY_TEST,
            environment={"QFR_TEST_POSTGRES_DSN": dsn, "QFR_TEST_SECRET_DIR": str(tmp_path)},
        )
    output = result.stdout + result.stderr
    assert result.returncode == pytest.ExitCode.TESTS_FAILED
    assert "Database migration failed (OperationalError)" in output
    assert "1 error" in output and "skipped" not in output
    assert secret not in output and dsn not in output
