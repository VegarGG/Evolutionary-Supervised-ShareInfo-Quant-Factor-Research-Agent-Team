"""Private frozen evaluation protocol. Never part of the public schema catalog."""

import hashlib
from datetime import date
from typing import Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.metrics.pilot import PilotMetricConfig
from qfr_core.pilot.baseline import P0Config
from qfr_core.pilot.features import PilotFeatureConfig

Cycle = Literal["weekly", "monthly", "quarterly", "fixed_quarter"]


class EvaluationWindow(Contract):
    start: date
    end: date
    exposure: Literal["previously_seen"]
    access: Literal["research", "private", "locked"]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.start > self.end:
            raise ValueError("window start exceeds end")
        return self


class BootstrapConfig(Contract):
    draws: PositiveInt
    seed: NonNegativeInt
    method: Literal["paired_circular_blocks"]
    confidence: float = Field(gt=0, lt=1)
    block_floors: dict[Cycle, PositiveInt]
    automatic: bool
    minimum_periods: PositiveInt
    minimum_blocks: PositiveInt
    sensitivity: bool
    family_method: Literal["romano_wolf_studentized", "original_bonferroni_12"]
    family_comparisons: PositiveInt | None


class TurnoverPolicy(Contract):
    cycle: Literal["weekly"]
    top_threshold: float = Field(ge=0, le=1)
    bottom_threshold: float = Field(ge=0, le=1)
    maximum_exceedance_numerator: PositiveInt
    maximum_exceedance_denominator: PositiveInt
    comparison: Literal["strict_gt"]
    combine: Literal["both_pass"]
    exclude: Literal["one_initial_construction_only"]
    formula: Literal["(buy+sell+abs(previous_sum-target_sum))/2"]
    missing: Literal["insufficient_data"]
    calibration_ref: Sha256


class ReleaseIntent(Contract):
    policy: Literal["scalar_plus_flags"]
    feedback_versions_per_lineage_generation: PositiveInt
    quota_identity: Literal["program,economic_lineage,server_generation"]
    renaming_resets_budget: Literal[False]
    confirmation_queries_per_protocol: PositiveInt
    confirmation_requires_separate_authorization: Literal[True]
    ladder_step: float = Field(gt=0)
    ladder_reference: Literal["P0_development_bootstrap_mean_sd_ddof1"]
    rounding: Literal["floor_to_step"]
    retain_origin_version: Literal[True]


class DiagnosticConfig(Contract):
    prefix_cutoffs: list[date]
    placebo_min_shift: dict[Cycle, PositiveInt]
    placebo_percentile_hurdle: float = Field(ge=0, le=100)
    max_pool_correlation: float = Field(gt=0, le=1)
    fingerprint_window: Literal["development"]
    cluster_similarity: float = Field(gt=0, le=1)
    cluster_max_trials: PositiveInt
    pbo_blocks: PositiveInt
    minimum_pbo_candidates: PositiveInt
    hlz_t_hurdle: float = Field(gt=0)
    permutation_draws: PositiveInt
    root_seed: NonNegativeInt
    purpose_seeds: dict[Text, NonNegativeInt]


class FrozenProtocol(Contract):
    schema_version: Literal["1"]
    protocol_id: Text
    version: Text
    profile: Literal["pilot_industry_v1"]
    scope: Literal["P0_P1_verification_only", "original_pilot_oracle"]
    approval_ref: Text
    approved_proposal_sha256: Sha256 | None
    approved_manifest_sha256: Sha256 | None
    source_hashes: dict[Text, Sha256]
    windows: dict[Text, EvaluationWindow]
    embargo_trading_days: NonNegativeInt
    purge: Literal["entry_and_exit_inside_window_carry_state"]
    primary_metric: Literal["extreme_macro_recall"]
    primary_cycle: Literal["weekly"]
    primary_cost_bps: Literal[10]
    group: Literal["p60"]
    baseline: Literal["P1_reversal_momentum"]
    calibration_reference: Literal["baseline"]
    p0: P0Config
    features: PilotFeatureConfig
    metrics: PilotMetricConfig
    bootstrap: BootstrapConfig
    diagnostics: DiagnosticConfig
    turnover: TurnoverPolicy | None
    release_intent: ReleaseIntent | None
    atol: float = Field(gt=0)
    rtol: float = Field(gt=0)
    extra_training: Literal[False]
    new_supplier_requests: Literal[False]
    live_model_calls: Literal[False]

    @model_validator(mode="after")
    def complete_semantics(self) -> Self:
        ordered = sorted(self.windows.values(), key=lambda w: w.start)
        if any(a.end >= b.start for a, b in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("protocol windows overlap")
        cycles = {"weekly", "monthly", "quarterly", "fixed_quarter"}
        if set(self.bootstrap.block_floors) != cycles:
            raise ValueError("all cycle block floors required")
        if self.scope == "P0_P1_verification_only":
            if self.bootstrap.draws < 10000 or not self.bootstrap.automatic:
                raise ValueError("official protocol requires >=10000 automatic block draws")
            if self.turnover is None or self.release_intent is None:
                raise ValueError("official protocol needs approved turnover and release intent")
            if not self.approved_proposal_sha256 or not self.approved_manifest_sha256:
                raise ValueError("official protocol requires approval artifact identities")
            if set(self.windows) != {"development", "validation", "confirmation"}:
                raise ValueError("P0/P1 verification has no diagnostic window")
            if self.windows["confirmation"].access != "locked":
                raise ValueError("confirmation must stay locked")
        if set(self.metrics.costs_bps) != {0, 10, 30}:
            raise ValueError("preserve pilot cost scenarios")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()
