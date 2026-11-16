"""Explicit 16k-to-32k continuation after the recorded maximum-effort length stop."""

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
    origin = private / "cases/unseen-glm53-max-adaptive-01"
    prior = json.loads((origin / "RESULT.json").read_bytes())
    assert prior["status"] == "incomplete" and prior["model"]["all_usage_settled"]
    assert any(c["finish_reason"] == "length" for c in prior["wire_calls"])
    assert not prior["board"]["findings"] and not prior["board"]["finalized"]
    original = CasePolicy.model_validate_json((origin / "package.json").read_bytes())
    route = CodingPolicy.model_validate(
        yaml.safe_load((root / "configs/glm53-max-32k-unseen-2026-11-16.yaml").read_text())
    )
    research = Research(root / "configs/research-trial.yaml", private)
    before = research.ledger.snapshot()
    assert not any(c["state"] == "pending" for c in before["calls"])
    for call in before["calls"]:
        if call["state"] == "unknown":
            CodingLedger(research.ledger, route).verify_reserved_timeout(call)
    folder = private / "case-studies/unseen-glm53-max32-20261116"
    folder.mkdir(parents=True, exist_ok=False)
    packages = []
    for number, variant in enumerate(("adaptive", "fixed"), 1):
        ident = f"unseen-glm53-max32-{variant}-{number:02}"
        value = original.model_dump()
        value.update(
            package_id=ident,
            study_id=folder.name,
            variant=variant,
            route_id=route.id,
            max_output_tokens=32768,
        )
        # Keep the existing model-visible authority text; record new operator
        # limits outside the task rather than adding a desired factor answer.
        value["episode"]["episode_id"] = ident
        package = CasePolicy.model_validate(value)
        assert package.question == original.question
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
            "origin_result_sha256": digest(prior),
            "reason": "Max-effort analyst stopped at 16384 output tokens before any finding; "
            "all usage settled. Explicit bounded output-cap amendment; not an automatic retry.",
            "packages": packages,
            "output_cap_from": original.max_output_tokens,
            "output_cap_to": 32768,
            "data_snapshot_sha256": original.episode.data_snapshot_sha256,
            "budget_before": {k: v for k, v in before.items() if k != "calls"},
            "protocol": "Same question, initial factor, data, research prompts and max effort. "
            "Adaptive then fixed if new usage settles and integrity checks pass. No further "
            "automatic retries, provider fallback or forced factor change. Stop on new unknown.",
            "not_run": {"unseen-glm53-max-fixed-02": "16k arm stopped at response limit"},
        },
    )
    research.activate_model_route(route, expected_previous_id="glm53-max-unseen-2026-11-16")
    assert research.ledger.snapshot() == before
    return {"status": "cap_rerun_frozen", "packages": packages, "provider_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.private.resolve()), indent=2))
