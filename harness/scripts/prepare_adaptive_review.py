"""Freeze a prior completed output for one native DSH diagnostic; no provider calls."""

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from qfh.adaptive_research import AdaptivePolicy
from qfh.final_output import CompletedOutput, OutputEpisode
from qfh.research import Research
from qfh.shared_state import atomic_new


def prepare(private, package_id, origin, *, accepted_board=False):
    root = Path(__file__).resolve().parents[1]
    source = json.loads(origin.read_bytes())
    if accepted_board:
        artifact = source["head"]
        body = artifact["output"]
    else:
        artifact = source["board"]["head"]
        body = artifact["body"]
    output = CompletedOutput.model_validate(
        {k: v for k, v in body.items() if k in CompletedOutput.model_fields}
    )
    case = json.loads((root / "cases/module-units.json").read_bytes())
    research = Research(root / "configs/research-trial.yaml", private)
    with research.db() as db:
        route = research.active_model_route(db)
    settings = yaml.safe_load((root / "configs/adaptive-review.yaml").read_text())
    episode = OutputEpisode(
        episode_id=package_id,
        actors={
            "supervisor": "supervisor",
            **{
                f"{role}-{i}": role
                for i in range(1, settings["max_tasks"] + 1)
                for role in ("author", "reviewer")
            },
        },
        sources=case["sources"],
        initial_output=output,
        units=settings["units"],
        import_origin={
            "path": str(origin.resolve()),
            "file_sha256": hashlib.sha256(origin.read_bytes()).hexdigest(),
            "artifact_id": artifact["id"],
            "original_artifact": artifact,
        },
        policy=settings["board"],
    )
    package = AdaptivePolicy(
        package_id=package_id,
        episode=episode,
        route_id=route["id"],
        **{
            k: settings[k]
            for k in (
                "max_tasks",
                "supervisor_requests",
                "worker_requests",
                "total_requests",
                "max_output_tokens",
            )
        },
        authority="Owner authorized completed-output review and adaptive supervisor follow-ups, "
        "GLM 5.3 Flash only, original cumulative 200 CNY. This diagnostic package "
        "allows one native supervisor, at most five tasks and 32 aggregate requests. "
        "All previous debits, reservations and provider quotas remain binding.",
    )
    directory = private / "adaptive-packages"
    directory.mkdir(exist_ok=True)
    path = directory / f"{package_id}.json"
    atomic_new(path, package.model_dump())
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", required=True, type=Path)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--origin", required=True, type=Path)
    parser.add_argument(
        "--board-snapshot",
        "--accepted-board",
        dest="board_snapshot",
        action="store_true",
        help="Import a board snapshot; this does not imply semantic acceptance.",
    )
    args = parser.parse_args()
    print(
        prepare(
            args.private.resolve(),
            args.package_id,
            args.origin.resolve(),
            accepted_board=args.board_snapshot,
        )
    )
