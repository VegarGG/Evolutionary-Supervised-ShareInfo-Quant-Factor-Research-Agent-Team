"""Freeze the task-reference repair after the recorded structured-report pair."""

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
    origin = private / "cases/structured-report-fixed-01"
    result = json.loads((origin / "RESULT.json").read_bytes())
    assert result["status"] == "finalized_research_prototype"
    assert result["model"]["all_usage_settled"]
    failed = json.loads((private / "cases/structured-report-adaptive-02/RESULT.json").read_bytes())
    assert failed["status"] == "incomplete" and failed["model"]["all_usage_settled"]
    assert not failed["board"]["findings"] and not failed["board"]["reviews"]
    assert any(
        e["kind"] == "task_finished" and e["body"]["status"] == "failed"
        for e in failed["board"]["tasks"]
    )
    original = CasePolicy.model_validate_json((origin / "package.json").read_bytes())
    route = CodingPolicy.model_validate(
        yaml.safe_load((root / "configs/glm53-task-bound-2026-11-17.yaml").read_text())
    )
    research = Research(root / "configs/research-trial.yaml", private)
    before = research.ledger.snapshot()
    assert not any(c["state"] == "pending" for c in before["calls"])
    assert sum(bool(coding_detail(c)) for c in before["calls"]) == 292
    assert before["cumulative_micro_cny"] == 64834632
    assert before["unresolved_micro_cny"] == 14090240
    for call in before["calls"]:
        if call["state"] == "unknown":
            CodingLedger(research.ledger, route).verify_reserved_timeout(call)
    folder = private / "case-studies/task-bound-20261117"
    folder.mkdir(parents=True, exist_ok=False)
    packages = []
    for number, variant in enumerate(("fixed", "adaptive"), 1):
        ident = f"task-bound-{variant}-{number:02}"
        value = original.model_dump()
        value.update(
            package_id=ident,
            study_id=folder.name,
            variant=variant,
            route_id=route.id,
            protocol="structured-v3",
            reference_mode="task_bound",
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
            "change": "Host-bound immutable task targets and short immutable references replace "
            "model copying of candidate/report/inspection/finding hashes. Full hashes and raw "
            "payload digests remain in append-only binding events. Stale tasks still fail. "
            "Enumerate fact references, clarify defects versus caveats and sort report metrics. "
            "Same question, data, baseline, model, effort and per-arm caps. No new data calls. "
            "Credit cap stays 7500. Local exposure cap becomes 100 CNY: 59.403050 CNY is already "
            "settled/reserved; with a 9.306112 full request reservation the former 80 cap left "
            "11.290838 CNY, less than twice the preceding fixed arm. Original 200 CNY unchanged.",
            "preserved_failure": failed["package_id"],
            "failed_result_sha256": digest(failed),
            "protocol": "Run one fixed then one adaptive arm without injecting first-arm outputs. "
            "Require settled usage and arithmetic/evidence integrity before the second arm. "
            "Preserve all rejections/failures. Stop on new unknown, quota exhaustion or integrity "
            "failure. No automatic extra pair. No official evaluation or acceptance.",
        },
    )
    research.activate_model_route(route, expected_previous_id="glm53-structured-report-2026-11-17")
    assert research.ledger.snapshot() == before
    return {"status": "task_bound_pair_frozen", "packages": packages, "provider_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().private.resolve()), indent=2))
