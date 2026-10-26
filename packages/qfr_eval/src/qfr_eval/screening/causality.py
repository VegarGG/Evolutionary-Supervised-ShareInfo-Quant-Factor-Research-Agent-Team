"""Prefix, future perturbation and exact deterministic reruns of actual outputs."""

from collections.abc import Callable
from datetime import date

import polars as pl
from qfr_core.contracts.execution import RunnerInput, RunnerOutput
from qfr_core.data_layer.snapshots import logical_hash
from qfr_core.pilot.parity import assert_parity
from qfr_core.runner_tables import pack_table, unpack_table

from qfr_eval.backtest.prefix import CausalOutput, PrefixCheck, slice_inputs
from qfr_eval.sandbox.models import SandboxCode
from qfr_eval.sandbox.runner import ExecutionResult, SandboxUnavailable
from qfr_eval.screening.models import CausalityEvidence, ScreeningExecutionPolicy


class ExecutionFailure(RuntimeError):
    def __init__(self, code: SandboxCode):
        super().__init__(code)
        self.code = code


def perturb_future(
    tables: dict[str, pl.DataFrame], cutoff: date, policy: ScreeningExecutionPolicy
) -> tuple[dict[str, pl.DataFrame], int]:
    changed = 0
    output = {}
    for name, frame in tables.items():
        date_columns = [c for c in ("date", "available_date") if c in frame.columns]
        if not date_columns:
            output[name] = frame
            continue
        if any(frame.schema[c] != pl.Date for c in date_columns):
            raise ValueError("causality input requires canonical date columns")
        future = pl.any_horizontal([pl.col(c) > cutoff for c in date_columns]).fill_null(False)
        expressions = []
        for column, dtype in frame.schema.items():
            if dtype.is_float():
                eligible = future & pl.col(column).is_not_null() & pl.col(column).is_finite()
                changed += frame.select((eligible & (pl.col(column) != 0)).sum()).item()
                expressions.append(
                    pl.when(eligible)
                    .then(pl.col(column) * policy.future_numeric_scale)
                    .otherwise(pl.col(column))
                    .alias(column)
                )
        output[name] = frame.with_columns(expressions)
    return output, changed


def compare_projection(
    complete: dict[str, CausalOutput],
    other: dict[str, CausalOutput],
    cutoff: date,
    *,
    filter_other: bool,
    atol: float,
    rtol: float,
) -> PrefixCheck:
    if set(complete) != set(other):
        raise AssertionError("causal output table identity changed")
    cells = 0
    full_hashes, actual_hashes = {}, {}
    for name, expected_output in complete.items():
        actual_output = other[name]
        expected = expected_output.frame.filter(pl.col("_available_date") <= cutoff)
        actual = actual_output.frame
        if filter_other:
            actual = actual.filter(pl.col("_available_date") <= cutoff)
        if (
            expected_output.keys != actual_output.keys
            or expected.schema != actual.schema
            or actual["_available_date"].null_count()
            or (actual["_available_date"] > cutoff).any()
        ):
            raise AssertionError("causal schema, keys or availability changed")
        exact = [
            c
            for c in actual.columns
            if c not in actual_output.keys
            and (not actual.schema[c].is_float() or c in {"rank", "actual_rank"})
        ]
        numeric = [c for c in actual.columns if c not in actual_output.keys and c not in exact]
        cells += assert_parity(
            actual, expected, keys=actual_output.keys, columns=exact, atol=0, rtol=0
        )
        cells += assert_parity(
            actual, expected, keys=actual_output.keys, columns=numeric, atol=atol, rtol=rtol
        )
        full_hashes[name] = logical_hash(expected, expected_output.keys)
        actual_hashes[name] = logical_hash(actual, actual_output.keys)
    return PrefixCheck(
        cutoff=cutoff,
        compared_cells=cells,
        full_prefix_hashes=full_hashes,
        rebuilt_hashes=actual_hashes,
    )


def run_probes(
    request: RunnerInput,
    execute: Callable[[RunnerInput], ExecutionResult],
    project: Callable[[RunnerOutput, RunnerInput], dict[str, CausalOutput]],
    cutoffs: list[date],
    policy: ScreeningExecutionPolicy,
    *,
    atol: float,
    rtol: float,
) -> tuple[CausalityEvidence, RunnerOutput | None]:
    if not cutoffs or len(set(cutoffs)) != len(cutoffs):
        raise ValueError("explicit unique frozen cutoffs are required")
    evidence = CausalityEvidence(
        schema_version="1",
        status="insufficient_data",
        code="insufficient_data",
        output_sha256=None,
        deterministic=None,
        prefix_passed=None,
        perturbation_passed=None,
        prefix=[],
        perturbation=[],
        label=policy.lookahead_label,
    )
    full = None

    def run(value: RunnerInput) -> ExecutionResult:
        result = execute(value)
        if result.code != "ok" or result.output is None or result.output_sha256 is None:
            raise ExecutionFailure(result.code if result.code != "ok" else "failed:invalid_output")
        return result

    def updated(**values: object) -> CausalityEvidence:
        return CausalityEvidence.model_validate({**evidence.model_dump(), **values})

    try:
        first = run(request)
        full = first.output
        assert full is not None
        # Preserve actual output when the required rerun fails, so that failed
        # attempt and its available evidence can still be recorded atomically.
        evidence = updated(output_sha256=first.output_sha256)
        second = run(request)
        evidence = updated(
            deterministic=first.output_sha256 == second.output_sha256,
        )
        if not evidence.deterministic:
            return updated(status="failed", code="failed:nondeterministic"), full
        tables = {name: unpack_table(value) for name, value in request.tables.items()}
        complete = project(full, request)
        prefix: list[PrefixCheck] = []
        perturbation: list[PrefixCheck] = []
        prefix_passed = perturbation_passed = True
        for cutoff in cutoffs:
            sliced = RunnerInput(
                schema_version="1",
                seed=request.seed,
                tables={k: pack_table(v) for k, v in slice_inputs(tables, cutoff).items()},
            )
            rebuilt = run(sliced).output
            assert rebuilt is not None
            try:
                prefix.append(
                    compare_projection(
                        complete,
                        project(rebuilt, sliced),
                        cutoff,
                        filter_other=False,
                        atol=atol,
                        rtol=rtol,
                    )
                )
            except AssertionError:
                prefix_passed = False
                break
        # Still test perturbation after prefix failure: both independent pieces
        # of planted-lookahead evidence must be observable, never a skipped pass.
        for cutoff in cutoffs:
            perturbed, changed = perturb_future(tables, cutoff, policy)
            if not changed:
                return updated(
                    prefix=prefix, prefix_passed=prefix_passed, perturbation=perturbation
                ), full
            value = RunnerInput(
                schema_version="1",
                seed=request.seed,
                tables={k: pack_table(v) for k, v in perturbed.items()},
            )
            rebuilt = run(value).output
            assert rebuilt is not None
            try:
                perturbation.append(
                    compare_projection(
                        complete,
                        project(rebuilt, value),
                        cutoff,
                        filter_other=True,
                        atol=atol,
                        rtol=rtol,
                    )
                )
            except AssertionError:
                perturbation_passed = False
                break
        fields = dict(
            prefix=prefix,
            perturbation=perturbation,
            prefix_passed=prefix_passed,
            perturbation_passed=perturbation_passed,
        )
        if not prefix_passed or not perturbation_passed:
            return updated(status="failed", code="failed:lookahead", **fields), full
        if not sum(p.compared_cells for p in prefix) or not sum(
            p.compared_cells for p in perturbation
        ):
            return updated(**fields), full
        return updated(status="passed", code="ok", **fields), full
    except SandboxUnavailable:
        return updated(status="failed", code="failed:backend_unavailable"), full
    except ExecutionFailure as error:
        return updated(status="failed", code=error.code), full
    except (ValueError, TypeError, KeyError, pl.exceptions.PolarsError):
        return updated(status="failed", code="failed:invalid_output"), full
