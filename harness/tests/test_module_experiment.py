import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from qfh.budget import ProviderAdmission, Usage
from qfh.coding_plan import CodingPolicy
from qfh.module_experiment import run
from qfh.research import Research

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("variant", ["peer_review", "feedback_disabled"])
def test_module_ablation_preserves_evidence_and_never_replays_completed_attempt(
    tmp_path, monkeypatch, variant
):
    obj = Research(ROOT / "configs/research-trial.yaml", tmp_path)
    obj.ledger.set_provider_admission(
        ProviderAdmission(
            providers=["glm_coding"], authority="Synthetic test only; no external provider access."
        )
    )
    raw = yaml.safe_load((ROOT / "configs/glm-coding-modular-2026-11-13.yaml").read_text())
    raw["starts_at"] = "2000-01-01T00:00:00+00:00"
    obj.activate_model_route(CodingPolicy.model_validate(raw))
    monkeypatch.setattr("qfh.module_experiment.read_coding_credential", lambda _: "synthetic")

    class FakeGuard:
        def __init__(self, ledger, *_, **__):
            self.ledger = ledger

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    monkeypatch.setattr("qfh.module_experiment.GuardProxy", FakeGuard)
    observed = []

    def fake_call(root, directory, guard, route, key, step, prompt, config):
        observed.append(prompt)
        guard.ledger.reserve(step, step, datetime.now(UTC), output_tokens=128)
        guard.ledger.settle(
            step,
            Usage(input_uncached=10, input_cached=0, input_cache_write=0, output=10),
            metadata={"cache_tokens_reported": True},
        )
        cite = {
            "evidence_id": "filing",
            "quote": "Filing published 2026-04-30 at 18:30 Asia/Shanghai.",
        }
        if prompt["role"] == "reviewer":
            return json.dumps(
                {
                    "findings": [
                        {
                            "candidate_id": prompt["candidate_id"],
                            "topic": "timing",
                            "statement": "Period end cannot establish availability.",
                            "status": "supported",
                            "citations": [cite],
                            "contradicts": [],
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "parent_id": prompt["candidate_id"],
                "definition": {**prompt["initial_candidate"], "signal_rule": "2026-05-06 close"},
                "decisions": [
                    {
                        "finding_id": f["finding_id"],
                        "disposition": "adopt",
                        "reason": "Use release.",
                    }
                    for f in prompt["findings"]
                ],
                "citations": [cite],
                "rationale": "Correct availability",
                "unresolved": [],
            }
        )

    monkeypatch.setattr("qfh.module_experiment.native_call", fake_call)
    case = ROOT / "cases/module-timing.json"
    result = run(tmp_path, case, "offline-module", variant)
    assert result["status"] == "structural_pass"
    assert len(observed) == 2 and observed[0]["sources"] == observed[1]["sources"]
    assert bool(observed[1]["findings"]) == (variant == "peer_review")
    folder = tmp_path / "module-runs/offline-module"
    # Names are distinct on case-insensitive macOS volumes as well as Linux.
    assert (folder / "manifest.json").exists() and (folder / "ARTIFACT_HASHES.json").exists()
    names = [p.name.casefold() for p in folder.iterdir()]
    assert len(names) == len(set(names))
    with pytest.raises(FileExistsError):
        run(tmp_path, case, "offline-module", variant)
    assert len(observed) == 2
    assert len(obj.ledger.snapshot()["calls"]) == 2
