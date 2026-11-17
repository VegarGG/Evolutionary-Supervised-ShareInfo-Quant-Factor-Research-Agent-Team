"""Keep native DSH file attribution inside a dedicated, empty Git boundary."""

import subprocess


def isolated_workspace(private):
    # Keep the existing native workspace path/session registry. Add a local Git
    # boundary there, rather than silently redirecting or rewriting old sessions.
    base = private / "research-workspace"
    workspace = base / "deepseek-harness/default-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    if not (workspace / ".git").exists():
        subprocess.run(["git", "init", "-q", str(workspace)], check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=QRH workspace",
                "-c",
                "user.email=qrh@localhost",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "-qm",
                "Initialize isolated research workspace",
            ],
            cwd=workspace,
            check=True,
        )
    actual = (
        subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=workspace)
        .decode()
        .strip()
    )
    if actual != str(workspace.resolve()):
        raise ValueError("research workspace must have its own Git boundary")
    return base
