"""Pure coarsening, timing and explicit public policy projections."""

from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal

from qfr_core.contracts.reports import MetricValue, PublicReleasePolicyCard

from qfr_eval.release.models import PilotReleasePolicy, StockReleasePolicy


def coarsen(value: MetricValue, step: float, *, floor: bool = False) -> MetricValue:
    quantum = Decimal(str(step))
    if not quantum.is_finite() or quantum <= 0:
        raise ValueError("positive finite release precision required")
    if value.value is None:
        return value
    number = Decimal(str(value.value))
    rounded = (number / quantum).to_integral_value(
        rounding=ROUND_FLOOR if floor else ROUND_HALF_UP
    ) * quantum
    return MetricValue(value=float(rounded), missing_reason=None)


def batch_at_or_after(at: datetime, *, hours: int = 6, weekly: bool = False) -> datetime:
    if at.utcoffset() is None or hours <= 0 or 24 % hours:
        raise ValueError("aware timestamp and an integral UTC-day batch required")
    at = at.astimezone(UTC)
    start = at.replace(hour=0, minute=0, second=0, microsecond=0)
    if weekly:
        start -= timedelta(days=start.weekday())
        step = timedelta(days=7)
    else:
        start += timedelta(hours=(at.hour // hours) * hours)
        step = timedelta(hours=hours)
    return start if start == at else start + step


def eligible_at(
    policy: PilotReleasePolicy | StockReleasePolicy, stage: str, completed_at: datetime
) -> datetime:
    if isinstance(policy, PilotReleasePolicy):
        if stage not in ("pilot", "intake", "screening", "withheld"):
            raise ValueError("pilot release stage is not enabled")
        return batch_at_or_after(completed_at, hours=policy.batch_hours)
    if stage in ("intake", "screening", "w1", "withheld"):
        return batch_at_or_after(completed_at, hours=policy.w1_batch_hours)
    if stage == "w2":
        return batch_at_or_after(completed_at, weekly=True)
    if stage == "advancement":
        return batch_at_or_after(
            completed_at + timedelta(days=policy.advancement_delay_days), weekly=True
        )
    if stage in ("sim", "decision", "library"):
        if completed_at.utcoffset() is None:
            raise ValueError("aware timestamp required")
        return completed_at.astimezone(UTC)
    raise ValueError("no release mapping for this stage")


def t_bucket(
    value: MetricValue,
) -> Literal["below_1", "1_to_2", "2_to_3", "above_3", "unavailable"]:
    if value.value is None:
        return "unavailable"
    if value.value < 1:
        return "below_1"
    if value.value < 2:
        return "1_to_2"
    if value.value < 3:
        return "2_to_3"
    return "above_3"


def public_card(policy: PilotReleasePolicy | StockReleasePolicy) -> PublicReleasePolicyCard:
    common = dict(
        schema_version="1",
        policy_ref=f"{policy.policy_id}@{policy.version}",
        policy_sha256=policy.sha256,
        profile=policy.profile,
        fitness_profile=policy.fitness_profile,
        raw_series_released=False,
        confirmation_metrics_released=False,
        diagnostics="enum_codes_only",
        prior_best_origin_required=True,
    )
    if isinstance(policy, PilotReleasePolicy):
        values = dict(
            disclosure="scalar_plus_flags",
            ladder_step=policy.ladder_step,
            rounding={"primary": policy.ladder_step},
            batch_hours=policy.batch_hours,
            weekly_batch=None,
            advancement_delay_days=None,
            quotas={
                "lineage_versions_per_generation": policy.feedback_versions_per_lineage_generation
            },
        )
    else:
        values = dict(
            disclosure="coarsened_stock_reports",
            ladder_step=policy.ladder_eta,
            rounding=policy.rounding.model_dump(),
            batch_hours=policy.w1_batch_hours,
            weekly_batch=policy.w2_batch,
            advancement_delay_days=policy.advancement_delay_days,
            quotas=policy.quotas.model_dump(
                exclude={"deferral_expiry_days", "burn_w1_amber", "burn_w1_red"}
            ),
        )
    return PublicReleasePolicyCard.model_validate({**common, **values})
