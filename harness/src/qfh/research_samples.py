"""Operator-prepared, immutable BaoStock samples composed from small source queries.

Expansion is based on quality and support only. It never computes an effect or
interval while choosing a sample, and never changes a candidate to improve support.
"""

from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

from pydantic import BaseModel, ConfigDict, Field, model_validator

from qfh.evidence import Query
from qfh.research_specification import ContrastSpec


class SampleRange(BaseModel):
    """A composed scope; each actual vendor request still uses bounded Query."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    symbols: list[str] = Field(min_length=1, max_length=1)
    start: date
    end: date

    @model_validator(mode="after")
    def valid_range(self):
        Query(symbols=self.symbols, start=self.start, end=self.start)
        if self.end < self.start:
            raise ValueError("reversed sample range")
        return self


class ExpansionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z0-9-]{5,100}$")
    authority: str = Field(min_length=40)
    data_config: str = Field(pattern=r"^[A-Za-z0-9_-]+\.yaml$")
    base_evidence_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_trial_id: str = Field(min_length=1, max_length=200)
    reference_specification_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    steps: list[Query] = Field(min_length=1, max_length=12)
    minimum_aligned_cases: int = Field(strict=True, ge=2)
    minimum_bucket_cases: int = Field(strict=True, ge=2)
    minimum_blocks: int = Field(strict=True, ge=2)
    absolute_return_warning: Decimal = Field(gt=0, le=1, allow_inf_nan=False)
    preview_rows: int = Field(strict=True, ge=1, le=20)
    alignment_preview_rows: int = Field(strict=True, ge=1, le=5)


class SampleActivation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z0-9-]{5,100}$")
    authority: str = Field(min_length=40)
    expected_previous_id: str | None
    evidence_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    query: SampleRange
    plan_id: str = Field(pattern=r"^[a-z0-9-]{5,100}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixed_definition: ContrastSpec
    statistical_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preview_rows: int = Field(strict=True, ge=1, le=20)
    alignment_preview_rows: int = Field(strict=True, ge=1, le=5)


def compose_sample(store, parent_ids, cutoff, plan_id, plan_sha256, stage, *, synthetic=False):
    if not parent_ids or len(set(parent_ids)) != len(parent_ids):
        raise ValueError("distinct source evidence required")
    records = [store.get(ident) for ident in parent_ids]
    queries = [Query.model_validate(r["query"]) for r in records]
    symbols = queries[0].symbols
    for record, query in zip(records, queries, strict=True):
        if (
            record.get("provider") != "baostock"
            or record.get("kind") != "bars"
            or record.get("adjustment") != "none"
            or record.get("research_cutoff") != cutoff.isoformat()
            or bool(record.get("transport", {}).get("synthetic", False)) != synthetic
            or query.symbols != symbols
            or len(symbols) != 1
            or query.end > cutoff.date()
        ):
            raise ValueError("source identity, adjustment, cutoff or execution mode differs")
    ordered_queries = sorted(queries, key=lambda q: q.start)
    if any(
        a.end + timedelta(days=1) != b.start
        for a, b in zip(ordered_queries, ordered_queries[1:], strict=False)
    ):
        raise ValueError("source query ranges must be adjacent without overlap or gaps")
    rows = []
    for record, query in zip(records, queries, strict=True):
        if not record["content"]:
            raise ValueError("empty source chunk cannot pass sample preparation")
        for row in record["content"]:
            day = date.fromisoformat(row["date"])
            close = Decimal(str(row["close"]))
            if (
                row["symbol"] != symbols[0]
                or not query.start <= day <= query.end
                or not close.is_finite()
                or close <= 0
            ):
                raise ValueError("invalid or out-of-scope source row")
            rows.append(row)
    rows.sort(key=lambda r: r["date"])
    if len({r["date"] for r in rows}) != len(rows):
        raise ValueError("duplicate dates across source chunks")
    scope = SampleRange(
        symbols=symbols, start=ordered_queries[0].start, end=ordered_queries[-1].end
    )
    record = {
        "provider": "baostock",
        "kind": "bars",
        "query": scope.model_dump(mode="json"),
        "retrieved_at": max(r["retrieved_at"] for r in records),
        "research_cutoff": cutoff.isoformat(),
        "adjustment": "none",
        "content": rows,
        "source_evidence_ids": sorted(parent_ids),
        "composition": {
            "protocol": "adjacent-source-chunks-v1",
            "plan_id": plan_id,
            "plan_sha256": plan_sha256,
            "stage": stage,
            "synthetic": synthetic,
        },
        "timing_limit": "Historical unadjusted closes, not a vintage archive. Returned "
        "observations are not a verified exchange calendar; corporate actions are unadjusted.",
    }
    return store.put(record), record


def support_profile(rows, spec, protocol, plan):
    """Exact support/quality checks only: no conditional means, effect or interval."""
    prices = [Fraction(str(r["close"])) for r in rows]
    dates = [date.fromisoformat(r["date"]) for r in rows]
    threshold = Fraction(spec.threshold)
    groups, ties = [], 0
    for i in range(spec.lookback, len(prices) - protocol.execution_lag - spec.label_horizon):
        trailing = prices[i] / prices[i - spec.lookback] - 1
        groups.append(trailing < threshold if spec.comparison == "lt" else trailing > threshold)
        ties += trailing == threshold
    counts = [sum(groups), sum(not group for group in groups)]
    block_length = max(protocol.block_length, spec.label_horizon)
    reasons = []
    if len(groups) < max(
        plan.minimum_aligned_cases, block_length * max(plan.minimum_blocks, protocol.minimum_blocks)
    ):
        reasons.append("below_planned_case_or_block_target")
    if min(counts, default=0) < max(plan.minimum_bucket_cases, protocol.minimum_bucket_size):
        reasons.append("below_planned_bucket_target")
    warnings = [
        {
            "end_date": dates[i].isoformat(),
            "absolute_return": str(float(abs(prices[i] / prices[i - 1] - 1))),
        }
        for i in range(1, len(prices))
        if abs(prices[i] / prices[i - 1] - 1) > Fraction(plan.absolute_return_warning)
    ]
    return {
        "row_count": len(rows),
        "first_observation": dates[0].isoformat(),
        "last_observation": dates[-1].isoformat(),
        "unique_dates": len(set(dates)),
        "weekend_observations": sum(d.weekday() >= 5 for d in dates),
        "maximum_calendar_gap_days": max(
            (b - a).days for a, b in zip(dates, dates[1:], strict=False)
        ),
        "large_unadjusted_return_warnings": warnings,
        "aligned_cases": len(groups),
        "signal_bucket": counts[0],
        "control_bucket": counts[1],
        "ties_to_control": ties,
        "block_length": block_length,
        "complete_blocks": len(groups) // block_length,
        "support_ready": not reasons,
        "reason_codes": reasons,
        "inference_computed": False,
        "quality_limits": [
            "Calendar completeness, corporate actions and vintage availability are unverified.",
            "Count floors permit a pilot calculation; they do not certify coverage or power.",
        ],
    }


def compact_calculation(result, kind, artifact_store, preview_rows):
    """Keep complete calculations immutable; show bounded summaries to the LLM."""
    artifact_id = artifact_store.put({"kind": kind, "result": result})

    def preview(rows):
        return rows if len(rows) <= preview_rows * 2 else rows[:preview_rows] + rows[-preview_rows:]

    view = dict(result)
    if kind == "metrics":
        view["facts"] = {
            key: value
            for key, value in result["facts"].items()
            if not key.startswith("daily_return.") and ".return." not in key
        }
        view["alignment"] = {key: preview(rows) for key, rows in result["alignment"].items()}
        view["alignment_total_rows"] = {key: len(rows) for key, rows in result["alignment"].items()}
    else:
        view["alignment"] = preview(result["alignment"])
        view["alignment_total_rows"] = len(result["alignment"])
    view["calculation_artifact_id"] = artifact_id
    view["view_scope"] = "Summary facts and first/last alignment rows only. The full permitted "
    "sample was computed; all detailed rows and numerical outputs are frozen in the artifact. "
    "Cite only the fact keys visible in this result. A preview is not the complete raw sample."
    return view
