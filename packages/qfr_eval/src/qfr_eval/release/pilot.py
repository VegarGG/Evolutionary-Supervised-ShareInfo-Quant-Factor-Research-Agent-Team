"""One scalar and enum flags from matching frozen validation evidence only."""

from decimal import Decimal
from math import isfinite
from typing import Literal

from qfr_core.contracts.reports import (
    MetricValue,
    PilotHurdleFlags,
    PilotRelease,
    ReleasedScalar,
    WithheldRelease,
)

from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import EvaluationRequest, Measurement, OfficialRecord
from qfr_eval.release.models import LadderBest, PilotReleasePolicy
from qfr_eval.release.policy import coarsen
from qfr_eval.scheduler.dedup import digest


def scope_hash(request: EvaluationRequest, policy: PilotReleasePolicy, lineage: str) -> str:
    return digest(
        {
            "program": request.program_id,
            "lineage": lineage,
            "protocol": request.protocol_hash,
            "snapshot": request.snapshot_id,
            "epoch": request.epoch_id,
            "window": request.window,
            "cycle": request.cycle,
            "policy": policy.sha256,
        }
    )


def rank_bucket(
    score: float | None, frozen_scores: list[float | None]
) -> Literal["top", "middle", "bottom", "withheld"]:
    if any(value is not None and not isfinite(value) for value in [score, *frozen_scores]):
        raise ValueError("nonfinite frozen family score")
    if score is None or any(item is None for item in frozen_scores):
        return "withheld"
    values = [*frozen_scores, score]
    less = sum(item < score for item in values if item is not None)
    equal = sum(item == score for item in values)
    # Twice the midrank numerator, compared using integers; ties stay together.
    if 3 * (2 * less + equal) <= 2 * len(values):
        return "bottom"
    if 3 * (2 * less + equal) >= 4 * len(values):
        return "top"
    return "middle"


def project_pilot(
    record: OfficialRecord,
    request: EvaluationRequest,
    measured: Measurement,
    protocol: FrozenProtocol,
    policy: PilotReleasePolicy,
    *,
    ordinals: dict[str, int],
    bests: dict[str, LadderBest],
    frozen_family_scores: list[float | None],
    baseline_version_id: str | None,
    cost_basis_ref: str,
    pit_grade_downgrade: bool,
) -> tuple[PilotRelease | WithheldRelease, dict[str, LadderBest]]:
    # No caller can select an alternate window/cycle or apply the oracle policy.
    if (
        request.protocol_hash != protocol.sha256
        or policy.protocol_sha256 != protocol.sha256
        or protocol.release_intent is None
        or protocol.scope != policy.scope
        or policy.ladder_step != protocol.release_intent.ladder_step
        or policy.feedback_versions_per_lineage_generation
        != protocol.release_intent.feedback_versions_per_lineage_generation
        or request.window != policy.release_window
        or request.cycle != policy.release_cycle
        or record.window != request.window
        or record.cycle != request.cycle
        or record.request_hash != request.sha256
        or record.results_hash != measured.results_hash
        or record.identity.artifact_version_id != str(request.artifact_version_id)
        or record.identity.content_hash != request.content_hash
        or record.identity.dataset_version_id != request.snapshot_id
        or record.identity.protocol_version != f"{protocol.protocol_id}@{protocol.version}"
        or record.identity.evaluator_version != request.runtime.evaluator_git_sha
        or record.stage != "measurement"
        or record.metrics != measured.metrics
        or record.protocol_hash != protocol.sha256
    ):
        raise ValueError("release source differs from the frozen pilot identity")
    if not ordinals or any(value <= 0 for value in ordinals.values()) or set(bests) - set(ordinals):
        raise ValueError("authoritative economic lineage reservations required")
    for lineage, best in bests.items():
        if (
            best.scope_sha256 != scope_hash(request, policy, lineage)
            or best.scalar.metric != policy.primary_metric
            or best.scalar.sampling_unit != "mature_matched_decision"
            or best.scalar.baseline_version_id != baseline_version_id
            or best.scalar.cost_basis_ref != cost_basis_ref
        ):
            raise ValueError("prior best has incompatible measurement semantics")
    if request.intent == "diagnostic":
        return WithheldRelease(type="withheld", reason="non_selectable"), {}
    if (
        request.intent == "withheld"
        or record.status == "withheld"
        or max(ordinals.values()) > policy.feedback_versions_per_lineage_generation
    ):
        return WithheldRelease(type="withheld", reason="budget"), {}
    missing = MetricValue(value=None, missing_reason="insufficient_data")
    metric = measured.metrics.get(policy.primary_metric, missing)
    if measured.status == "failed" or record.status == "failed":
        metric = MetricValue(value=None, missing_reason="failed")
    if metric.value is not None and not 0 <= metric.value <= 1:
        raise ValueError("primary recall outside its declared ratio unit")
    current = ReleasedScalar(
        metric=policy.primary_metric,
        sampling_unit="mature_matched_decision",
        period_count=measured.period_count,
        cost_basis_ref=cost_basis_ref,
        baseline_version_id=baseline_version_id,
        measurement=coarsen(metric, policy.ladder_step, floor=True),
        origin_artifact_version_id=str(request.artifact_version_id),
        attribution="current_version",
    )
    prior = max(
        bests.values(),
        key=lambda b: (b.unrounded_score, b.scalar.origin_artifact_version_id),
        default=None,
    )
    improves = metric.value is not None and (
        prior is None
        or Decimal(str(metric.value))
        >= Decimal(str(prior.unrounded_score)) + Decimal(str(policy.ladder_step))
    )
    updates = {}
    if improves:
        assert metric.value is not None
        updates = {
            lineage: LadderBest(
                schema_version="1",
                scope_sha256=scope_hash(request, policy, lineage),
                unrounded_score=metric.value,
                scalar=current,
            )
            for lineage in ordinals
        }
    elif prior is not None:
        current = prior.scalar.model_copy(update={"attribution": "lineage_best"})
    flags = {
        key: measured.hurdle.get(key, "insufficient_data") for key in PilotHurdleFlags.model_fields
    }
    # This is a diagnostic flag only, not a new admission hurdle. Keep the
    # evaluator's existing overall decision and paired-primary flag unchanged.
    net = measured.metrics.get("long_short_net_per_period", missing)
    flags["net_result"] = (
        "insufficient_data" if net.value is None else "pass" if net.value > 0 else "fail"
    )
    flags["coverage"] = measured.hurdle.get(
        "coverage", "pass" if not measured.reason_codes else "insufficient_data"
    )
    quality: list[Literal["small_sample_warning", "pit_grade_downgrade", "duplicate"]] = []
    if measured.uncertainty is None or measured.uncertainty.small_sample_warning:
        quality.append("small_sample_warning")
    if pit_grade_downgrade:
        quality.append("pit_grade_downgrade")
    content = PilotRelease(
        type="pilot",
        scalar=current,
        hurdle_flags=PilotHurdleFlags.model_validate(flags),
        rank_bucket=rank_bucket(metric.value, frozen_family_scores),
        quality_flags=quality,
        minimum_detectable_effect=MetricValue(value=None, missing_reason="withheld"),
        not_for_selection=metric.value is None,
    )
    return content, updates
