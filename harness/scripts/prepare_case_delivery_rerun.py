"""Freeze one fresh pair after the recorded native evidence-delivery failure."""

import argparse
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
    origin = private / "cases/checkpoint-glm53-max-fixed-01"
    result = json.loads((origin / "RESULT.json").read_bytes())
    assert result["status"] == "incomplete" and result["model"]["all_usage_settled"]
    assert not result["board"]["reviews"] and result["board"]["head"]["kind"] == "revision"
    original = CasePolicy.model_validate_json((origin / "package.json").read_bytes())
    route = CodingPolicy.model_validate(
        yaml.safe_load((root / "configs/glm53-delivery-2026-11-17.yaml").read_text())
    )
    research = Research(root / "configs/research-trial.yaml", private)
    before = research.ledger.snapshot()
    assert not any(c["state"] == "pending" for c in before["calls"])
    assert not any(
        c["step"].startswith("case:checkpoint-glm53-max-adaptive-02:") for c in before["calls"]
    )
    for call in before["calls"]:
        if call["state"] == "unknown":
            CodingLedger(research.ledger, route).verify_reserved_timeout(call)
    folder = private / "case-studies/checkpoint-delivery-20261117"
    folder.mkdir(parents=True, exist_ok=False)
    packages = []
    for number, variant in enumerate(("fixed", "adaptive"), 1):
        ident = f"checkpoint-delivery-{variant}-{number:02}"
        value = original.model_dump()
        value.update(
            package_id=ident,
            study_id=folder.name,
            variant=variant,
            route_id=route.id,
            worker_prompt_bytes=65536,
        )
        value["episode"]["episode_id"] = ident
        package = CasePolicy.model_validate(value)
        assert (
            package.question == original.question
            and package.episode.sources == original.episode.sources
        )
        assert (
            package.episode.rows == original.episode.rows
            and package.episode.initial_spec == original.episode.initial_spec
        )
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
            "repair": "Preload complete current evidence into bounded 65536-byte worker scopes; "
            "retain 24000-byte paged tool views and expose inspection receipts. No question, data, "
            "model, effort, token or per-arm request-limit change. No new data calls.",
            "not_run": {"checkpoint-glm53-max-adaptive-02": "withheld after delivery defect"},
            "protocol": "One repaired fixed/adaptive pair only. Preserve failed first control. "
            "Require settled usage and arithmetic/evidence integrity before the second arm. "
            "Stop on new unknown, quota exhaustion, data/integrity failure; "
            "no automatic further retry.",
        },
    )
    research.activate_model_route(route, expected_previous_id="glm53-checkpoint-2026-11-17")
    assert research.ledger.snapshot() == before
    return {"status": "delivery_pair_frozen", "packages": packages, "provider_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().private.resolve()), indent=2))
