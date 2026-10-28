"""Bootstrap must stop before DDL when any credential read fails."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "infra/postgres/init/00-bootstrap.sh"
ROLES = ("registry_app", "research_rw", "eval_rw", "feedback_ro")


@pytest.fixture
def startup(tmp_path):
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    for role in ROLES:
        (credentials / f"{role}_password").write_text(f"fixture-{role}")
    data = tmp_path / "data"
    data.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    psql = binaries / "psql"
    psql.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "keys = ['REGISTRY_PASSWORD', 'RESEARCH_PASSWORD', 'EVAL_PASSWORD', 'FEEDBACK_PASSWORD']\n"
        "valid = all(os.environ[k].startswith('fixture-') for k in keys)\n"
        "pathlib.Path(os.environ['RECEIPT']).write_text(json.dumps({'valid': valid}))\n"
        "sys.exit(int(os.environ.get('PSQL_EXIT', '0')))\n"
    )
    psql.chmod(0o755)
    cleanup = binaries / "rm"
    cleanup.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "keys = ['REGISTRY_PASSWORD', 'RESEARCH_PASSWORD', 'EVAL_PASSWORD', 'FEEDBACK_PASSWORD']\n"
        "assert not any(k in os.environ for k in keys), 'Only the SQL child receives credentials'\n"
        "os.execv('/bin/rm', ['/bin/rm', *sys.argv[1:]])\n"
    )
    cleanup.chmod(0o755)
    receipt = tmp_path / "receipt.json"
    env = dict(
        os.environ,
        PATH=f"{binaries}:{os.environ['PATH']}",
        PGDATA=str(data),
        POSTGRES_USER="postgres",
        RECEIPT=str(receipt),
    )

    def run():
        result = subprocess.run(
            ["bash", str(BOOTSTRAP), str(credentials), str(tmp_path / "unused.sql")],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "fixture-" not in result.stdout + result.stderr
        return result

    return run, credentials, data, binaries, receipt, env


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("failure", ["missing", "empty", "read_error"])
def test_bad_secret_prevents_all_ddl(startup, role, failure):
    run, credentials, data, binaries, receipt, _ = startup
    path = credentials / f"{role}_password"
    if failure == "missing":
        path.unlink()
    elif failure == "empty":
        path.write_text("\n")
    else:
        # Regression: even nonempty stdout with a failing read must not be exported.
        reader = binaries / "cat"
        reader.write_text(
            f'#!/usr/bin/env bash\nif [[ "${{*: -1}}" == *{role}_password ]]; then\n'
            '  printf fixture-partial-read\n  exit 1\nfi\nexec /bin/cat "$@"\n'
        )
        reader.chmod(0o755)
    result = run()
    assert result.returncode != 0
    assert role in result.stderr
    assert not receipt.exists(), "No SQL may run with partial or empty credentials"
    assert (data / ".qfr-bootstrap-pending").exists()
    assert not list(credentials.iterdir()), "Private staged copies must be removed on failure"


@pytest.mark.skipif(
    os.geteuid() == 0, reason="Real DAC read denial requires an unprivileged test UID"
)
def test_actual_unreadable_secret_prevents_ddl_without_a_mock_reader(startup):
    run, credentials, data, _, receipt, _ = startup
    path = credentials / "registry_app_password"
    path.chmod(0)
    with pytest.raises(PermissionError):
        path.read_bytes()
    result = run()
    assert result.returncode != 0
    assert "Cannot read PostgreSQL secret: registry_app_password" in result.stderr
    assert not receipt.exists(), "A real denied read must stop before SQL"
    assert (data / ".qfr-bootstrap-pending").exists()
    assert not list(credentials.iterdir())


def test_success_exports_all_credentials_only_to_sql_child_and_cleans_up(startup):
    run, credentials, data, _, receipt, _ = startup
    assert run().returncode == 0
    assert json.loads(receipt.read_text()) == {"valid": True}
    assert not (data / ".qfr-bootstrap-pending").exists()
    assert not list(credentials.iterdir())


def test_sql_failure_retains_recovery_marker_and_cleans_up(startup):
    run, credentials, data, _, receipt, env = startup
    env["PSQL_EXIT"] = "7"
    assert run().returncode == 7
    assert receipt.exists()
    assert (data / ".qfr-bootstrap-pending").exists()
    assert not list(credentials.iterdir())
