"""TRC-01 and TRC-02 (INV-13): the packager refuses an incomplete trace, and every LLM step
can be reconstructed from its agent run and matches a log line."""

import hashlib
import json

import pytest
from qfr_core.contracts import ResearchBrief
from qfr_core.ids import uuid7
from qfr_research.jobs import JobService
from qfr_research.packager import Packager
from qfr_research.store import Ctx

from tests.research.rig import brief, research_only
from tests.research.scripted import Script
from tests.research.test_generation import scan

pytestmark = pytest.mark.postgres

# Test data on the planted synthetic world; not a product default.
REVERSAL = ("-Delta($close, 5) / Ref($close, 5)", 1)
SECOND = ("Mean($close, 5) / Mean($close, 20) - 1", 1)


@pytest.fixture
def generated(tmp_path, small_zones):
    """One scripted generation that publishes at least one candidate."""
    with research_only(tmp_path, small_zones, Script([REVERSAL, SECOND])) as (_, research):
        JobService(research.api_env).submit(
            ResearchBrief.model_validate(brief()), scan(), "control"
        )
        result = research.tick()
        assert result["ran"] and result["ran"][0]["state"] == "CLOSED", result
        yield research


def copy_candidate(research, *, operator=None, without=()):
    """A selected copy of a published candidate under a new id, with the candidate's trace
    steps copied too except the step types in `without`."""
    source = research.db.rows(
        "SELECT c.* FROM candidates c JOIN candidate_versions v USING (candidate_id) LIMIT 1"
    )[0]
    copy_id = uuid7()
    with research.db.transaction() as conn:
        columns = [
            name
            for (name,) in conn.exec_driver_sql(
                "SELECT column_name FROM information_schema.columns WHERE table_name = "
                "'candidates' ORDER BY ordinal_position"
            )
        ]
        replaced = {
            "candidate_id": "%(n)s",
            "state": "'selected'",
            "reason": "NULL",
            "operator": "coalesce(%(o)s, operator)",
        }
        conn.exec_driver_sql(
            f"INSERT INTO candidates ({', '.join(columns)}) SELECT "
            f"{', '.join(replaced.get(c, c) for c in columns)} FROM candidates "
            "WHERE candidate_id = %(c)s",
            {"n": copy_id, "o": operator, "c": source.candidate_id},
        )
        steps = conn.exec_driver_sql(
            "SELECT * FROM trace_steps WHERE candidate_id = %(c)s",
            {"c": source.candidate_id},
        ).mappings()
        for step in list(steps):
            if step["step_type"] in without or step["step_type"] in ("TRACE_CHECKED", "PUBLISHED"):
                continue
            row = dict(step) | {"step_id": uuid7(), "candidate_id": copy_id}
            row["inputs"], row["payload"] = json.dumps(row["inputs"]), json.dumps(row["payload"])
            columns = ", ".join(row)
            values = ", ".join(f"%({k})s" for k in row)
            conn.exec_driver_sql(f"INSERT INTO trace_steps ({columns}) VALUES ({values})", row)
    return source, copy_id


def publish(research, source, candidate_id):
    ctx = Ctx(
        job_id=research.db.scalar(
            "SELECT job_id FROM programs WHERE program_id = :p", p=source.program_id
        ),
        program_id=source.program_id,
        generation_id=source.generation_id,
    )
    return Packager(research.env).publish(ctx, candidate_id)


def test_trc_01_publication_is_refused_when_a_required_step_is_missing(generated):
    research = generated
    published_before = research.db.scalar("SELECT count(*) FROM candidate_versions")
    source, copy_id = copy_candidate(research, without=("CRITIC_REVIEWED",))

    assert publish(research, source, copy_id) is None
    (check,) = research.steps(candidate_id=copy_id, step_type="TRACE_CHECKED")
    assert check.outcome == "failed" and check.actor == "packager"
    assert check.payload["missing"] == ["candidate:CRITIC_REVIEWED"]
    state = research.db.rows(
        "SELECT state, reason FROM candidates WHERE candidate_id = :c", c=copy_id
    )[0]
    assert (state.state, state.reason) == ("not_selected", "TRACE_INCOMPLETE")
    assert research.db.scalar("SELECT count(*) FROM candidate_versions") == published_before
    assert not research.steps(candidate_id=copy_id, step_type="PUBLISHED")
    refused = [
        line for line in research.logs("research-worker")
        if line.get("event") == "publication_refused" and line.get("candidate_id") == str(copy_id)
    ]  # fmt: skip
    assert refused and refused[0]["level"] == "WARNING"
    assert refused[0]["error_code"] == "TRACE_INCOMPLETE"


def test_trc_01_the_required_steps_depend_on_the_operator(generated):
    """The same explore trace is incomplete for a mutation: the parent selection, the
    applied operator and the lineage parents are missing."""
    research = generated
    source, copy_id = copy_candidate(research, operator="llm_mutation")
    assert publish(research, source, copy_id) is None
    (check,) = research.steps(candidate_id=copy_id, step_type="TRACE_CHECKED")
    assert set(check.payload["missing"]) == {
        "lineage:PARENT_SELECTED",
        "candidate:MUTATION_APPLIED",
        "lineage:parents",
    }


def test_trc_01_a_complete_trace_was_checked_before_each_publication(generated):
    research = generated
    for row in research.db.rows("SELECT candidate_id FROM candidate_versions"):
        steps = research.steps(candidate_id=row.candidate_id)
        kinds = [s.step_type for s in steps]
        assert kinds.index("TRACE_CHECKED") < kinds.index("PUBLISHED"), kinds
        (check,) = [s for s in steps if s.step_type == "TRACE_CHECKED"]
        assert check.outcome == "ok" and check.payload["missing"] == []


def test_trc_02_every_llm_step_has_a_full_agent_run_and_a_log_line(generated):
    research = generated
    runs = research.db.rows("SELECT * FROM agent_runs ORDER BY created_at")
    assert {r.role for r in runs} >= {"supervisor", "hypothesis", "engineer", "critic"}
    lines = {
        line["run_id"]: line
        for line in research.logs("research-worker")
        if line.get("event") == "llm_call_completed"
    }
    responded = research.steps(step_type="MODEL_RESPONDED")
    assert len(responded) == len(runs)
    by_run = {step.run_id: step for step in responded}
    for run in runs:
        # The full request: the first user prompt is the rendered prompt that was hashed.
        prompts = [
            part["content"]
            for message in run.request_messages
            if message.get("kind") == "request"
            for part in message["parts"]
            if part.get("part_kind") == "user-prompt"
        ]
        assert prompts, run.run_id
        assert hashlib.sha256(prompts[0].encode()).hexdigest() == run.prompt_sha256
        # The full response: the model's answer is stored as text and as parsed output.
        assert run.response_text and run.status == "ok"
        assert run.response_json is not None
        assert run.usage["tokens_in"] > 0 and run.usage["cost_cny"] > 0
        # The trace step and the log line carry the same run id.
        step = by_run[run.run_id]
        assert step.step_id == run.step_id and step.actor == run.role
        assert step.prompt_sha256 == run.prompt_sha256 and step.model_id == run.model_id
        line = lines[str(run.run_id)]
        assert line["step_id"] == str(run.step_id)
        assert line["payload"]["role"] == run.role
        assert line["payload"]["prompt_sha256"] == run.prompt_sha256
