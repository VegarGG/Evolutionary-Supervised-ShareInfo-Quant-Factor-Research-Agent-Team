"""Freeze the owner-requested maximum-effort retry without erasing unknown usage."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from qfh.case_research import CasePolicy
from qfh.coding_plan import CodingLedger, CodingPolicy
from qfh.research import Research
from qfh.shared_state import atomic_new, digest


def prepare(private):
    root = Path(__file__).resolve().parents[1]
    original = CasePolicy.model_validate_json(
        (private / "case-packages/unseen-glm53-adaptive-02.json").read_bytes()
    )
    route = CodingPolicy.model_validate(
        yaml.safe_load((root / "configs/glm53-max-unseen-2026-11-16.yaml").read_text())
    )
    research = Research(root / "configs/research-trial.yaml", private)
    budget = research.ledger.snapshot()
    assert not any(c["state"] == "pending" for c in budget["calls"])
    unknown = [c for c in budget["calls"] if c["state"] == "unknown"]
    assert len(unknown) == 1
    ledger = CodingLedger(research.ledger, route)
    for call in unknown:
        ledger.verify_reserved_timeout(call)
    folder = private / "case-studies/unseen-glm53-max-20261116"
    folder.mkdir(parents=True, exist_ok=False)
    packages = []
    for number, variant in enumerate(("adaptive", "fixed"), 1):
        ident = f"unseen-glm53-max-{variant}-{number:02}"
        value = original.model_dump()
        value.update(
            package_id=ident,
            study_id=folder.name,
            variant=variant,
            route_id=route.id,
            authority=route.authority,
        )
        value["episode"]["episode_id"] = ident
        package = CasePolicy.model_validate(value)
        for field in (
            "question",
            "max_tasks",
            "total_requests",
            "max_output_tokens",
            "max_inspections",
        ):
            assert getattr(package, field) == getattr(original, field)
        assert package.episode.rows == original.episode.rows
        assert package.episode.sources == original.episode.sources
        assert package.episode.initial_spec == original.episode.initial_spec
        assert ident in route.reserved_connection_timeouts[0].groups
        atomic_new(private / "case-packages" / f"{ident}.json", package.model_dump())
        packages.append({"package_id": ident, "sha256": digest(package.model_dump())})
    atomic_new(
        folder / "FROZEN_PLAN.json",
        {
            "at": datetime.now(UTC).isoformat(),
            "authority": route.authority,
            "route": route.model_dump(mode="json"),
            "origin_package": original.package_id,
            "packages": packages,
            "data_snapshot_sha256": original.episode.data_snapshot_sha256,
            "sources_sha256": digest(original.episode.sources),
            "initial_spec": original.episode.initial_spec.model_dump(),
            "question": original.question,
            "changed_model_setting": {"from": "low", "to": "max"},
            "unchanged_output_cap": original.max_output_tokens,
            "data_requests": 0,
            "budget_before": {k: v for k, v in budget.items() if k != "calls"},
            "retained_unknown_calls": unknown,
            "protocol": "Adaptive first, then fixed if new usage settles and integrity audit "
            "passes. Stop on new unknown usage or exhausted allowance. No automatic model "
            "fallback, token-cap expansion, failed-turn replay or forced factor change.",
            "prompt_patch_sha256": {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in ("configs/web-case.patch.yml", "dsh-plugin/case.js")
            },
            "transport_amendment": "The original ConnectTimeout stays unknown and fully "
            "reserved. Owner retry permits only the two named fresh groups against exact "
            "ledger/request fingerprints and pre-HTTP evidence; it is not billing reconciliation.",
        },
    )
    research.activate_model_route(route, expected_previous_id="glm53-coding-unseen-2026-11-16")
    assert research.ledger.snapshot() == budget
    return {"status": "frozen", "packages": packages, "effort": "max", "provider_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.private.resolve()), indent=2))
