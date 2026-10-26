"""Private, frozen development fingerprints and all-attempt cluster evidence."""

import hashlib
from datetime import date
from typing import Literal, Self

import polars as pl
from pydantic import Field, NonNegativeInt, PositiveInt, model_validator
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.metrics.core import behavioral_similarity

from qfr_eval.protocols.models import DiagnosticConfig
from qfr_eval.statistics.family import TrialObservation


class BehavioralFingerprint(Contract):
    schema_version: Literal["1"]
    definition: Literal["pilot_full_development_weekly_v1"]
    protocol_hash: Sha256
    snapshot_id: Text
    epoch_id: Text
    artifact_version_id: Text
    content_hash: Sha256
    seed: NonNegativeInt
    start: date
    end: date
    grid: list[tuple[date, Text]]
    ranks: list[float]

    @model_validator(mode="after")
    def complete_grid(self) -> Self:
        if (
            self.end < self.start
            or not self.grid
            or self.grid != sorted(set(self.grid))
            or len(self.grid) != len(self.ranks)
            or any(not self.start <= day <= self.end for day, _ in self.grid)
        ):
            raise ValueError("fingerprint requires a unique ordered development grid")
        by_date: dict[date, list[float]] = {}
        for (day, _), value in zip(self.grid, self.ranks, strict=True):
            by_date.setdefault(day, []).append(value)
        if any(len(values) < 2 or min(values) == max(values) for values in by_date.values()):
            raise ValueError("fingerprint has a degenerate cross-section")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


class ClusterSnapshot(Contract):
    schema_version: Literal["1"]
    algorithm: Literal["mean_absolute_spearman_single_linkage"]
    status: Literal["estimated", "insufficient_data"]
    basis: Literal["behavioral_clusters", "economic_family_count_above_limit"]
    threshold: float = Field(gt=0, le=1)
    maximum_trials: PositiveInt
    trial_ids: list[Text]
    raw_trials: NonNegativeInt
    effective_trials: PositiveInt | None
    groups: list[list[Text]]
    fingerprint_hashes: dict[Text, Sha256 | None]
    missing_trials: list[Text]
    reason: Literal["complete", "missing_fingerprint", "incomparable_grid", "no_trials"]

    @model_validator(mode="after")
    def all_attempts(self) -> Self:
        if self.trial_ids != sorted(set(self.trial_ids)) or self.raw_trials != len(self.trial_ids):
            raise ValueError("cluster snapshot must count unique attempts")
        if set(self.fingerprint_hashes) != set(self.trial_ids) or not set(
            self.missing_trials
        ) <= set(self.trial_ids):
            raise ValueError("fingerprint coverage must cover the counted cohort")
        if self.status == "estimated":
            if (
                self.effective_trials != len(self.groups)
                or not self.groups
                or any(not group or group != sorted(set(group)) for group in self.groups)
                or sorted(t for group in self.groups for t in group) != self.trial_ids
                or self.reason != "complete"
            ):
                raise ValueError("estimated clusters must partition every attempt")
        elif self.effective_trials is not None or self.groups or self.reason == "complete":
            raise ValueError("missing cluster evidence cannot have an effective count")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


def cluster_trials(
    trials: list[TrialObservation],
    fingerprints: dict[str, BehavioralFingerprint | None],
    config: DiagnosticConfig,
) -> ClusterSnapshot:
    """Single linkage over ALL attempts; missing fingerprints are never independent."""
    ordered = sorted(trials, key=lambda t: t.trial_id)
    ids = [t.trial_id for t in ordered]
    if len(ids) != len(set(ids)) or set(fingerprints) - set(ids):
        raise ValueError("duplicate attempts or fingerprints outside the frozen cohort")
    if (
        len(
            {(t.program_id, t.protocol_hash, t.snapshot_id, t.window, t.cohort_id) for t in ordered}
        )
        > 1
    ):
        raise ValueError("cluster cohort semantics differ")
    hashes = {t: value.sha256 if (value := fingerprints.get(t)) else None for t in ids}
    missing = [t for t in ids if hashes[t] is None]
    base = dict(
        schema_version="1",
        algorithm="mean_absolute_spearman_single_linkage",
        status="insufficient_data",
        basis="behavioral_clusters",
        threshold=config.cluster_similarity,
        maximum_trials=config.cluster_max_trials,
        trial_ids=ids,
        raw_trials=len(ids),
        effective_trials=None,
        groups=[],
        fingerprint_hashes=hashes,
        missing_trials=missing,
        reason="missing_fingerprint",
    )
    if not ids:
        return ClusterSnapshot.model_validate({**base, "reason": "no_trials"})
    if len(ids) > config.cluster_max_trials:
        # Canonical economic family, not a renamed display/family alias. All
        # failed/withheld/diagnostic attempts remain in this declared fallback.
        families: dict[str, list[str]] = {}
        for trial in ordered:
            families.setdefault(trial.economic_lineage_id, []).append(trial.trial_id)
        groups = sorted(families.values())
        return ClusterSnapshot.model_validate(
            {
                **base,
                "status": "estimated",
                "basis": "economic_family_count_above_limit",
                "reason": "complete",
                "groups": groups,
                "effective_trials": len(groups),
            }
        )
    if missing:
        return ClusterSnapshot.model_validate(base)
    reference = fingerprints[ids[0]]
    assert reference is not None
    keys = (
        "definition",
        "protocol_hash",
        "snapshot_id",
        "epoch_id",
        "seed",
        "start",
        "end",
        "grid",
    )
    for trial in ordered:
        value = fingerprints[trial.trial_id]
        assert value is not None
        if (
            value.artifact_version_id != trial.artifact_version_id
            or value.protocol_hash != trial.protocol_hash
            or value.snapshot_id != trial.snapshot_id
            or any(getattr(value, key) != getattr(reference, key) for key in keys)
        ):
            return ClusterSnapshot.model_validate({**base, "reason": "incomparable_grid"})
    # Deduplicate identical rank vectors before pair comparisons. This reduces
    # repeated built-in attempts without deleting a single ledger entry.
    vectors: dict[tuple[float, ...], list[str]] = {}
    for identity in ids:
        value = fingerprints[identity]
        assert value is not None
        vectors.setdefault(tuple(value.ranks), []).append(identity)
    members = list(vectors.values())
    parent = list(range(len(members)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    grid = pl.DataFrame(
        reference.grid, schema=[("date", pl.Date), ("instrument", pl.String)], orient="row"
    )
    frames = [grid.with_columns(pl.Series("rank", values)) for values in vectors]
    for i in range(len(frames)):
        for j in range(i):
            similarity = behavioral_similarity(frames[i], frames[j]).value
            if similarity is None:
                return ClusterSnapshot.model_validate({**base, "reason": "incomparable_grid"})
            if similarity >= config.cluster_similarity:
                parent[root(i)] = root(j)
    groups_by_root: dict[int, list[str]] = {}
    for i, group in enumerate(members):
        groups_by_root.setdefault(root(i), []).extend(group)
    groups = sorted(sorted(group) for group in groups_by_root.values())
    return ClusterSnapshot.model_validate(
        {
            **base,
            "status": "estimated",
            "reason": "complete",
            "groups": groups,
            "effective_trials": len(groups),
        }
    )
