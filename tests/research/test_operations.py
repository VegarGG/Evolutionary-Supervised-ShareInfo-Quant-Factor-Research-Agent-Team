"""The research worker's operations: cost and generation caps, the wall-clock deadline,
the cadence, queue retries and leases, and the provider probe (P4.1, P4.2, P4.10).

Every model answer is scripted and every price is a test price; no provider is reached.
"""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from qfr_core.contracts import ResearchBrief
from qfr_core.eval_api import ReportPage
from qfr_research import queue
from qfr_research.jobs import JobService
from qfr_research.monitor import answered
from qfr_research.probe import run_probe
from qfr_research.settings import ResearchConfig
from qfr_research.worker import Worker
from qfr_research.workflow import GenerationRunner

from tests.research.rig import brief, research_only
from tests.research.scripted import Script
from tests.research.test_generation import scan

pytestmark = pytest.mark.postgres

# Test data on the planted synthetic world; not a product default.
REVERSAL = ("-Delta($close, 5) / Ref($close, 5)", 1)


@pytest.fixture
def research(tmp_path, small_zones):
    with research_only(tmp_path, small_zones, Script([REVERSAL])) as (_, built):
        yield built


def submit(research, **budget):
    body = brief(
        budget={"max_cost": 40.0, "max_generations": 3, "max_wall_clock_days": 14} | budget
    )
    submitted = JobService(research.api_env).submit(
        ResearchBrief.model_validate(body), scan(), "control"
    )
    return submitted.job.job_id


def job(research, job_id):
    return research.db.rows("SELECT * FROM research_jobs WHERE job_id = :j", j=job_id)[0]


def events(research, job_id):
    return research.db.rows(
        "SELECT kind, payload FROM job_events WHERE job_id = :j ORDER BY seq", j=job_id
    )


# Caps and the deadline -------------------------------------------------------------------


def test_the_job_cost_cap_stops_research_and_closes_the_job(research):
    """A cap below one supervisor call's estimate: the job-start probe is paid, the next
    call is refused before it is sent, the job waits for evaluation, and with nothing
    published it closes as budget_exhausted. Nothing ever exceeds the cap."""
    cap = 0.2
    job_id = submit(research, max_cost=cap)
    result = research.tick()
    assert result["ran"][0]["state"] == "CLOSED"
    (generation,) = research.db.rows("SELECT * FROM generations WHERE seq = 1")
    assert generation.budget_stop == "budget_job"
    # Only the probe ran; no role call was sent.
    assert research.db.scalar("SELECT count(*) FROM agent_runs") == 0
    stopped = [line for line in research.logs("research-worker") if line["event"] == "budget_stop"]
    assert stopped and stopped[0]["error_code"] == "BUDGET_JOB"
    assert stopped[0]["payload"]["cap"] == cap and stopped[0]["payload"]["role"] == "supervisor"

    row = job(research, job_id)
    assert row.state == "WAITING_FOR_EVALUATION" and row.next_generation_at is None
    assert ("research_stopped", "job cost cap reached") in [
        (e.kind, e.payload.get("reason")) for e in events(research, job_id)
    ]
    spent = research.db.scalar(
        "SELECT sum(cost_cny) FROM budget_ledger WHERE job_id = :j", j=job_id
    )
    assert 0 < float(row.cost_cny) == float(spent) <= cap

    closed = research.tick()
    assert closed["jobs_closed"] == [str(job_id)]
    row = job(research, job_id)
    assert (row.state, row.close_decision) == ("CLOSED", "budget_exhausted")
    assert research.db.scalar("SELECT count(*) FROM deliverables WHERE job_id = :j", j=job_id) == 0


def test_the_generation_cap_waits_for_evaluation_then_the_deadline_closes_best_effort(research):
    job_id = submit(research, max_generations=1, max_wall_clock_days=2)
    assert research.tick()["ran"][0]["state"] == "CLOSED"
    assert research.db.scalar("SELECT count(*) FROM candidate_versions") >= 1
    row = job(research, job_id)
    assert row.state == "WAITING_FOR_EVALUATION" and row.next_generation_at is None
    assert ("research_stopped", "generation cap reached") in [
        (e.kind, e.payload.get("reason")) for e in events(research, job_id)
    ]

    # The published version still waits for W1, so the job stays open and nothing runs.
    research.clock.advance(hours=12)
    quiet = research.tick()
    assert quiet["jobs_closed"] == [] and quiet["ran"] == [] and quiet["generations_started"] == []
    assert job(research, job_id).state == "WAITING_FOR_EVALUATION"

    research.clock.at = row.deadline_at
    assert research.tick()["jobs_closed"] == [str(job_id)]
    row = job(research, job_id)
    assert (row.state, row.close_decision) == ("CLOSED", "expired")
    (deliverable,) = research.db.rows("SELECT * FROM deliverables WHERE job_id = :j", j=job_id)
    assert deliverable.status == "best_effort"
    items = deliverable.document["items"]
    assert items and all(item["tier_reached"] is None for item in items)
    assert len(items) <= brief()["deliverable"]["max_candidates"]


# The cadence -----------------------------------------------------------------------------


def report(kind, status=None):
    """The two fields of a released report the cadence reads."""
    return SimpleNamespace(content=SimpleNamespace(type=kind, status=status))


@pytest.mark.parametrize(
    ("reports", "done"),
    [
        ([], False),
        ([report("intake", "PASS")], False),
        ([report("intake", "PASS"), report("screening", "PASS")], False),
        ([report("intake", "PASS"), report("screening", "PASS"), report("w1")], True),
        ([report("intake", "PASS"), report("screening", "FAIL")], True),
        ([report("intake", "FAIL")], True),
        ([report("intake", "DUPLICATE")], True),
        ([report("intake", "DEFERRED")], True),  # a quota deferral counts as an answer
    ],
)
def test_a_version_is_answered_by_a_refusal_a_deferral_a_failed_screening_or_w1(reports, done):
    assert answered(reports) is done


def test_the_next_generation_is_due_at_once_or_after_the_max_wait(research):
    monitor = research.worker.monitor
    at = datetime(2026, 1, 5, 1, tzinfo=UTC)
    charter = {"cadence": {"after_feedback_complete": True, "max_wait_hours": 6}}
    assert monitor.next_start(charter, at, waiting=0, failed=False) == at
    assert monitor.next_start(charter, at, waiting=3, failed=False) == at + timedelta(hours=6)
    # A failed generation always waits the full time, even with nothing published.
    assert monitor.next_start(charter, at, waiting=0, failed=True) == at + timedelta(hours=6)


def test_the_next_generation_starts_once_the_feedback_is_complete(research, monkeypatch):
    job_id = submit(research)
    # No seeds: the first generation is due at once.
    assert job(research, job_id).next_generation_at == research.clock.now()
    assert research.tick()["ran"][0]["state"] == "CLOSED"
    published = [
        r.version_id for r in research.db.rows("SELECT version_id FROM candidate_versions")
    ]
    assert published
    row = job(research, job_id)
    assert row.next_generation_at == research.clock.now() + timedelta(hours=6)
    scheduled = [e.payload for e in events(research, job_id) if e.kind == "generation_scheduled"]
    assert scheduled[-1]["awaiting_versions"] == len(published)

    # Nothing is answered yet, then all but one version: no generation starts.
    answers: dict = {}
    feedback = research.worker.monitor.env.feedback

    def reports(**params):
        if "version_id" in params:
            return SimpleNamespace(items=answers.get(params["version_id"], []))
        return ReportPage(items=[], next_after_id=None)

    monkeypatch.setattr(feedback, "reports", reports)
    assert research.tick()["generations_started"] == []
    w1 = [report("intake", "PASS"), report("screening", "PASS"), report("w1")]
    answers.update({version_id: w1 for version_id in published[:-1]})
    assert research.tick()["generations_started"] == []

    # The last version's answer completes the feedback: generation 2 starts before the
    # max wait is over.
    answers[published[-1]] = [report("intake", "DEFERRED")]
    assert len(research.tick()["generations_started"]) == 1
    assert research.clock.now() < row.next_generation_at


def test_without_feedback_the_next_generation_starts_after_the_max_wait(research):
    job_id = submit(research)
    research.tick()
    due = job(research, job_id).next_generation_at
    research.clock.at = due - timedelta(seconds=1)
    assert research.tick()["generations_started"] == []
    research.clock.at = due
    assert len(research.tick()["generations_started"]) == 1


# The queue -------------------------------------------------------------------------------


class Flaky(GenerationRunner):
    """Fails its first `failures` runs, as a worker crash inside a generation would."""

    def __init__(self, env, monitor, failures):
        super().__init__(env, monitor)
        self.failures = failures

    async def run(self, generation_id):
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("scripted worker failure")
        return await super().run(generation_id)


def flaky_worker(research, failures):
    worker = Worker(research.env, "test-flaky-worker")
    worker.runner = Flaky(research.env, worker.monitor, failures)
    return worker


def test_a_failed_attempt_is_retried_after_the_backoff_and_resumes(research):
    submit(research)
    worker = flaky_worker(research, failures=1)
    first = asyncio.run(worker.tick())
    assert first["ran"][0]["state"] == "RETRY"
    (row,) = research.db.rows("SELECT * FROM queue_jobs")
    backoff = research.config.service.worker.retry_backoff_seconds
    assert row.state == "queued" and row.attempts == 1
    assert row.run_after == research.clock.now() + timedelta(seconds=backoff[0])
    assert "scripted worker failure" in row.last_error
    assert asyncio.run(worker.tick())["ran"] == []  # not before the backoff
    research.clock.advance(seconds=backoff[0])
    second = asyncio.run(worker.tick())
    assert second["ran"][0]["state"] == "CLOSED"
    (row,) = research.db.rows("SELECT * FROM queue_jobs")
    assert row.state == "done" and row.attempts == 2


def test_the_last_failed_attempt_fails_the_generation_and_schedules_the_next(research):
    job_id = submit(research)
    worker = flaky_worker(research, failures=99)
    cfg = research.config.service.worker
    states = []
    for attempt in range(cfg.max_attempts):
        states.append(asyncio.run(worker.tick())["ran"][0]["state"])
        if attempt < cfg.max_attempts - 1:
            research.clock.advance(seconds=cfg.retry_backoff_seconds[attempt])
    assert states == ["RETRY"] * (cfg.max_attempts - 1) + ["FAILED"]
    (row,) = research.db.rows("SELECT * FROM queue_jobs")
    assert row.state == "failed" and row.attempts == cfg.max_attempts
    (generation,) = research.db.rows("SELECT * FROM generations WHERE seq = 1")
    assert generation.state == "FAILED" and "RuntimeError" in generation.error_code
    # A failed generation counts toward the cap; the job carries on with the next one.
    assert job(research, job_id).state == "RUNNING"
    assert job(research, job_id).next_generation_at is not None
    assert "generation_scheduled" in [e.kind for e in events(research, job_id)]


def test_an_expired_lease_returns_the_generation_to_the_queue(research):
    submit(research)
    assert research.worker.monitor.tick().started
    with research.db.transaction() as conn:
        assert queue.claim(conn, research.clock, "a-worker-that-died") is not None
    assert research.tick()["ran"] == []  # the lease still holds
    research.clock.advance(seconds=research.config.service.worker.lease_seconds + 1)
    result = research.tick()
    assert result["stale_requeued"] == 1
    assert result["ran"][0]["state"] == "CLOSED"
    (row,) = research.db.rows("SELECT * FROM queue_jobs")
    assert row.state == "done" and row.attempts == 2


def test_enqueue_is_idempotent_by_key(research):
    with research.db.transaction() as conn:
        first = queue.enqueue(conn, research.clock, "generation", "test-key", {"n": 1})
        again = queue.enqueue(conn, research.clock, "generation", "test-key", {"n": 2})
    assert first is not None and again is None
    (row,) = research.db.rows("SELECT * FROM queue_jobs")
    assert row.payload == {"n": 1}


# The probe -------------------------------------------------------------------------------


def test_the_setup_probe_checks_every_model_roles_name(research):
    report = asyncio.run(run_probe(research.env, "setup"))
    assert report.ok and report.trigger == "setup"
    refs = {f"{m.provider}/{m.model_id}" for m in report.models}
    assert refs == {str(r) for role in report.roles for r in research.env.planner.chain(role)}
    for model in report.models:
        assert model.checks["price"] == "pass" and model.checks["tool_output"] == "pass"
        assert model.checks["json_object"] == "pass", model
    kimi = [m for m in report.models if m.provider == "kimi"]
    assert kimi and all(m.checks["balance"] == "pass" for m in kimi)
    stored = research.db.rows("SELECT * FROM llm_probes")
    assert [(r.trigger, r.ok) for r in stored] == [("setup", True)]
    # Probe calls are paid and recorded under the role "probe", outside any job.
    probes = research.db.rows("SELECT * FROM budget_ledger WHERE role = 'probe'")
    assert len(probes) == 2 * len(report.models)
    assert all(r.job_id is None and r.cost_cny > 0 for r in probes)


def test_a_model_without_a_price_is_never_called(research):
    """The shipped providers.yaml has no prices: the probe fails every model without
    sending one request (the no-price-no-run rule)."""
    shipped = replace(research.env, config=ResearchConfig.load(Path("configs")))
    report = asyncio.run(run_probe(shipped, "setup"))
    assert not report.ok
    for model in report.models:
        assert model.checks["price"] == "fail" and model.detail["skipped_reason"] == "no price"
        assert model.checks["tool_output"] == "skipped"
    assert research.script.calls == []
    assert research.db.scalar("SELECT count(*) FROM budget_ledger") == 0


def test_a_failing_primary_leaves_the_role_usable_through_its_fallbacks(research):
    research.script.failing.add("glm/glm-5.3-flash")
    research.script.balance = {"available_balance": 0}
    report = asyncio.run(run_probe(research.env, "manual"))
    assert not report.ok
    engineer = report.roles["engineer"]
    assert engineer.primary == "glm/glm-5.3-flash" and not engineer.primary_ok
    assert engineer.usable == ["deepseek/deepseek-flash"]  # kimi has no balance
    (glm,) = [m for m in report.models if m.model_id == "glm-5.3-flash"]
    assert glm.checks["tool_output"] == "fail" and glm.checks["json_object"] == "fail"
    assert all(
        m.checks["balance"] == "fail" and not m.ok for m in report.models if m.provider == "kimi"
    )
    assert report.roles["supervisor"].ok
