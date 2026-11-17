"""Freeze the owner-requested same-case pair under the updated semantic guards."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from qfh.case_research import CasePolicy
from qfh.coding_plan import CodingLedger, CodingPolicy, coding_detail
from qfh.research import Research
from qfh.shared_state import atomic_new, digest


def prepare(private):
    root = Path(__file__).resolve().parents[1]
    origin = private / "cases/task-bound-fixed-01"
    original = CasePolicy.model_validate_json((origin / "package.json").read_bytes())
    prior = {}
    for ident in ("task-bound-fixed-01", "task-bound-adaptive-02"):
        folder = private / "cases" / ident
        result = json.loads((folder / "RESULT.json").read_bytes())
        assert result["status"] == "finalized_research_prototype"
        assert result["model"]["all_usage_settled"]
        assert json.loads((folder / "INDEPENDENT_ARITHMETIC.json").read_bytes())["status"] == "pass"
        prior[ident] = digest(result)
    route = CodingPolicy.model_validate(
        yaml.safe_load((root / "configs/glm53-semantic-guards-2026-11-17.yaml").read_text())
    )
    research = Research(root / "configs/research-trial.yaml", private)
    before = research.ledger.snapshot()
    assert not any(c["state"] == "pending" for c in before["calls"])
    assert sum(bool(coding_detail(c)) for c in before["calls"]) == 335
    assert before["cumulative_micro_cny"] == 76938368
    assert before["unresolved_micro_cny"] == 14090240
    for call in before["calls"]:
        if call["state"] == "unknown":
            CodingLedger(research.ledger, route).verify_reserved_timeout(call)
    folder = private / "case-studies/semantic-guards-20261117"
    folder.mkdir(parents=True, exist_ok=False)
    packages = []
    for number, variant in enumerate(("fixed", "adaptive"), 1):
        ident = f"semantic-guards-{variant}-{number:02}"
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
        assert package.question == original.question
        assert package.episode.sources == original.episode.sources
        assert package.episode.rows == original.episode.rows
        assert package.episode.initial_spec == original.episode.initial_spec
        assert package.protocol == "structured-v3" and package.reference_mode == "task_bound"
        assert package.total_requests == 36 and package.max_output_tokens == 32768
        assert ident in route.reserved_connection_timeouts[0].groups
        atomic_new(private / "case-packages" / f"{ident}.json", package.model_dump())
        packages.append({"package_id": ident, "sha256": digest(package.model_dump())})
    # Reuse the actual prior native root prompt, without operator findings or outcomes.
    first = next(c for c in before["calls"] if c["step"] == "case:task-bound-fixed-01:supervisor")
    request = json.loads((private / "campaign/wire" / first["id"] / "request.json").read_bytes())
    users = [m["content"] for m in request["messages"] if m["role"] == "user"]
    assert len(users) == 2 and isinstance(users[0], str)
    assert users[1].startswith("<system-reminder>")
    (folder / "PROMPT.txt").write_text(users[0])
    atomic_new(
        folder / "FROZEN_PLAN.json",
        {
            "at": datetime.now(UTC).isoformat(),
            "authority": route.authority,
            "route": route.model_dump(mode="json"),
            "prior_result_hashes": prior,
            "packages": packages,
            "data_snapshot_sha256": original.episode.data_snapshot_sha256,
            "prompt_sha256": hashlib.sha256(users[0].encode()).hexdigest(),
            "budget_before": {k: v for k, v in before.items() if k != "calls"},
            "changes_under_test": [
                "Reject recorded unqualified dispersion-width comparisons unless a measure "
                "is named; reject the false heterogeneous-units heading.",
                "Independent audit checks spec digests and changed-row counts even if wrong "
                "report fields are consistently hashed.",
            ],
            "allowance_basis": "Before this pair, 6178.406360 conservative credits are "
            "settled/reserved. A full 32768-output request reserves 802.160640 credits, "
            "leaving only 519.433000 usable under the old 7500 cap, below the prior pair's "
            "1042.544430 credits. The new 9000 cap leaves 2019.433000 before actual usage. "
            "The local historical cash cap stays 100 CNY, inside the original 200.",
            "protocol": "Freeze identical updated source snapshots. Run fixed then adaptive "
            "with the same question, data, initial spec, model, effort and caps. Do not inject "
            "first-arm outputs or operator reviews into the second arm. Require settled "
            "usage and arithmetic/evidence integrity before the second arm; semantic failure "
            "is an outcome, not a reason to force revision. Preserve rejected submissions "
            "and native failures. Stop on new unknown, quota exhaustion or integrity failure. "
            "No extra automatic pair, new data, evaluation, official acceptance or publication.",
        },
    )
    research.activate_model_route(route, expected_previous_id="glm53-task-bound-2026-11-17")
    assert research.ledger.snapshot() == before
    return {"status": "semantic_guard_pair_frozen", "packages": packages, "provider_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().private.resolve()), indent=2))
