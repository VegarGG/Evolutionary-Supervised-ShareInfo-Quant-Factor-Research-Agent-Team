"""Owner-directed GLM 5.3 rerun; preserve the exact original task and BaoStock bundle."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from qfh.case_research import CasePolicy
from qfh.coding_plan import CodingPolicy
from qfh.research import Research
from qfh.shared_state import atomic_new, digest


def prepare(private):
    root = Path(__file__).resolve().parents[1]
    old = CasePolicy.model_validate_json(
        (private / "case-packages/unseen-fixed-01.json").read_bytes()
    )
    bundle = json.loads((private / "case-studies" / old.study_id / "BUNDLE.json").read_bytes())
    assert digest(old.episode.rows) == bundle["rows_sha256"]
    assert old.episode.sources == bundle["sources"]
    route = CodingPolicy.model_validate(
        yaml.safe_load((root / "configs/glm53-coding-unseen-2026-11-16.yaml").read_text())
    )
    research = Research(root / "configs/research-trial.yaml", private)
    before = research.ledger.snapshot()
    if any(c["state"] not in ("settled", "rejected_reserved") for c in before["calls"]):
        raise ValueError("unsettled usage blocks model switch")
    study_id = "unseen-baostock-glm53-20261116"
    folder = private / "case-studies" / study_id
    folder.mkdir(parents=True, exist_ok=True)
    order = ["fixed", "adaptive", "adaptive", "fixed"]
    packages = []
    for n, variant in enumerate(order, 1):
        ident = f"unseen-glm53-{variant}-{n:02}"
        value = old.model_dump()
        value.update(
            package_id=ident,
            study_id=study_id,
            variant=variant,
            route_id=route.id,
            model=route.model,
            authority=route.authority,
        )
        value["episode"]["episode_id"] = ident
        package = CasePolicy.model_validate(value)
        assert package.question == old.question and package.episode.initial == old.episode.initial
        assert package.episode.sources == old.episode.sources
        path = private / "case-packages" / f"{ident}.json"
        atomic_new(path, package.model_dump())
        packages.append({"package_id": ident, "sha256": digest(package.model_dump())})
    atomic_new(
        folder / "FROZEN_RERUN.json",
        {
            "at": datetime.now(UTC).isoformat(),
            "authority": route.authority,
            "origin_study": old.study_id,
            "source_bundle_sha256": digest(bundle),
            "data_snapshot_sha256": bundle["rows_sha256"],
            "source_bundle_changed": False,
            "question": old.question,
            "initial_spec": old.episode.initial_spec.model_dump(),
            "route": route.model_dump(mode="json"),
            "packages": packages,
            "budget_before": {k: v for k, v in before.items() if k != "calls"},
            "covered_call_ids_sha256": digest(sorted(c["id"] for c in before["calls"])),
            "not_run_by_owner_switch": [
                "unseen-adaptive-02",
                "unseen-adaptive-03",
                "unseen-fixed-04",
            ],
            "comparison_limit": "Model and contract guidance both changed; no causal model-only "
            "comparison with the retained Flash attempt. Within the new pair inputs/code match.",
            "repeat_rule": "Audit and settle the first pair before the reverse-order pair. "
            "Retain failures; stop on uncertain charges or unresolved arithmetic/integrity error.",
        },
    )
    research.activate_model_route(route, expected_previous_id="glm-coding-unseen-2026-11-16")
    return {
        "status": "rerun_frozen",
        "model": route.model,
        "packages": packages,
        "new_data_requests": 0,
        "model_requests": 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.private.resolve()), indent=2))
