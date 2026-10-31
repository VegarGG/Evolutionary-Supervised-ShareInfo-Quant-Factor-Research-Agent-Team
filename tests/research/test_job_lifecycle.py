"""The job controls through the MCP front door (P4.11): list, wait, steer, pause, resume
and cancel. Every model answer is scripted; no provider is reached."""

import pytest

from tests.research.rig import brief, research_stack
from tests.research.scripted import Script

pytestmark = pytest.mark.postgres

# Test data on the planted synthetic world; not a product default.
REVERSAL = ("-Delta($close, 5) / Ref($close, 5)", 1)
NOTE = "Prefer liquid names and explain the holding period."


@pytest.fixture
def full(tmp_path, monkeypatch, small_zones):
    with research_stack(tmp_path, monkeypatch, small_zones, Script([REVERSAL])) as built:
        yield built


def test_steer_pause_resume_and_cancel_through_mcp(full):
    mcp, research = full.mcp, full.research
    job = mcp.ok("qfr.job.submit", brief=brief())["data"]["job"]
    job_id = job["job_id"]
    listed = mcp.ok("qfr.job.list")["data"]["items"]
    assert [j["job_id"] for j in listed] == [job_id] and listed[0]["state"] == "RUNNING"
    waited = mcp.ok("qfr.job.wait", job_id=job_id, timeout_s=0)["data"]
    assert waited["changed"] is False and waited["job"]["state"] == "RUNNING"
    assert "TIMEOUT_INVALID" in mcp.error("qfr.job.wait", job_id=job_id, timeout_s=601)

    # Steering appends to the charter and reaches the next generation's prompts.
    steered = mcp.ok("qfr.job.steer", job_id=job_id, note=NOTE)["data"]
    assert steered["charter_version"] == job["charter_version"] + 1
    (step,) = research.steps(step_type="STEERING_ADDED")
    assert step.actor_kind == "host_agent" and step.outcome == "ok"

    # A paused job starts no generation and spends nothing.
    paused = mcp.ok("qfr.job.pause", job_id=job_id)["data"]
    assert paused["paused"] is True and paused["state"] == "RUNNING"
    quiet = research.tick()
    assert quiet["generations_started"] == [] and quiet["ran"] == []
    assert research.db.scalar("SELECT count(*) FROM agent_runs") == 0

    resumed = mcp.ok("qfr.job.resume", job_id=job_id)["data"]
    assert resumed["paused"] is False
    assert research.tick()["ran"][0]["state"] == "CLOSED"
    prompts = research.db.rows(
        "SELECT role, request_messages FROM agent_runs WHERE role IN ('supervisor', 'hypothesis')"
    )
    assert prompts and all(NOTE in str(row.request_messages) for row in prompts)

    cancelled = mcp.ok("qfr.job.cancel", job_id=job_id)["data"]
    assert cancelled["state"] == "CLOSED" and cancelled["close_decision"] == "cancelled"
    assert mcp.ok("qfr.job.wait", job_id=job_id, timeout_s=0, state="RUNNING")["data"]["changed"]
    assert research.tick()["generations_started"] == []
    assert "JOB_CLOSED" in mcp.error("qfr.job.steer", job_id=job_id, note=NOTE)
    events = mcp.ok("qfr.job.events", job_id=job_id)["data"]["items"]
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "submitted" and {"steered", "paused", "resumed"} <= set(kinds), kinds
    assert events[-1]["kind"] == "state_changed" and "CLOSED" in str(events[-1]["payload"])
    # Published versions stay published after a cancel.
    assert research.db.scalar("SELECT count(*) FROM candidate_versions") >= 1
