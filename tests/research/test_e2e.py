"""Phase 4 acceptance, offline end to end through the MCP front door (P4.12).

A brief submitted with qfr.job.submit produces a job and a generation with hypotheses,
candidates, reviews and publications; the evaluator measures them on W1 and releases the
reports at the next batch; the next generation syncs them back and writes
interpretations; the job monitor reads the w1_pass tier and assembles a deliverable that
qfr.deliverable.get returns with its iteration history and owner-grade evidence.
Every model answer is scripted; no provider is reached.
"""

import json
from datetime import datetime

import pytest

from tests.research.rig import brief, research_stack
from tests.research.scripted import Script

pytestmark = pytest.mark.postgres

# Test data on the planted synthetic world: a reversal that passes W1, and a second
# draft. Neither is a product default; the product ships no factor.
REVERSAL = ("-Delta($close, 5) / Ref($close, 5)", 1)
SECOND = ("Mean($close, 5) / Mean($close, 20) - 1", 1)


@pytest.fixture
def full(tmp_path, monkeypatch, small_zones):
    with research_stack(tmp_path, monkeypatch, small_zones, Script([REVERSAL, SECOND])) as built:
        yield built


def run_to_deliverable(full):
    mcp, research = full.mcp, full.research
    submitted = mcp.ok("qfr.job.submit", brief=brief())["data"]
    job_id = submitted["job"]["job_id"]
    research.tick()  # generation 1
    full.settle()  # the evaluator pulls, screens and evaluates on W1
    due = research.db.scalar(
        "SELECT next_generation_at FROM research_jobs WHERE job_id = :j", j=job_id
    )
    assert due is not None
    full.eval.clock.at = max(full.eval.clock.at, due)
    full.eval.release.tick()  # the W1 batch is released
    research.tick()  # generation 2 syncs the reports; the criteria are met
    return submitted, job_id


def test_offline_brief_to_deliverable_through_mcp(full):
    mcp, research = full.mcp, full.research
    submitted, job_id = run_to_deliverable(full)
    assert submitted["created"] is True and submitted["job"]["short_code"].startswith("J-")
    assert submitted["timeline"]["tier"] == "w1_pass"
    assert submitted["charter"]["deliverable"]["tier"] == "w1_pass"

    got = mcp.ok("qfr.job.get", job_id=job_id)["data"]
    assert got["job"]["state"] == "DELIVERABLE_READY", got["job"]
    first, second = sorted(got["generations"], key=lambda g: g["seq"])[-2:]
    assert first["state"] == "CLOSED" and second["state"] == "CLOSED"

    # Generation 1: a plan, hypotheses, candidates, reviews, at most 12 publications.
    counts = {
        table: research.db.scalar(f"SELECT count(*) FROM {table}")
        for table in ("hypotheses", "candidates", "reviews", "candidate_versions")
    }
    assert counts["hypotheses"] >= 1 and counts["candidates"] >= 2 and counts["reviews"] >= 2
    assert 1 <= counts["candidate_versions"] <= 12, counts
    # Generation 2: the released W1 reports were synced and interpreted.
    assert research.db.scalar("SELECT count(*) FROM report_cache WHERE report_type = 'w1'") >= 1
    assert research.db.scalar("SELECT count(*) FROM interpretations") >= 1

    listed = mcp.ok("qfr.deliverable.list", job_id=job_id)["data"]["items"]
    assert len(listed) == 1 and listed[0]["status"] == "complete"
    deliverable_id = listed[0]["deliverable_id"]
    assert listed[0]["fetched_at"] is None

    fetched = mcp.ok("qfr.deliverable.get", deliverable_id=deliverable_id)["data"]
    assert fetched["visibility"] == "owner_only" and fetched["evidence"] == "ok"
    document = fetched["deliverable"]
    assert document["schema_version"] == "deliverable/1"
    assert document["short_codes"] == [f"{submitted['job']['short_code']} F-1"]
    (item,) = document["items"]
    assert item["tier_reached"] == "w1_pass"
    assert item["manifest"]["implementation"]["expression"] == REVERSAL[0]
    assert fetched["tier_confirmation"][item["version_id"]]["confirmed"] is True
    assert item["owner_evidence"]["visibility"] == "owner_only"
    assert {r["content"]["type"] for r in item["released_reports"]} >= {"intake", "w1"}
    history = item["iteration_history"]
    assert history["schema_version"] == "iteration_history/1" and history["hops"]
    assert any("in-sample" in c or "W0" in c for c in item["caveats"])
    assert any("coarsen" in c.lower() for c in item["caveats"])
    assert document["costs"]["total_cny"] > 0

    after = mcp.ok("qfr.job.get", job_id=job_id)["data"]["job"]
    assert after["state"] == "DELIVERED"
    assert after["cost_cny"] <= brief()["budget"]["max_cost"]
    events = mcp.ok("qfr.job.events", job_id=job_id)["data"]["items"]
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "submitted" and "deliverable_ready" in kinds

    costs = mcp.ok("qfr.ops.costs", job_id=job_id, group_by=["role"])["data"]
    roles = {row["key"]["role"] for row in costs["rows"]}
    assert {"supervisor", "hypothesis", "engineer", "critic", "analyst"} <= roles
    # No generation exceeded its cost cap.
    cap = float(research.config.charter_values["budget"]["generation"])
    spent = research.db.rows(
        "SELECT generation_id, sum(cost_cny) AS c FROM budget_ledger WHERE generation_id IS "
        "NOT NULL GROUP BY generation_id"
    )
    assert spent and all(float(r.c) <= cap for r in spent)

    trace = mcp.ok("qfr.trace.get", version_id=item["version_id"])["data"]
    assert trace["export"]["schema_version"] == "trace/1"
    lineage = mcp.ok("qfr.lineage.get", version_id=item["version_id"])["data"]
    assert lineage["registry"]["version_id"] == item["version_id"]

    status = mcp.ok("qfr.status")["data"]
    assert status["services"]["research-api"]["status"] == "ok"
    assert status["active_jobs"]["by_state"].get("DELIVERED") == 1
    assert status["budgets"]["cost_today"] > 0
    setup = mcp.ok("qfr.setup.status")["data"]
    assert setup["steps"]["providers"]["status"] == "ok"
    assert setup["probe_results"]["ok"] is True


def test_resources_read_the_job_and_deliverable_without_marking_it_fetched(full):
    _, job_id = run_to_deliverable(full)
    client, headers = (
        full.mcp.client,
        {
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )

    def read(uri):
        response = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": uri}},
        )
        return response.json()["result"]["contents"][0]["text"]

    job = json.loads(read(f"qfr://jobs/{job_id}"))
    assert job["job"]["state"] == "DELIVERABLE_READY"
    assert job["job"]["deliverables"] == 1
    (listed,) = full.mcp.ok("qfr.deliverable.list", job_id=job_id)["data"]["items"]
    deliverable_id = listed["deliverable_id"]
    composed = json.loads(read(f"qfr://deliverables/{deliverable_id}"))
    assert composed["deliverable"]["status"] == "complete" and composed["fetched_at"] is None
    assert full.mcp.ok("qfr.job.get", job_id=job_id)["data"]["job"]["state"] == (
        "DELIVERABLE_READY"
    )
    protocol = json.loads(read("qfr://cards/protocol"))
    assert protocol["state"] == "active" and "gates" in protocol["card"]
    assert datetime.fromisoformat(job["job"]["submitted_at"])


def test_log_03_and_mcp_01_one_job_id_joins_every_service(full):
    _, job_id = run_to_deliverable(full)
    (listed,) = full.mcp.ok("qfr.deliverable.list", job_id=job_id)["data"]["items"]
    full.mcp.ok("qfr.deliverable.get", deliverable_id=listed["deliverable_id"])

    found = full.mcp.ok("qfr.logs.correlate", id=job_id, id_kind="job", query={"limit": 2000})[
        "data"
    ]
    services = set(found["grouped_by_service"])
    assert services >= {
        "qfr-mcp",
        "research-api",
        "research-worker",
        "registry-api",
        "eval-scheduler",
        "eval-worker",
        "release-worker",
    }, services
    times = [line["ts"] for line in found["lines"]]
    assert times == sorted(times)

    # MCP-01: each MCP call is audited, and its request id reaches research-api's log.
    call = full.mcp.audit.calls[-1]
    assert call.tool == "qfr.logs.correlate" and call.outcome == "ok"
    fetch = next(c for c in full.mcp.audit.calls if c.tool == "qfr.deliverable.get")
    assert fetch.downstream_request_ids == [fetch.request_id]
    api_lines = [
        line for line in full.research.logs("research-api")
        if line.get("request_id") == fetch.request_id
    ]  # fmt: skip
    assert api_lines and all(line.get("job_id") in (None, job_id) for line in api_lines)
