"""The evolution engine against research_db (Phase 5, P5.1, P5.2 and P5.6).

A first scripted generation starts from an empty population (SET-01) and its
publications join as provisional members. Released reports written into research's
report cache then drive the refresh directly: a published member waiting for evaluation
(a quota deferral included) stays provisional however many generations pass, a released
W1 report makes it official with Section 12.2 fitness and MAP-Elites descriptors, a
failed screening archives it as a repair target, a quota expiry removes it without
counting a failure, each published child counts once in its island's bandit arm, the
archive keeps the elite, and every 5 generations an island's best migrates along the
ring. The proposal is a pure function of the stored state and the recorded seeds.
"""

import hashlib
import json
from typing import Any
from uuid import UUID

import pytest
from qfr_core.contracts import ResearchBrief
from qfr_core.ids import uuid7
from qfr_research.db import dumps
from qfr_research.engine import EvolutionEngine, GenerationRef
from qfr_research.jobs import JobService
from qfr_research.variation import derive_seed
from sqlalchemy import text

from tests.research.rig import brief, research_only
from tests.research.scripted import Script
from tests.research.test_generation import scan

pytestmark = pytest.mark.postgres

# Test data on the planted synthetic world; not a product default.
REVERSAL = ("-Delta($close, 5) / Ref($close, 5)", 1)
HIGH_SLOPE = ("Slope($high, 5)", -1)


@pytest.fixture
def first(tmp_path, small_zones):
    script = Script([REVERSAL, HIGH_SLOPE])
    with research_only(tmp_path, small_zones, script) as (_, research):
        submitted = JobService(research.api_env).submit(
            ResearchBrief.model_validate(brief(islands=["I1", "I2"])), scan(), "control"
        )
        result = research.tick()
        assert result["ran"] and result["ran"][0]["state"] == "CLOSED", result
        yield research, submitted.job.job_id


def generation_ref(research: Any, job_id: UUID, seq: int, **charter: Any) -> GenerationRef:
    row = research.db.rows(
        "SELECT g.generation_id, g.program_id, p.charter FROM generations g JOIN programs p ON "
        "p.program_id = g.program_id JOIN research_jobs j ON j.job_id = p.job_id WHERE "
        "j.job_id = :j AND g.seq = 1",
        j=job_id,
    )[0]
    return GenerationRef(
        row.generation_id, row.program_id, job_id, seq, dict(row.charter) | charter
    )


def release(research: Any, version_id: UUID, program_id: UUID, content: dict[str, Any]) -> None:
    """A released report as feedback sync stores it (content is the report's JSON)."""
    report = {
        "schema_version": "1",
        "report_id": str(uuid7()),
        "version_id": str(version_id),
        "program_id": str(program_id),
        "released_at": research.clock.now().isoformat(),
        "content": content,
    }
    with research.db.transaction() as conn:
        conn.execute(
            text(
                "INSERT INTO report_cache (report_id, program_id, version_id, report_type, "
                "released_at, content, content_hash, fetched_at) VALUES (:r, :p, :v, :t, :at, "
                "CAST(:c AS jsonb), :h, :at)"
            ),
            {
                "r": report["report_id"],
                "p": program_id,
                "v": version_id,
                "t": content["type"],
                "at": research.clock.now(),
                "c": dumps(report),
                "h": hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest(),
            },
        )


W1 = {
    "type": "w1",
    "rankic_mean": 0.035,
    "rankic_ir": 0.4,
    "nw_t_bucket": "above_3",
    "hit_ratio": 0.6,
    "decay_profile": {"1": 0.02, "5": 0.035, "10": 0.02, "20": 0.01},
    "ls_net_sharpe": 1.25,
    "monotonicity": 0.8,
    "top_turnover": 0.55,
    "rank_autocorrelation": 0.5,
    "max_library_correlation": None,
    "library_version_id": None,
    "library_empty": True,
    "yearly_rankic": {"2011": 0.035},
    "coverage_bucket": "PASS",
    "size_neutral_rankic": None,
    "complexity": 6,
    "flags": ["HIGH_TURNOVER"],
}
SCREENING_FAIL = {"type": "screening", "status": "FAIL", "reasons": ["LOW_COVERAGE"]}
DEFERRED = {"type": "intake", "status": "DEFERRED", "reasons": ["QUOTA_DEFERRED"]}
QUOTA_EXPIRED = {"type": "intake", "status": "FAIL", "reasons": ["QUOTA_EXPIRED"]}


def members(research: Any) -> dict[str, Any]:
    return {
        f"{r.island_key}:{r.version_id}": r
        for r in research.db.rows("SELECT * FROM population_members ORDER BY joined_seq")
    }


def test_set_01_empty_start_then_published_factors_join_as_provisional(first):
    research, job_id = first
    (init,) = [
        line
        for line in research.logs("research-worker")
        if line["event"] == "population_initialized"
    ]
    assert init["payload"]["empty_start"] is True and init["payload"]["seeds"] == 0
    (step,) = research.steps(step_type="PROPOSAL_EMITTED")
    proposal = step.payload
    assert proposal["refresh"]["members"] == {}
    assert proposal["engine"]["guardrail"]["raised"] is True  # an empty archive
    assert {t["type"] for t in proposal["default_plan"]["tasks"]} == {"explore"}
    assert proposal["parents"] == [] and proposal["variants"] == []
    published = research.db.rows(
        "SELECT v.version_id, c.island_key FROM candidate_versions v JOIN candidates c USING "
        "(candidate_id)"
    )
    assert published
    rows = members(research)
    assert len(rows) == len(published)
    for row in rows.values():
        assert row.status == "provisional" and row.source == "program"
        assert row.joined_seq == 1
        assert row.fitness is not None and row.metrics["source"] == "W0"


def test_refresh_waiting_official_fitness_screening_failure_bandit_archive_and_migration(first):
    research, job_id = first
    engine = EvolutionEngine(research.env)
    published = research.db.rows(
        "SELECT v.version_id, c.island_key, c.program_id FROM candidate_versions v JOIN "
        "candidates c USING (candidate_id) ORDER BY v.published_at"
    )
    assert len(published) >= 2, published

    # Generation 4: no W1 report yet, one version deferred by its quota. Published
    # members waiting for evaluation do not expire (Section 12.1).
    official, failed = published[0], published[1]
    release(research, official.version_id, official.program_id, DEFERRED)
    waiting = engine.refresh(generation_ref(research, job_id, 4))
    assert waiting["status_changes"] == []
    assert {r.status for r in members(research).values()} == {"provisional"}

    release(research, official.version_id, official.program_id, W1)
    release(research, failed.version_id, failed.program_id, SCREENING_FAIL)
    gen5 = generation_ref(research, job_id, 5)
    refreshed = engine.refresh(gen5)
    changes = {c["version_id"]: c for c in refreshed["status_changes"]}
    assert changes[str(official.version_id)]["to"] == "official"
    assert changes[str(failed.version_id)]["reason"] == "SCREENING_FAILED"

    rows = members(research)
    best = rows[f"{official.island_key}:{official.version_id}"]
    assert best.status == "official" and best.metrics["source"] == "W1"
    # A lone official member sits at the middle of every percentile (Section 12.2).
    assert best.fitness == pytest.approx(0.5)
    # The best decay horizon for the declared sign, turnover 0.55 in bucket 2, and a
    # price-only expression.
    horizon = 5 if best.expected_sign == 1 else 20
    assert best.descriptors == {
        "horizon": horizon,
        "turnover_bucket": 2,
        "field_group": "price_only",
        "cell_key": f"h{horizon}|t2|price_only",
    }
    lost = rows[f"{failed.island_key}:{failed.version_id}"]
    assert lost.status == "archived" and lost.fitness == 0.0
    assert lost.fitness_detail["multiplier_reasons"] == ["SCREENING_FAILED"]

    # The archive keeps the official elite; the bandit counted each child once.
    assert refreshed["archive"]["cells"] == 1 and refreshed["archive"]["total"] == 64
    outcomes = research.db.rows("SELECT * FROM bandit_outcomes ORDER BY success DESC")
    assert [(str(o.version_id), o.success) for o in outcomes] == [
        (str(official.version_id), True),
        (str(failed.version_id), False),
    ]
    again = engine.refresh(gen5)
    assert research.db.scalar("SELECT count(*) FROM bandit_outcomes") == 2
    assert all(not v["outcomes"] for v in again["bandit"].values())
    arm = again["bandit"][official.island_key]
    assert arm["alpha"] >= 2.0

    # Generation 5 is a migration generation: the best official member of each island
    # with one is copied to the next island of the ring.
    (moved,) = refreshed["migrated"]
    assert moved["version_id"] == str(official.version_id) and moved["from"] == official.island_key
    target = moved["to"]
    assert target != official.island_key
    copy = members(research)[f"{target}:{official.version_id}"]
    assert copy.source == "migrant" and copy.status == "official"

    # A screening failure for a repairable reason is a repair target.
    settings = engine.settings(gen5.charter)
    with research.db.read() as conn:
        targets = engine._repair_targets(conn, gen5, settings)
    assert [t["version_id"] for t in targets] == [str(failed.version_id)]
    assert targets[0]["reasons"] == ["LOW_COVERAGE"]


def test_the_proposal_is_reproducible_from_the_state_and_its_seeds(first):
    research, job_id = first
    engine = EvolutionEngine(research.env)
    (official, *_) = research.db.rows(
        "SELECT v.version_id, c.program_id FROM candidate_versions v JOIN candidates c USING "
        "(candidate_id) ORDER BY v.published_at"
    )
    release(research, official.version_id, official.program_id, W1)
    gen = generation_ref(research, job_id, 2)
    refresh = engine.refresh(gen)
    from decimal import Decimal

    one = engine.propose(gen, refresh, [], Decimal("30"), Decimal("0.1")).as_json()
    two = engine.propose(gen, refresh, [], Decimal("30"), Decimal("0.1")).as_json()
    assert one == two
    assert one["engine"]["bandit_seed"] == derive_seed(gen.program_id, 2, "bandit")
    assert sum(one["publication_slots"].values()) == 12
    # The member with a W1 report is offered as a parent, with the flags that target
    # its llm_mutation instructions.
    offered = one["parent_info"].get(str(official.version_id))
    if offered is not None:
        assert offered["status"] == "official" and offered["flags"] == ["HIGH_TURNOVER"]
    assert set(one["parents"]) <= {
        str(r.version_id) for r in research.db.rows("SELECT version_id FROM population_members")
    }


def test_a_quota_expiry_removes_a_member_without_counting_a_failure(first):
    research, job_id = first
    engine = EvolutionEngine(research.env)
    (version, *_) = research.db.rows(
        "SELECT v.version_id, c.program_id FROM candidate_versions v JOIN candidates c USING "
        "(candidate_id) ORDER BY v.published_at"
    )
    release(research, version.version_id, version.program_id, DEFERRED)
    release(research, version.version_id, version.program_id, QUOTA_EXPIRED)
    refreshed = engine.refresh(generation_ref(research, job_id, 2))
    (change,) = [
        c for c in refreshed["status_changes"] if c["version_id"] == str(version.version_id)
    ]
    assert (change["from"], change["to"], change["reason"]) == (
        "provisional",
        "archived",
        "QUOTA_EXPIRED",
    )
    # Never judged, so the bandit counts nothing and it is no repair target.
    assert research.db.scalar("SELECT count(*) FROM bandit_outcomes") == 0
    with research.db.read() as conn:
        gen = generation_ref(research, job_id, 2)
        assert engine._repair_targets(conn, gen, engine.settings(gen.charter)) == []


def test_a_stagnant_island_is_paused_when_too_small_to_reseed(first):
    research, job_id = first
    engine = EvolutionEngine(research.env)
    from decimal import Decimal

    # One publication slot for the whole generation: one island gets it, the other has
    # a single candidate slot, fewer than the 2 explore tasks a reseed needs.
    small = {
        "throughput": {
            "publications": 1,
            "candidate_slots_max": 3,
            "concurrency": 4,
            "review_rounds_max": 2,
            "compose_strategy_tasks_max": 0,
        }
    }
    gen = generation_ref(research, job_id, 12, **small)
    research.db.conn.execute(text("UPDATE islands SET best_seq = 1, best_fitness = NULL"))
    refresh = engine.refresh(gen)
    assert all(v["stagnant"] for v in refresh["islands"].values())
    proposal = engine.propose(gen, refresh, [], Decimal("30"), Decimal("0.1"))
    choice = proposal.engine["stagnation_choice"]
    assert sorted(choice) == ["I1", "I2"]
    paused = [p.island_id for p in proposal.default_plan.islands_to_pause]
    assert len(paused) == 1 and choice[paused[0]] == "pause"
    kept = next(k for k in choice if k not in paused)
    assert choice[kept] == "reseed"
    assert not [t for t in proposal.default_plan.tasks if t.island_id == paused[0]]
