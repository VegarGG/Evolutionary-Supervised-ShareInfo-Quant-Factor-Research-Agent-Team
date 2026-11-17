import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path


def test_crashed_server_is_not_attributed_to_a_later_trial(tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts/summarize_research.py"
    spec = importlib.util.spec_from_file_location("research_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    now = datetime.now().astimezone()
    for name, offset in (("crashed", -90), ("active", 10)):
        server = tmp_path / name
        server.mkdir()
        (server / "manifest.json").write_text(
            json.dumps({"started_at": (now - timedelta(seconds=120)).isoformat(), "name": name})
        )
        (server / "resources.jsonl").write_text(
            json.dumps({"at": (now + timedelta(seconds=offset)).isoformat(), "pids": [1]})
            + '\n{"unfinished":'
        )
        # Neither has stopped.json: one crashed, one is still running.
    samples, manifests = module.collect_resources(tmp_path, now, now + timedelta(seconds=20))
    assert len(samples) == 1
    assert [m["manifest"]["name"] for m in manifests] == ["active"]
