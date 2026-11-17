"""Freeze one replacement pair after the recorded false-positive guard failure."""

import argparse
import json
from pathlib import Path

import yaml

from qfh.case_research import CasePolicy
from qfh.coding_plan import CodingLedger, CodingPolicy, coding_detail
from qfh.research import Research
from qfh.shared_state import atomic_new, digest


def prepare(private):
    root = Path(__file__).resolve().parents[1]
    original = CasePolicy.model_validate_json(
        (private / "case-packages/typed-evidence-fixed-01.json").read_bytes()
    )
    failure = json.loads((private / "cases/typed-evidence-fixed-01/RESULT.json").read_bytes())
    assert failure["status"] == "incomplete" and failure["model"]["all_usage_settled"]
    assert failure["model"]["requests"] == 13
    assert not (private / "cases/typed-evidence-adaptive-02").exists()
    research = Research(root / "configs/research-trial.yaml", private)
    before = research.ledger.snapshot()
    assert not any(c["state"] == "pending" for c in before["calls"])
    assert sum(bool(coding_detail(c)) for c in before["calls"]) == 384
    assert before["cumulative_micro_cny"] == 90626516
    assert before["unresolved_micro_cny"] == 14090240
    route = CodingPolicy.model_validate(
        yaml.safe_load((root / "configs/glm53-typed-repair-2026-11-17.yaml").read_text())
    )
    assert route.max_requests == 443 and route.max_microcredits == 10000000000
    assert route.cash_package_micro_cny == 100000000
    for call in before["calls"]:
        if call["state"] == "unknown":
            CodingLedger(research.ledger, route).verify_reserved_timeout(call)
    folder = private / "case-studies/typed-repair-20261117"
    folder.mkdir(parents=True, exist_ok=False)
    packages = []
    for number, variant in enumerate(("fixed", "adaptive"), 3):
        ident = f"typed-repair-{variant}-{number:02}"
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
        atomic_new(private / "case-packages" / f"{ident}.json", package.model_dump())
        packages.append({"package_id": ident, "sha256": digest(package.model_dump())})
    prompt = (private / "case-studies/typed-evidence-20261117/PROMPT.txt").read_bytes()
    (folder / "PROMPT.txt").write_bytes(prompt)
    atomic_new(
        folder / "FROZEN_PLAN.json",
        {
            "route": route.model_dump(mode="json"),
            "packages": packages,
            "preserved_failure_sha256": digest(failure),
            "retired_unstarted_package": "typed-evidence-adaptive-02",
            "budget_before": {k: v for k, v in before.items() if k != "calls"},
            "allowance_expanded": False,
            "protocol": "Same frozen data, prompt, model, effort and identical repaired sources. "
            "Fixed then adaptive, no cross-arm outcomes injected. Original aggregate caps "
            "include the failed attempt. No further automatic pair or provider fallback. "
            "All previous evidence and reservations remain immutable.",
        },
    )
    research.activate_model_route(route, expected_previous_id="glm53-typed-evidence-2026-11-17")
    assert research.ledger.snapshot() == before
    return {"status": "replacement_pair_frozen", "packages": packages, "provider_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().private.resolve()), indent=2))
