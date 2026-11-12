"""Start the local DSH credential setup UI; model providers stay disabled."""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, default=Path(".qfh-private"))
    parser.add_argument("--port", type=int, default=3080)
    parser.add_argument("--install-plugin", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    private = args.private.resolve()
    private.mkdir(parents=True, exist_ok=True)
    private.chmod(0o700)
    env = {
        **os.environ,
        "DSH_HOME": str(private / "ui-home"),
        "QFH_PYTHON": sys.executable,
        "QFH_SOURCE_ROOT": str(root / "src"),
        "QFH_DATA_POLICY": str(root / "configs/data-pilot.yaml"),
        "QFH_DATA_PRIVATE": str(private / "data"),
        "DSH_TELEMETRY_MODE": "DISABLED",
    }
    dsh = str(Path(sys.executable).with_name("dsh"))
    if args.install_plugin:
        subprocess.run(
            [dsh, "plugin", "--profile", "web", "add", f"file:{root / 'dsh-plugin'}"],
            env=env,
            check=True,
        )
        # A development link exposes new files too; pnpm may retain an old file: snapshot.
        subprocess.run(
            [dsh, "plugin", "--profile", "web", "link", str(root / "dsh-plugin")],
            env=env,
            check=True,
        )
    os.execve(
        dsh,
        [
            dsh,
            "web",
            "--patch",
            str(root / "configs/web-credentials.patch.yml"),
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
            "--no-open",
        ],
        env,
    )


if __name__ == "__main__":
    main()
