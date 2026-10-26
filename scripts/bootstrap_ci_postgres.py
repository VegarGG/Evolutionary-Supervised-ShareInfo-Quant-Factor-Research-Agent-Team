"""Bootstrap a fresh, isolated CI service; production uses the Compose entrypoint."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    container = sys.argv[1]
    roles = {
        "REGISTRY_PASSWORD": "registry_app",
        "RESEARCH_PASSWORD": "research_rw",
        "EVAL_PASSWORD": "eval_rw",
        "FEEDBACK_PASSWORD": "feedback_ro",
    }
    env = dict(os.environ)
    for variable, role in roles.items():
        env[variable] = (ROOT / f".secrets/{role}_password").read_text().strip()
    command = ["docker", "exec", "-i"]
    for variable in roles:
        command += ["--env", variable]
    command += [container, "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-q", "-f", "-"]
    password = (ROOT / ".secrets/postgres_password").read_text().strip()
    # token_hex generation guarantees quoting is safe; never emit this SQL or driver frames.
    assert password.isalnum()
    source = (
        f"ALTER ROLE postgres PASSWORD '{password}';\n"
        + (ROOT / "infra/postgres/init.sql").read_text()
    )
    result = subprocess.run(command, input=source, text=True, env=env, capture_output=True)
    if result.returncode:
        raise SystemExit("CI bootstrap SQL failed; inspect the isolated container locally")
    subprocess.run(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-c",
            "sed -i '/^host/s/trust/scram-sha-256/g' /var/lib/postgresql/data/pg_hba.conf",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-U",
            "postgres",
            "-q",
            "-c",
            "SELECT pg_reload_conf();",
        ],
        check=True,
        capture_output=True,
    )
    print("Fresh CI databases bootstrapped; host authentication now requires SCRAM passwords.")


if __name__ == "__main__":
    main()
