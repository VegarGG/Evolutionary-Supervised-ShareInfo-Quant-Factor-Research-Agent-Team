"""Freeze the owner's authorized structured-report pair; retain all previous ledger state."""

import argparse
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
    origin = private / "cases/checkpoint-delivery-adaptive-02"
    result = json.loads((origin / "RESULT.json").read_bytes())
    assert result["status"] == "finalized_research_prototype"
    assert result["model"]["all_usage_settled"]
    original = CasePolicy.model_validate_json((origin / "package.json").read_bytes())
    route = CodingPolicy.model_validate(
        yaml.safe_load((root / "configs/glm53-structured-report-2026-11-17.yaml").read_text())
    )
    research = Research(root / "configs/research-trial.yaml", private)
    before = research.ledger.snapshot()
    assert not any(c["state"] == "pending" for c in before["calls"])
    assert sum(bool(coding_detail(c)) for c in before["calls"]) == 261
    assert before["cumulative_micro_cny"] == 55583184
    assert before["unresolved_micro_cny"] == 14090240
    for call in before["calls"]:
        if call["state"] == "unknown":
            CodingLedger(research.ledger, route).verify_reserved_timeout(call)
    folder = private / "case-studies/structured-report-20261117"
    folder.mkdir(parents=True, exist_ok=False)
    packages = []
    for number, variant in enumerate(("fixed", "adaptive"), 1):
        ident = f"structured-report-{variant}-{number:02}"
        value = original.model_dump()
        value.update(
            package_id=ident,
            study_id=folder.name,
            variant=variant,
            route_id=route.id,
            protocol="structured-v3",
            authority=route.authority,
        )
        value["episode"]["episode_id"] = ident
        package = CasePolicy.model_validate(value)
        assert package.question == original.question
        assert package.episode.sources == original.episode.sources
        assert package.episode.rows == original.episode.rows
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
            "origin_result_sha256": digest(result),
            "packages": packages,
            "data_snapshot_sha256": original.episode.data_snapshot_sha256,
            "budget_before": {k: v for k, v in before.items() if k != "calls"},
            "change": "Typed host facts and report hashes; structured exact-report reviews; "
            "native deterministic text rendering; numeric copies excluded "
            "from qualitative proposals. "
            "Same original question, rows, evidence, initial factor and per-arm limits. "
            "GLM 5.3/max, 32768 output tokens, 36 aggregate requests, six tasks, six inspections. "
            "No new data requests. Qualitative interpretation still needs independent review. "
            "Credit allowance becomes 7500: 4339.323740 credits are already settled/reserved; "
            "the former 6000 cap leaves only 858.515620 after a full 802.160640 credit wire "
            "reservation, less than the preceding pair consumed. This local pilot allowance "
            "is not a provider quota reading. Original 200 CNY and 80 CNY sublimit unchanged.",
            "protocol": "Run one fixed then one adaptive arm without injecting first-arm outputs. "
            "Require settled usage and arithmetic/evidence integrity before the second arm. "
            "Preserve all rejections/failures. Stop on new unknown, quota exhaustion or integrity "
            "failure. No automatic extra pair. No official evaluation or acceptance.",
        },
    )
    research.activate_model_route(route, expected_previous_id="glm53-delivery-2026-11-17")
    assert research.ledger.snapshot() == before
    return {"status": "structured_pair_frozen", "packages": packages, "provider_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().private.resolve()), indent=2))
