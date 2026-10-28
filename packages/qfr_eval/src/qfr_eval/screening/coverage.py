"""Original eligible observations, with no candidate-selected denominator."""

from dataclasses import dataclass
from typing import Literal

import polars as pl
from qfr_core.contracts.enums import ArtifactKind, ReasonCode
from qfr_core.contracts.execution import RunnerOutput
from qfr_core.runner_tables import unpack_table

from qfr_eval.screening.models import CoverageEvidence


@dataclass(frozen=True)
class RequiredTable:
    # Built by the evaluator's kind adapter from original eligibility/warm-up,
    # never from the candidate's returned rows or claimed coverage flags.
    eligible_keys: pl.DataFrame
    keys: tuple[str, ...]
    finite_columns: tuple[str, ...]
    score_columns: tuple[str, ...]
    date_column: str = "date"


def check_coverage(
    output: RunnerOutput, required: dict[str, RequiredTable], *, fixed_position_strategy: bool
) -> CoverageEvidence:
    exempt = fixed_position_strategy and output.kind == ArtifactKind.STRATEGY
    total = sum(table.eligible_keys.height for table in required.values())
    covered = scored = constant = 0

    def evidence(
        status: Literal["passed", "failed", "insufficient_data"], reasons: list[ReasonCode]
    ) -> CoverageEvidence:
        return CoverageEvidence(
            schema_version="1",
            status=status,
            reason_codes=reasons,
            required_observations=total,
            complete_observations=covered,
            scored_cross_sections=scored,
            constant_cross_sections=constant,
            fixed_position_exempt=exempt,
            diagnostics=["some_constant_cross_sections"] if 0 < constant < scored else [],
        )

    if not required or not total:
        return evidence("insufficient_data", [ReasonCode.LOW_COVERAGE])
    if set(output.tables) != set(required):
        return evidence("insufficient_data", [ReasonCode.LOW_COVERAGE])
    for name, rule in required.items():
        grid = rule.eligible_keys
        if not set(rule.score_columns) <= set(rule.finite_columns):
            raise ValueError("every scoring column must require finite eligible output")
        if (
            not rule.keys
            or set(grid.columns) != set(rule.keys)
            or grid.select(pl.struct(rule.keys).is_duplicated().any()).item()
            or grid.select(pl.any_horizontal(pl.all().is_null()).any()).item()
        ):
            raise ValueError("evaluator eligibility must be a unique complete key grid")
        try:
            frame = unpack_table(output.tables[name])
            if (
                not set(rule.keys + rule.finite_columns + rule.score_columns) <= set(frame.columns)
                or frame.select(pl.struct(rule.keys).is_duplicated().any()).item()
                or frame.select(
                    pl.any_horizontal([pl.col(c).is_null() for c in rule.keys]).any()
                ).item()
            ):
                return evidence("failed", [ReasonCode.DECLARATION_MISMATCH])
            if any(frame.schema[key] != grid.schema[key] for key in rule.keys):
                return evidence("failed", [ReasonCode.DECLARATION_MISMATCH])
            frame = frame.with_columns(pl.lit(True).alias("_qfr_present"))
            matched = grid.join(frame, on=list(rule.keys), how="left", validate="1:1")
            valid = pl.col("_qfr_present").fill_null(False)
            for column in rule.finite_columns:
                if not matched.schema[column].is_numeric():
                    return evidence("failed", [ReasonCode.DECLARATION_MISMATCH])
                valid &= pl.col(column).is_not_null() & pl.col(column).is_finite()
            complete = matched.filter(valid)
            covered += complete.height
            if rule.score_columns:
                if rule.date_column not in rule.keys:
                    raise ValueError("scorer eligibility must include its decision date")
                # Missing values were counted above; never shrink the pool to
                # improve a score. Constant means exact equality, not a new
                # near-zero/percentage threshold imported from the stock profile.
                if complete.height == grid.height:
                    for cross in complete.partition_by(rule.date_column):
                        scored += 1
                        constant += int(
                            all(cross[col].n_unique() == 1 for col in rule.score_columns)
                        )
        except (TypeError, ValueError, pl.exceptions.PolarsError):
            return evidence("failed", [ReasonCode.DECLARATION_MISMATCH])
    if covered != total:
        return evidence("insufficient_data", [ReasonCode.LOW_COVERAGE])
    if output.kind in (ArtifactKind.FACTOR, ArtifactKind.MODEL) and not scored:
        return evidence("insufficient_data", [ReasonCode.LOW_COVERAGE])
    if scored and scored == constant and not exempt:
        return evidence("failed", [ReasonCode.DEGENERATE])
    return evidence("passed", [])
