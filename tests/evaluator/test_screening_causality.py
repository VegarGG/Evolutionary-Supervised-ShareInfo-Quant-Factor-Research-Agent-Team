"""Trusted math fixtures exercise screening logic; these are not isolation proof."""

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from qfr_core.contracts.execution import RunnerInput, RunnerOutput
from qfr_core.runner_tables import pack_table, unpack_table
from qfr_eval.backtest.prefix import CausalOutput
from qfr_eval.sandbox.runner import ExecutionResult, SandboxUnavailable, decode_result
from qfr_eval.screening.causality import perturb_future, run_probes
from qfr_eval.screening.models import ScreeningExecutionPolicy
from qfr_eval.screening.static import check_source

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def execution_policy():
    return ScreeningExecutionPolicy.model_validate_json(
        (ROOT / "configs/evaluation/screening_execution_v1.json").read_bytes()
    )


@pytest.fixture
def prices():
    frame = pl.DataFrame(
        {
            "date": [date(2020, 1, day) for day in range(1, 7)],
            "code": ["a"] * 6,
            "close": [1.0, 2.0, 4.0, 8.0, 16.0, 32.0],
        }
    )
    return RunnerInput(schema_version="1", seed=123, tables={"prices": pack_table(frame)})


def projected(value, request):
    frame = unpack_table(value.tables["output"])
    return {
        "output": CausalOutput(
            frame.with_columns(pl.col("date").alias("_available_date")), ("date", "code")
        )
    }


def math_fixture(mode):
    counter = 0

    def execute(request):
        nonlocal counter
        counter += 1
        frame = unpack_table(request.tables["prices"])
        expression = (
            pl.col("close").shift(1)
            if mode == "causal"
            else pl.lit(frame["close"].mean())
            if mode == "lookahead"
            else pl.lit(float(counter))
        )
        output = RunnerOutput(
            schema_version="1",
            kind="factor",
            tables={"output": pack_table(frame.select("date", "code", expression.alias("score")))},
        )
        return decode_result(
            json.dumps({"code": "ok", "output": output.model_dump(mode="json")}).encode(), 65536
        )

    return execute


def test_causal_output_preserves_null_warmup_and_passes_both_probes(prices, execution_policy):
    result, output = run_probes(
        prices,
        math_fixture("causal"),
        projected,
        [date(2020, 1, 2), date(2020, 1, 4)],
        execution_policy,
        atol=1e-12,
        rtol=1e-12,
    )
    assert result.status == "passed" and result.deterministic
    assert result.prefix_passed and result.perturbation_passed
    assert len(result.prefix) == len(result.perturbation) == 2
    assert output.tables["output"].rows[0][2] is None


def test_planted_full_future_mean_fails_prefix_and_perturbation(prices, execution_policy):
    result, _ = run_probes(
        prices,
        math_fixture("lookahead"),
        projected,
        [date(2020, 1, 3)],
        execution_policy,
        atol=1e-12,
        rtol=1e-12,
    )
    assert result.status == "failed" and result.code == "failed:lookahead"
    assert result.prefix_passed is False and result.perturbation_passed is False


def test_nondeterminism_is_not_rounded_into_a_pass(prices, execution_policy):
    result, _ = run_probes(
        prices,
        math_fixture("nondeterministic"),
        projected,
        [date(2020, 1, 3)],
        execution_policy,
        atol=1e-12,
        rtol=1e-12,
    )
    assert result.code == "failed:nondeterministic" and result.deterministic is False
    assert result.prefix_passed is result.perturbation_passed is None


def test_perturbation_changes_only_future_float_values_and_preserves_keys(prices, execution_policy):
    original = unpack_table(prices.tables["prices"])
    actual, changed = perturb_future({"prices": original}, date(2020, 1, 3), execution_policy)
    assert changed == 3
    assert actual["prices"].head(3).equals(original.head(3))
    assert actual["prices"].select("date", "code").equals(original.select("date", "code"))
    assert actual["prices"]["close"].tail(3).to_list() == [7.0, 14.0, 28.0]


def test_no_future_values_or_empty_comparisons_cannot_pass(prices, execution_policy):
    for cutoff in (date(2020, 1, 6), date(2019, 12, 31)):
        result, _ = run_probes(
            prices,
            math_fixture("causal"),
            projected,
            [cutoff],
            execution_policy,
            atol=1e-12,
            rtol=1e-12,
        )
        assert result.status == "insufficient_data"


@pytest.mark.parametrize("backend_unavailable", [True, False])
def test_execution_failures_never_become_success(prices, execution_policy, backend_unavailable):
    def execute(request):
        if backend_unavailable:
            raise SandboxUnavailable("no usable backend")
        return ExecutionResult("failed:timeout", None, None, {})

    result, output = run_probes(
        prices, execute, projected, [date(2020, 1, 3)], execution_policy, atol=1e-12, rtol=1e-12
    )
    assert result.status == "failed" and output is None
    assert result.code == (
        "failed:backend_unavailable" if backend_unavailable else "failed:timeout"
    )


def test_static_checks_accept_frozen_sources_and_reject_unsafe_constructs(execution_policy):
    for name in ("generic.py", "pilot.py"):
        assert (
            check_source(
                (ROOT / "fixtures/artifacts/runners" / name).read_bytes(),
                execution_policy,
                constrained_factor=False,
            )
            is None
        )
    for source in (
        b"import socket",
        b"from os import system",
        b"eval('1')",
        b"x.__class__.__mro__",
        b"np.load('x',allow_pickle=True)",
        b"from qfr_core import *",
        b"from .local import hidden",
    ):
        assert (
            check_source(source, execution_policy, constrained_factor=False).value
            == "FORBIDDEN_CONSTRUCT"
        )
    assert (
        check_source(b'x["code"]', execution_policy, constrained_factor=True).value
        == "FORBIDDEN_CONSTRUCT"
    )
    assert check_source(b'x["code"]', execution_policy, constrained_factor=False) is None
    assert (
        check_source(b"def invalid(", execution_policy, constrained_factor=False).value
        == "PARSE_ERROR"
    )


def test_failed_determinism_rerun_keeps_first_output_hash_for_failed_trial(
    prices, execution_policy
):
    first = math_fixture("causal")(prices)
    calls = iter([first, ExecutionResult("failed:timeout", None, None, {})])
    result, output = run_probes(
        prices,
        lambda _: next(calls),
        projected,
        [date(2020, 1, 3)],
        execution_policy,
        atol=1e-12,
        rtol=1e-12,
    )
    assert result.status == "failed" and result.code == "failed:timeout"
    assert output == first.output and result.output_sha256 == first.output_sha256
