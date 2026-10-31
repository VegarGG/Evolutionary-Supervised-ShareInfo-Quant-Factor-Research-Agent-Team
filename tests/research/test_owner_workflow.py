"""Phase 6 acceptance: a scripted host agent completes the five workflow steps through the
MCP front door on the synthetic world (P6.7, Section 13.1).

1. a brief, 2. a deliverable with its iteration history and backtest results, 3. the
owner's approval recorded with its short codes, 4. a factor pool entry and a strategy pool
entry written, 5. the evaluator's library synced from the approved entries.
Every model answer is scripted; no provider is reached.

On the 60-name test universe a 20-name long-only portfolio is too concentrated for the
shipped strategy thresholds (its net Sharpe is about 0.4 on W0 and negative on W1, against
0.8), so the strategy
half of this test lowers the research pre-screen and activates a test protocol version
(never shipped) with W1 strategy gates the composite clears. It checks the workflow, not
the gates; BM-STRATEGY measures the shipped gates on the benchmark world.
"""

import pytest
from qfr_research.store import Ctx
from qfr_research.tools import ToolDeps, workbench_evaluate

from tests.research.rig import brief, research_stack
from tests.research.scripted import Script

pytestmark = pytest.mark.postgres

REVERSAL = ("-Delta($close, 5) / Ref($close, 5)", 1)  # test data on the planted world
STRATEGY_SPEC = {"top_k": 20, "dropout": 5, "max_components": 2}
LOOSE_STRATEGY_GATES = {
    "w1_strategy": {"rankic_min": 0.0, "nw_t_min": 0.0, "net_sharpe_min": -10.0, "ir_min": -10.0,
                    "drawdown_max": 1.0, "strategy_correlation_max": 1.0},
}  # fmt: skip


@pytest.fixture
def full(tmp_path, monkeypatch, small_zones):
    with research_stack(tmp_path, monkeypatch, small_zones, Script([REVERSAL])) as built:
        yield built


def deliver(full, body):
    """Submit a brief and run research and the evaluator until a deliverable is ready."""
    mcp, research = full.mcp, full.research
    job = mcp.ok("qfr.job.submit", brief=body)["data"]["job"]
    for _ in range(4):
        research.tick()
        full.settle(rounds=6)
        full.eval.release.tick()
        state = mcp.ok("qfr.job.get", job_id=job["job_id"])["data"]["job"]["state"]
        if state == "DELIVERABLE_READY":
            break
        research.clock.advance(hours=1)
    (listed,) = mcp.ok("qfr.deliverable.list", job_id=job["job_id"])["data"]["items"]
    fetched = mcp.ok("qfr.deliverable.get", deliverable_id=listed["deliverable_id"])["data"]
    return job, fetched


def approve(full, job, fetched, confirmation):
    return full.mcp.call(
        "qfr.approval.record",
        decision="approve",
        deliverable_id=fetched["deliverable"]["deliverable_id"],
        owner_confirmation=confirmation,
        rationale="The evidence supports a pool entry.",
    )


def test_a_host_agent_completes_the_five_workflow_steps(full, monkeypatch):
    mcp = full.mcp

    # 1-2. A factor brief and its deliverable with history and backtest evidence.
    job, fetched = deliver(full, brief())
    document = fetched["deliverable"]
    (factor,) = document["items"]
    assert document["short_codes"] == [f"{job['short_code']} F-1"]
    assert factor["iteration_history"]["hops"]
    assert {r["content"]["type"] for r in factor["released_reports"]} >= {"w1"}
    assert fetched["tier_confirmation"][factor["version_id"]]["confirmed"] is True

    # 3. MCP-03: a confirmation without every short code is refused; nothing is stored.
    refused = approve(full, job, fetched, f"APPROVE {job['short_code']}")
    assert refused["isError"] and "SHORT_CODE_MISSING" in refused["content"][0]["text"]
    assert mcp.store.list_approvals(10) == []
    recorded = approve(full, job, fetched, f"approve {job['short_code']} f-1")["structuredContent"]
    approval = recorded["data"]["approval"]
    assert approval["short_codes_matched"] == [f"{job['short_code']} F-1"]
    assert approval["scope"]["tier"] == "w1_pass"
    assert approval["scope"]["version_ids"] == [factor["version_id"]]

    # 4a. The factor pool entry, with the tier the approval fixed.
    added = mcp.ok(
        "qfr.pool.add",
        approval_id=approval["approval_id"],
        version_id=factor["version_id"],
        title="Short-horizon reversal",
        tags=["reversal"],
    )["data"]
    factor_entry = added["entry"]
    assert (factor_entry["pool"], factor_entry["status"], factor_entry["approved_tier"]) == (
        "factor", "approved", "w1_pass",
    )  # fmt: skip
    assert factor_entry["short_code"] == f"E-{factor_entry['entry_id'].replace('-', '')[-6:]}"
    closed = mcp.ok(
        "qfr.job.close", job_id=job["job_id"], decision="approved",
        approval_id=approval["approval_id"],
    )["data"]  # fmt: skip
    assert closed["state"] == "CLOSED"

    # 1-2 again for a strategy seeded with the approved factor entry (test gates, above).
    prescreen = full.research.config.charter_values["prescreen"]
    monkeypatch.setitem(prescreen, "strategy_net_sharpe_min", 0.0)  # type: ignore[arg-type]
    full.eval.activate_protocol("test-strategy", LOOSE_STRATEGY_GATES)
    strategy_brief = brief(
        title="Reversal top-k strategy",
        objective="Compose a long-only top-k strategy from the approved reversal factor.",
        mode="new_strategy",
        seeds={"pool_entry_ids": [factor_entry["entry_id"]], "version_ids": [],
               "expressions": [], "notes": ""},
        strategy_spec=STRATEGY_SPEC,
    )  # fmt: skip
    strategy_job, strategy_fetched = deliver(full, strategy_brief)
    strategies = [i for i in strategy_fetched["deliverable"]["items"] if i["kind"] == "strategy"]
    assert strategies, strategy_fetched["deliverable"]["items"]
    strategy = strategies[0]
    code = strategy_fetched["deliverable"]["short_codes"][
        strategy_fetched["deliverable"]["items"].index(strategy)
    ]
    assert code.startswith(f"{strategy_job['short_code']} S-")
    assert strategy_fetched["deliverable"]["status"] == "complete"
    assert strategy["tier_reached"] == "w1_pass"
    assert (
        strategy["manifest"]["implementation"]["components"][0]["version_id"]
        == (factor["version_id"])
    )
    assert strategy_fetched["contribution_tables"][strategy["version_id"]]

    # The strategy prompt lists each component with its released W1 report, and the
    # engineer measured the composite on W0 with workbench.evaluate (Section 11.3).
    composed = next(
        s
        for s in full.research.steps(step_type="PROMPT_SENT", actor="engineer")
        if "working in strategy mode" in s.payload["prompt"]
    )
    assert '"w1_report_id": ' in composed.payload["prompt"]
    measured = [
        s
        for s in full.research.steps(step_type="TOOL_CALLED", actor="tool:workbench.evaluate")
        if "components" in s.inputs["args"]
    ]
    assert measured and measured[0].payload["composite"] is True
    assert measured[0].payload["components"][0]["version_id"] == factor["version_id"]
    assert measured[0].payload["visibility"] == "research_non_official"
    deps = ToolDeps(full.research.env, "engineer", Ctx())
    part = {"version_id": factor["version_id"], "sign": 1, "weight": 1.0}
    for arguments, reason in (
        ({"components": [part], "top_k": 5, "dropout": 5}, "PORTFOLIO_OUT_OF_BOUNDS"),
        ({"components": [part] * 9, "top_k": 20, "dropout": 5}, "COMPONENTS_OUT_OF_BOUNDS"),
        ({"components": [part | {"version_id": "x"}], "top_k": 20}, "VERSION_UNKNOWN"),
        ({"components": [part | {"weight": 0}], "top_k": 20}, "COMPONENT_INVALID"),
    ):
        refused = workbench_evaluate(deps, **arguments)
        assert refused["ok"] is False and reason in str(refused["errors"]), (arguments, refused)

    # 3-4b. The strategy approval and pool entry.
    recorded = mcp.ok(
        "qfr.approval.record",
        decision="approve",
        deliverable_id=strategy_fetched["deliverable"]["deliverable_id"],
        version_ids=[strategy["version_id"]],
        owner_confirmation=f"APPROVE {code}",
        rationale="The composite passed its gates.",
    )["data"]
    strategy_entry = mcp.ok(
        "qfr.pool.add",
        approval_id=recorded["approval_id"],
        version_id=strategy["version_id"],
        title="Reversal top-k",
    )["data"]["entry"]
    assert (strategy_entry["pool"], strategy_entry["status"]) == ("strategy", "approved")

    # 5. The evaluator syncs both approved entries into its library.
    full.eval.scheduler.tick()
    library = {
        str(r.version_id): r
        for r in full.eval.db.rows("SELECT version_id, status FROM eval.library")
    }
    assert {factor["version_id"], strategy["version_id"]} <= set(library)
    assert {library[factor["version_id"]].status, library[strategy["version_id"]].status} == {
        "active"
    }
    listed = mcp.ok("qfr.pool.list", pool="factor")["data"]["items"]
    assert [i["short_code"] for i in listed] == [factor_entry["short_code"]]

    # Every approval-gated write left an audit row and a trace step.
    tools = [c.tool for c in mcp.audit.calls if c.outcome == "ok"]
    assert tools.count("qfr.approval.record") == 2 and tools.count("qfr.pool.add") == 2
    count = "SELECT count(*) FROM trace_steps WHERE step_type = :t"
    assert mcp.control_db.count(count, t="APPROVAL_RECORDED") == 2
    assert mcp.control_db.count(count, t="POOL_EVENT") == 2
