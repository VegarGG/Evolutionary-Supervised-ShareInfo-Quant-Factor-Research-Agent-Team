from datetime import date

import polars as pl
import pytest
from qfr_core.contracts.execution import RunnerOutput
from qfr_core.runner_tables import pack_table
from qfr_eval.screening.coverage import RequiredTable, check_coverage


def example(values, *, kind="factor"):
    frame = pl.DataFrame(
        {
            "date": [date(2020, 1, 1)] * 2 + [date(2020, 1, 2)] * 2,
            "code": ["a", "b", "a", "b"],
            "score": values,
        },
        schema_overrides={"score": pl.Float64},
    )
    rule = RequiredTable(frame.select("date", "code"), ("date", "code"), ("score",), ("score",))
    return (
        frame,
        rule,
        RunnerOutput(schema_version="1", kind=kind, tables={"output": pack_table(frame)}),
    )


@pytest.mark.parametrize("mode", ["missing_row", "null_score", "missing_table"])
def test_every_original_eligible_observation_is_required(mode):
    frame, rule, output = example([1.0, 2.0, 3.0, 4.0])
    if mode == "missing_row":
        frame = frame.head(3)
    elif mode == "null_score":
        frame = frame.with_columns(
            pl.when(pl.col("code") == "a").then(None).otherwise(pl.col("score")).alias("score")
        )
    tables = {"wrong" if mode == "missing_table" else "output": pack_table(frame)}
    output = RunnerOutput(schema_version="1", kind="factor", tables=tables)
    result = check_coverage(output, {"output": rule}, fixed_position_strategy=False)
    assert result.status == "insufficient_data"
    assert result.required_observations == 4
    assert result.complete_observations < 4
    assert result.reason_codes == ["LOW_COVERAGE"]


def test_only_completely_constant_scorers_fail_and_near_constants_are_not_new_thresholds():
    _, rule, flat = example([1.0, 1.0, 2.0, 2.0])
    assert check_coverage(flat, {"output": rule}, fixed_position_strategy=False).reason_codes == [
        "DEGENERATE"
    ]
    _, _, partial = example([1.0, 1.0, 2.0, 3.0])
    result = check_coverage(partial, {"output": rule}, fixed_position_strategy=False)
    assert result.status == "passed" and result.diagnostics == ["some_constant_cross_sections"]
    assert result.scored_cross_sections == 2 and result.constant_cross_sections == 1
    _, _, tiny = example([1.0, 1.0 + 1e-14, 2.0, 2.0 + 1e-14])
    result = check_coverage(tiny, {"output": rule}, fixed_position_strategy=False)
    assert result.status == "passed" and result.constant_cross_sections == 0


def test_fixed_strategy_exemption_cannot_exempt_a_factor():
    _, rule, strategy = example([0.5, 0.5, 0.5, 0.5], kind="strategy")
    result = check_coverage(strategy, {"output": rule}, fixed_position_strategy=True)
    assert result.status == "passed" and result.fixed_position_exempt
    _, _, factor = example([0.5, 0.5, 0.5, 0.5])
    result = check_coverage(factor, {"output": rule}, fixed_position_strategy=True)
    assert result.status == "failed" and not result.fixed_position_exempt


def test_duplicate_keys_empty_eligibility_and_missing_scoring_spec_cannot_pass():
    frame, rule, output = example([1.0, 2.0, 3.0, 4.0])
    bad = RunnerOutput(
        schema_version="1",
        kind="factor",
        tables={"output": pack_table(pl.concat([frame, frame.head(1)]))},
    )
    assert check_coverage(bad, {"output": rule}, fixed_position_strategy=False).status == "failed"
    empty = RequiredTable(
        frame.select("date", "code").head(0), rule.keys, rule.finite_columns, rule.score_columns
    )
    assert (
        check_coverage(output, {"output": empty}, fixed_position_strategy=False).status
        == "insufficient_data"
    )
    no_score = RequiredTable(rule.eligible_keys, rule.keys, (), ())
    assert (
        check_coverage(output, {"output": no_score}, fixed_position_strategy=False).status
        == "insufficient_data"
    )
    bad_spec = RequiredTable(rule.eligible_keys, rule.keys, (), ("score",))
    with pytest.raises(ValueError, match="finite"):
        check_coverage(output, {"output": bad_spec}, fixed_position_strategy=False)


def test_coverage_checks_all_declared_cycles_not_only_weekly():
    _, rule, first = example([1.0, 2.0, 3.0, 4.0])
    _, _, missing = example([None, 2.0, 3.0, 4.0])
    value = RunnerOutput(
        schema_version="1",
        kind="model",
        tables={
            "weekly": first.tables["output"],
            "monthly": missing.tables["output"],
            "quarterly": first.tables["output"],
        },
    )
    required = {cycle: rule for cycle in ("weekly", "monthly", "quarterly")}
    result = check_coverage(value, required, fixed_position_strategy=False)
    assert result.status == "insufficient_data"
    assert result.required_observations == 12 and result.complete_observations == 11
