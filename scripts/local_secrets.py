"""Create task-local development secret files, never print their contents."""

import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = json.loads((ROOT / "configs/infra.json").read_text())
    target = ROOT / ".secrets"
    target.mkdir(mode=0o700, exist_ok=True)
    for name in config["database_principals"]:
        path = target / f"{name}_password"
        if not path.exists():
            with path.open("x") as stream:
                stream.write(secrets.token_hex(config["secret_bytes"]))
            path.chmod(0o600)
    print("Local database secret files ready; no credentials printed.")


if __name__ == "__main__":
    main()
