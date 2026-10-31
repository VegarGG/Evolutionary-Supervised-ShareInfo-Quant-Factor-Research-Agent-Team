"""Research's reading of a released W1 report against the public gates, which decides the
w1_pass tier research claims (Section 13.4). For a strategy it mirrors the strategy gate
(P6.5): HIGH_DRAWDOWN fails it even when the rounded drawdown bucket sits on the gate,
and turnover and coverage, which are factor gates, do not."""

from pathlib import Path

import yaml
from qfr_core.contracts import W1Content
from qfr_research.monitor import read_w1

GATES = yaml.safe_load(Path("configs/protocols/cn_csi300_daily_v1.yaml").read_text())["gates"]


def w1(**overrides):
    body = {
        "type": "w1",
        "rankic_mean": 0.04,
        "rankic_ir": 0.3,
        "nw_t_bucket": "above_3",
        "hit_ratio": 0.55,
        "decay_profile": {"1": 0.04, "5": 0.03},
        "ls_net_sharpe": 1.0,
        "monotonicity": 0.9,
        "top_turnover": 0.3,
        "rank_autocorrelation": 0.8,
        "max_library_correlation": None,
        "library_version_id": None,
        "library_empty": True,
        "yearly_rankic": {"2021": 0.04},
        "coverage_bucket": "PASS",
        "size_neutral_rankic": None,
        "complexity": 4,
        "flags": [],
        "strategy_net_sharpe": 1.0,
        "strategy_ir": 0.88,
        "strategy_drawdown_bucket": 0.25,
    }
    return W1Content.model_validate(body | overrides)


def passed(kind, content):
    return all(c["passed"] for c in read_w1(kind, 1, content, GATES).values())


def test_a_strategy_reading_mirrors_the_strategy_gate():
    assert passed("strategy", w1())
    # The bucket rounds to the gate, the flag says the drawdown is above it.
    flagged = w1(flags=["HIGH_DRAWDOWN", "COST_DOMINATED"])
    checks = read_w1("strategy", 1, flagged, GATES)
    assert checks["flags"] == {"value": ["HIGH_DRAWDOWN"], "passed": False}
    assert checks["strategy_drawdown"]["passed"] is True
    assert not passed("strategy", w1(flags=["WEAK_SIGNAL"]))
    assert not passed("strategy", w1(strategy_ir=0.48))
    # Turnover and coverage are factor gates, not strategy gates.
    assert passed("strategy", w1(flags=["HIGH_TURNOVER"], coverage_bucket="FAIL"))


def test_a_factor_reading_keeps_the_factor_flags():
    assert passed("factor", w1())
    assert not passed("factor", w1(flags=["HIGH_TURNOVER"]))
    assert not passed("factor", w1(coverage_bucket="FAIL"))
    assert passed("factor", w1(flags=["COST_DOMINATED", "HIGH_DRAWDOWN"]))
