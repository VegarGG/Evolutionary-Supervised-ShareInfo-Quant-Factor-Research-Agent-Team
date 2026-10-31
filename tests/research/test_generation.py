"""A first scripted generation against research_db and registry-api (no evaluator)."""

import pytest
from qfr_core.contracts import ResearchBrief
from qfr_core.research_api import BriefScan
from qfr_research.jobs import JobService

from tests.research.rig import brief, research_only
from tests.research.scripted import Script

pytestmark = pytest.mark.postgres

REVERSAL = ("-Delta($close, 5) / Ref($close, 5)", 1)
MOMENTUM = ("Mean($close, 5) / Mean($close, 20) - 1", 1)


def scan() -> BriefScan:
    return BriefScan(
        status="passed", scanner="qfr-mcp", referenced_version_ids=[], numbers_in_text=0,
        values_compared=0,
    )  # fmt: skip


@pytest.fixture
def rig(tmp_path, small_zones):
    with research_only(tmp_path, small_zones, Script([REVERSAL, MOMENTUM])) as (registry, built):
        yield registry, built


def test_one_scripted_generation_publishes_traced_candidates(rig):
    registry, research = rig
    submitted = JobService(research.api_env).submit(
        ResearchBrief.model_validate(brief()), scan(), "control"
    )
    assert submitted.created and submitted.job.state == "RUNNING"
    result = research.tick()
    assert result["ran"] and result["ran"][0]["state"] == "CLOSED", result
    roles = research.script.roles()
    assert {"supervisor", "hypothesis", "engineer", "critic"} <= set(roles), roles
    published = research.db.rows("SELECT * FROM candidate_versions")
    assert published, research.db.rows("SELECT state, reason FROM candidates")
