"""EVL-04: re-running an official record with its pinned inputs reproduces its hash."""

from uuid import UUID

import pytest
from qfr_core.operators import evaluate
from qfr_eval.compute import InlineRunner
from qfr_eval.configs import EvalError
from qfr_eval.reproduce import reproduce
from qfr_eval.runtime import eval_config
from qfr_eval.worker import Evaluator, MarketCache

from tests.registry_rig import factor_manifest

pytestmark = pytest.mark.postgres


def test_evl_04_rerunning_official_records_reproduces_their_results_hash(rig):
    for name, expression in (("first", "Pct($close, 20)"), ("second", "Corr($close, $volume, 10)")):
        rig.registry.publish(factor_manifest(name, expression))
    rig.cycle()
    records = rig.db.rows(
        "SELECT record_id, stage, results_hash FROM eval.official_records ORDER BY created_at"
    )
    assert {r.stage for r in records} == {"screening", "w1"}
    evaluator = Evaluator(rig.env, InlineRunner(), MarketCache(rig.env.full_snapshot_dir))
    config = eval_config(rig.env.config_dir)
    for record in records:
        result = reproduce(rig.db, rig.env, config, record.record_id, evaluator)
        assert result["match"] is True, result
        assert result["actual_results_hash"] == record.results_hash
    # The second W1 record saw the first as library: the pinned library files are re-read.
    second = rig.db.rows(
        "SELECT summary FROM eval.official_records WHERE stage = 'w1' ORDER BY created_at"
    )[-1].summary
    assert second["library"]["size"] == 0 or second["library"]["members"]


def test_reproduce_detects_a_changed_input_and_unknown_records(rig):
    rig.registry.publish(factor_manifest("only", "Pct($close, 20)"))
    rig.cycle()
    record = rig.db.rows("SELECT record_id FROM eval.official_records WHERE stage = 'w1'")[0]

    def flipped(panel, tree, eligibility):
        return -evaluate(panel, tree, eligibility)  # ranks reverse, so the metrics change

    evaluator = Evaluator(rig.env, InlineRunner(flipped), MarketCache(rig.env.full_snapshot_dir))
    result = reproduce(rig.db, rig.env, eval_config(rig.env.config_dir), record.record_id,
                       evaluator)  # fmt: skip
    assert result["match"] is False
    with pytest.raises(EvalError, match="no official record"):
        reproduce(rig.db, rig.env, eval_config(rig.env.config_dir),
                  UUID(int=1), evaluator)  # fmt: skip
