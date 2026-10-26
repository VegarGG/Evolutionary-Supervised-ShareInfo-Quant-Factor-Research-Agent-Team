"""Real-container startup regressions; no daemon socket enters application/test images.

Run separately from pytest with `uv run python scripts/verify_postgres_startup.py`.
Positive initialization and authenticated grants are covered by the Compose exit gate.
Only disposable containers and generated fixture credentials are used here.
"""

import os
import secrets
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("postgres", "registry_app", "research_rw", "eval_rw", "feedback_ro")
FAIL_BEFORE_INIT = """
set +e
bash /opt/qfr/postgres/entrypoint.sh postgres
result=$?
set -e
test "$result" -ne 0
test ! -e "$PGDATA/PG_VERSION"
test -z "$(ls -A /run/qfr-postgres-secrets)"
"""


def main():
    image = yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text())["services"]["postgres"][
        "image"
    ]
    cases = [
        ("missing-role", "Cannot read PostgreSQL secret: feedback_ro_password"),
        ("empty-role", "Empty PostgreSQL secret: feedback_ro_password"),
        ("missing-admin", "Cannot read PostgreSQL secret: postgres_password"),
        ("empty-admin", "Empty PostgreSQL secret: postgres_password"),
        ("masked-read-error", "Cannot read PostgreSQL secret: feedback_ro_password"),
        ("missing-tmpfs", "requires its private tmpfs mount"),
        ("host-uid-mismatch", "Cannot read PostgreSQL secret: registry_app_password"),
        ("incomplete-restart", "operator recovery required"),
    ]
    for case, expected in cases:
        with tempfile.TemporaryDirectory(prefix="qfr-startup-") as directory:
            fixture = Path(directory)
            values = {role: secrets.token_hex(32) for role in ROLES}
            name = f"qfr-startup-{uuid4().hex}"
            command = [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--network",
                "none",
                "--entrypoint",
                "bash",
                "--mount",
                f"type=bind,src={ROOT / 'infra/postgres'},dst=/opt/qfr/postgres,readonly",
                "--tmpfs",
                "/var/lib/postgresql/data:rw,nosuid,nodev,mode=0700",
                "--env",
                "POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password",
            ]
            if case != "missing-tmpfs":
                command += ["--tmpfs", "/run/qfr-postgres-secrets:rw,noexec,nosuid,nodev,mode=0700"]
            for role in ROLES:
                if (case, role) in {("missing-role", "feedback_ro"), ("missing-admin", "postgres")}:
                    continue
                path = fixture / f"{role}_password"
                path.write_text(
                    ""
                    if (case, role) in {("empty-role", "feedback_ro"), ("empty-admin", "postgres")}
                    else values[role]
                )
                path.chmod(0o600)
                command += [
                    "--mount",
                    f"type=bind,src={path},dst=/run/secrets/{path.name},readonly",
                ]
            script = FAIL_BEFORE_INIT
            if case == "masked-read-error":
                reader = fixture / "cat"
                reader.write_text(
                    '#!/usr/bin/env bash\nif [[ "${*: -1}" == */feedback_ro_password ]]; then\n'
                    'printf partial-fixture-read\nexit 1\nfi\nexec /bin/cat "$@"\n'
                )
                reader.chmod(0o700)
                command += ["--mount", f"type=bind,src={reader},dst=/test-bin/cat,readonly"]
                script = 'export PATH="/test-bin:$PATH"\n' + script
            elif case == "missing-tmpfs":
                script = "mkdir -m 0700 /run/qfr-postgres-secrets\n" + script
            elif case == "incomplete-restart":
                script = 'touch "$PGDATA/.qfr-bootstrap-pending"\n' + script
            elif case == "host-uid-mismatch":
                # Match Compose file-secret mounts: host 0600, foreign owner, no chown/chmod.
                script = (
                    f'test "$(id -u postgres)" != "{os.getuid()}"\n'
                    + """
test "$(stat -c %a /run/secrets/registry_app_password)" = 600
install -d -m 0755 /test/init /test/bin
install -m 0644 /opt/qfr/postgres/init/* /test/init/
printf '#!/bin/sh\\necho DDL_REACHED\\n' > /test/bin/psql
chmod 0755 /test/bin/psql
chown postgres:postgres "$PGDATA"
set +e
gosu postgres env PATH="/test/bin:$PATH" POSTGRES_USER=postgres \\
    bash /test/init/00-bootstrap.sh /run/secrets /unused.sql
result=$?
set -e
test "$result" -ne 0
test -f "$PGDATA/.qfr-bootstrap-pending"
"""
                )
            try:
                result = subprocess.run(
                    command + [image, "-euo", "pipefail", "-c", script],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                output = result.stdout + result.stderr
                if any(value in output for value in values.values()):
                    raise RuntimeError(f"{case}: credential appeared in captured output")
                if result.returncode or expected not in output or "DDL_REACHED" in output:
                    raise RuntimeError(
                        f"{case}: startup regression failed (exit {result.returncode})"
                    )
                assert all(
                    path.stat().st_mode & 0o777 == 0o600 for path in fixture.glob("*_password")
                )
                print(
                    f"PASS {case}: fail closed; no SQL/credential output; host secrets remain 0600"
                )
            finally:
                # Also clean up a container if a regression caused startup to hang.
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
    print(f"{len(cases)} real-container startup regressions passed.")


if __name__ == "__main__":
    main()
