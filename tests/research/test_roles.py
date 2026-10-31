"""Fallback chains and the cross-provider critic rule (P4.2, P4.5), with scripted models:
a primary that answers 503 is retried, then the next model in the role's chain answers,
and a critic never runs on the provider that drafted the candidate."""

import pytest
from qfr_core.contracts import ResearchBrief
from qfr_research.jobs import JobService

from tests.research.rig import brief, research_only
from tests.research.scripted import Script
from tests.research.test_generation import scan

pytestmark = pytest.mark.postgres

# Test data on the planted synthetic world; not a product default.
REVERSAL = ("-Delta($close, 5) / Ref($close, 5)", 1)
SECOND = ("Mean($close, 5) / Mean($close, 20) - 1", 1)


@pytest.mark.parametrize("failing", ["deepseek/deepseek-v4-pro", "glm/glm-5.3-flash"])
def test_a_failing_primary_falls_back_and_the_critic_avoids_the_engineers_provider(
    tmp_path, small_zones, failing
):
    script = Script([REVERSAL, SECOND], failing={failing})
    with research_only(tmp_path, small_zones, script) as (_, research):
        JobService(research.api_env).submit(
            ResearchBrief.model_validate(brief()), scan(), "control"
        )
        result = research.tick()
        assert result["ran"][0]["state"] == "CLOSED", result
        assert research.db.scalar("SELECT count(*) FROM candidate_versions") >= 1

        # Every failed attempt is an agent run and a failed step; then the chain moves on.
        failed = research.db.rows("SELECT * FROM agent_runs WHERE status = 'failed'")
        assert failed and {f"{r.provider}/{r.model_id}" for r in failed} == {failing}
        retries = research.config.providers.request["retries"]
        roles_hit = {r.role for r in failed}
        assert len(failed) >= (int(retries) + 1) * len(roles_hit)
        fallbacks = research.steps(step_type="PROVIDER_FALLBACK")
        assert fallbacks and all(s.inputs["from"] == failing for s in fallbacks)
        assert all(s.outcome == "fallback" for s in fallbacks)
        lines = [
            line for line in research.logs("research-worker")
            if line["event"] == "llm_provider_fallback"
        ]  # fmt: skip
        assert len(lines) == len(fallbacks)
        ok = research.db.rows("SELECT * FROM agent_runs WHERE status = 'ok'")
        assert not {f"{r.provider}/{r.model_id}" for r in ok} & {failing}

        # The critic never shares the engineer's provider.
        pairs = research.db.rows(
            "SELECT r.provider AS critic, e.provider AS engineer FROM reviews r "
            "JOIN candidates c USING (candidate_id) "
            "JOIN agent_runs e ON e.run_id = c.engineer_run_id"
        )
        assert pairs and all(p.critic != p.engineer for p in pairs), pairs
