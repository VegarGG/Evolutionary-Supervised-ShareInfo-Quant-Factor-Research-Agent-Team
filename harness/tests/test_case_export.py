import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_case_research import host

from qfh.budget import BudgetRefused, ProviderAdmission
from qfh.case_research import TOOLS
from qfh.coding_plan import CodingLedger
from qfh.research import Research


def test_startup_manifest_preserves_legacy_package_without_new_defaults(tmp_path, monkeypatch):
    seed = tmp_path / "seed"
    seed.mkdir()
    fixture = host(seed)
    legacy = fixture.policy.model_dump()
    for key in ("protocol", "max_tool_bytes", "page_chars", "worker_prompt_bytes"):
        del legacy[key]
    private = tmp_path / "legacy"
    private.mkdir()
    (private / "OFFLINE_ONLY").write_text("No network or provider dispatch.")
    package = private / "package.json"
    package.write_text(json.dumps(legacy))
    root = Path(__file__).parents[1]
    config = root / "configs/research-trial.yaml"
    research = Research(config, private)
    research.ledger.set_provider_admission(
        ProviderAdmission(providers=["glm_coding"], authority="Offline startup regression.")
    )
    research.activate_model_route(fixture.route)
    spec = importlib.util.spec_from_file_location(
        "case_startup_test", root / "scripts/start_research_ui.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def stop_before_transport(*args, **kwargs):
        raise RuntimeError("offline stop before transport")

    monkeypatch.setattr(module, "GuardProxy", stop_before_transport)
    with pytest.raises(RuntimeError, match="offline stop before transport"):
        module.serve(config, private, None, 3080, False, case_package=package)
    manifests = list((private / "research/servers").glob("*/manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_bytes())
    persisted = json.loads((private / "cases/offline-case/package.json").read_bytes())
    assert manifest["case_package"] == persisted == legacy
    assert research.ledger.snapshot()["calls"] == []


def test_timeout_export_preserves_unknown_charge_and_blocks_replay(tmp_path):
    obj = host(tmp_path)
    ledger = CodingLedger(obj.research.ledger, obj.route)
    now = datetime.now(UTC)
    ledger.reserve("timeout", obj.step("supervisor"), now, output_tokens=16384)
    server = tmp_path / "research/servers/fixture"
    server.mkdir(parents=True)
    manifest = {
        "mode": "synthetic",
        "case_package": obj.policy.model_dump(exclude_unset=True),
        "active_model_route": obj.route.model_dump(mode="json"),
        "source_sha256": {},
        "effective_output_cap": 16384,
        "policy": {"max_output_tokens": 16384},
        "budget_before": ledger.snapshot(),
    }
    (server / "manifest.json").write_text(json.dumps(manifest))
    (server / "resources.jsonl").write_text("")
    wire = tmp_path / "campaign/wire/timeout"
    wire.mkdir(parents=True)
    request = {
        "model": obj.route.model,
        "max_tokens": 16384,
        "thinking": {"type": "enabled", "clear_thinking": False},
        "reasoning_effort": obj.route.reasoning_effort,
        "tools": [{"function": {"name": name}} for name in sorted(TOOLS)],
        "messages": [],
    }
    (wire / "request.json").write_text(json.dumps(request))
    path = Path(__file__).parents[1] / "scripts/export_adaptive_run.py"
    spec = importlib.util.spec_from_file_location("case_export_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(AssertionError, match="guard drainage"):
        module.export(tmp_path, "offline-case", case=True, allow_unresolved=True)
    ledger.unknown("timeout", "ReadTimeout")
    before = ledger.snapshot()
    with pytest.raises(AssertionError, match="Explicit unresolved"):
        module.export(tmp_path, "offline-case", case=True)
    result = module.export(tmp_path, "offline-case", case=True, allow_unresolved=True)
    assert result["status"] == "incomplete"
    assert result["audit"]["status"] == "partial_unresolved_usage"
    assert not result["model"]["all_usage_settled"]
    assert result["model"]["requests_with_known_usage"] == 0
    assert result["model"]["input_cache_hit_ratio"] is None
    assert result["model"]["unresolved_reserved_cny"] > 0
    assert ledger.snapshot() == before
    with pytest.raises(BudgetRefused, match="unknown"):
        ledger.reserve("replay", obj.step("supervisor"), now, output_tokens=16384)
