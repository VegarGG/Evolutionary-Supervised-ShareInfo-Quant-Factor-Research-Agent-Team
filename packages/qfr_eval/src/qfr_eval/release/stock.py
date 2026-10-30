"""Stock-policy field allowlist. No W3 measurement projection exists."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Literal

from qfr_core.contracts.reports import (
    AdvancementRelease,
    MetricValue,
    ReleasedScalar,
    StockW1Release,
    StockW2Release,
)

from qfr_eval.release.models import LadderBest, StockReleasePolicy
from qfr_eval.release.policy import coarsen, t_bucket


def project_w1(
    metrics: Mapping[str, MetricValue],
    *,
    window: str,
    policy: StockReleasePolicy,
    yearly: dict[str, MetricValue],
    decay: dict[Literal["1", "5", "10", "20"], MetricValue],
    library_artifact_version_id: str | None,
    coverage_bucket: Literal["low", "adequate", "high", "unavailable"],
    complexity: int,
) -> StockW1Release:
    if window != "W1":
        raise ValueError("stock metric projection requires W1")
    missing = MetricValue(value=None, missing_reason="insufficient_data")
    precision = policy.rounding

    def number(name: str, step: float) -> MetricValue:
        return coarsen(metrics.get(name, missing), step)

    return StockW1Release(
        type="w1",
        rank_ic_mean=number("rank_ic_mean", precision.rank_ic),
        rank_ic_ir=number("rank_ic_ir", precision.ir),
        nw_t_bucket=t_bucket(metrics.get("nw_t", missing)),
        positive_rank_ic_date_share=number("positive_rank_ic_date_share", precision.shares),
        decay_profile={key: coarsen(value, precision.rank_ic) for key, value in decay.items()},
        ls_net_sharpe=number("ls_net_sharpe", precision.sharpe),
        monotonicity=number("monotonicity", precision.correlations),
        top_turnover=number("top_turnover", precision.shares),
        rank_autocorrelation=number("rank_autocorrelation", precision.correlations),
        max_library_correlation=number("max_library_correlation", precision.correlations),
        library_artifact_version_id=library_artifact_version_id
        if metrics.get("max_library_correlation", missing).value is not None
        else None,
        yearly_rank_ic={year: coarsen(value, precision.rank_ic) for year, value in yearly.items()},
        coverage_bucket=coverage_bucket,
        size_neutral_rank_ic=number("size_neutral_rank_ic", precision.rank_ic),
        complexity=complexity,
    )


def project_w2(
    current: ReleasedScalar,
    *,
    window: str,
    policy: StockReleasePolicy,
    passed: bool,
    scope_sha256: str,
    prior: LadderBest | None,
) -> tuple[StockW2Release, LadderBest | None]:
    if (
        window != "W2"
        or current.metric != "RankIC_mean"
        or current.sampling_unit != "trading_date"
        or current.attribution != "current_version"
    ):
        raise ValueError("stock Ladder requires current W2 RankIC evidence")
    if prior is not None and (
        prior.scope_sha256 != scope_sha256
        or prior.scalar.metric != current.metric
        or prior.scalar.sampling_unit != current.sampling_unit
        or prior.scalar.cost_basis_ref != current.cost_basis_ref
        or prior.scalar.baseline_version_id != current.baseline_version_id
    ):
        raise ValueError("prior stock best has incompatible semantics")
    value = current.measurement.value
    decision: Literal["PASS", "FAIL"] = "PASS" if passed else "FAIL"
    if value is None:
        if passed:
            raise ValueError("missing W2 metric cannot pass")
        return StockW2Release(
            type="w2", decision="FAIL", ladder_status="withheld", scalar=None
        ), None
    if not -1 <= value <= 1:
        raise ValueError("RankIC outside its declared unit")
    if prior is not None and Decimal(str(value)) < (
        Decimal(str(prior.unrounded_score)) + Decimal(str(policy.ladder_eta))
    ):
        return StockW2Release(
            type="w2", decision=decision, ladder_status="unchanged", scalar=None
        ), None
    scalar = current.model_copy(
        update={"measurement": coarsen(current.measurement, policy.rounding.w2_best_rank_ic)}
    )
    best = LadderBest(
        schema_version="1", scope_sha256=scope_sha256, unrounded_score=value, scalar=scalar
    )
    return StockW2Release(
        type="w2", decision=decision, ladder_status="improved", scalar=scalar
    ), best


def project_advancement(*, advanced: bool) -> AdvancementRelease:
    """Formatting only. This does not run or authorize a holdout check."""
    return AdvancementRelease(
        type="advancement", decision="ADVANCED" if advanced else "NOT_ADVANCED"
    )
