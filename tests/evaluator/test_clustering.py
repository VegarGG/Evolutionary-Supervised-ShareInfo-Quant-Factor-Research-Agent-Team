from datetime import date
from pathlib import Path

import polars as pl
import pytest
from qfr_core.configuration import load_yaml
from qfr_core.metrics.core import behavioral_similarity
from qfr_eval.backtest.fingerprint import pilot_fingerprint
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import EvaluationRequest
from qfr_eval.runtime import builtin_definition
from qfr_eval.statistics.clustering import BehavioralFingerprint, cluster_trials
from qfr_eval.statistics.family import TrialObservation


def protocol_fixture():
    return load_yaml(Path("configs/evaluation/pilot_p0_p1_verification_v1.yaml"), FrozenProtocol)


def trial_fixture(identity, status="evaluated"):
    return TrialObservation.model_validate_json(
        Path(
            "packages/qfr_eval/src/qfr_eval/private_contracts/TrialObservation.valid.json"
        ).read_bytes()
    ).model_copy(
        update={
            "trial_id": identity,
            "artifact_version_id": identity,
            "status": status,
            "selectable": status not in {"diagnostic", "failed"},
            "protocol_hash": protocol_fixture().sha256,
        }
    )


def fingerprint_fixture(trial, ranks):
    return BehavioralFingerprint(
        schema_version="1",
        definition="pilot_full_development_weekly_v1",
        protocol_hash=trial.protocol_hash,
        snapshot_id=trial.snapshot_id,
        epoch_id="fixture",
        artifact_version_id=trial.artifact_version_id,
        content_hash="1" * 64,
        seed=protocol_fixture().diagnostics.purpose_seeds["fingerprint"],
        start=date(2020, 1, 1),
        end=date(2022, 12, 31),
        grid=[(date(2020, 1, day), str(i)) for day in (2, 3) for i in range(len(ranks))],
        ranks=ranks * 2,
    )


def test_single_linkage_chain_absolute_similarity_and_every_attempt():
    trials = [
        trial_fixture(str(i), status)
        for i, status in enumerate(["evaluated", "withheld", "diagnostic", "failed"])
    ]
    # Spearman A-B=.9, B-C=.8, A-C=.5: A and C still share a single-link cluster.
    ranks = [[1, 2, 3, 4, 5], [1, 2, 4, 3, 5], [1, 3, 5, 2, 4], [5, 4, 3, 2, 1]]
    fingerprints = {
        t.trial_id: fingerprint_fixture(t, r) for t, r in zip(trials, ranks, strict=True)
    }
    result = cluster_trials(trials, fingerprints, protocol_fixture().diagnostics)
    assert result.status == "estimated" and result.raw_trials == 4 and result.effective_trials == 1
    assert result.groups == [["0", "1", "2", "3"]]
    separate = cluster_trials(
        trials,
        fingerprints,
        protocol_fixture().diagnostics.model_copy(update={"cluster_similarity": 1.0}),
    )
    assert separate.effective_trials == 3 and ["0", "3"] in separate.groups
    assert (
        cluster_trials(list(reversed(trials)), fingerprints, protocol_fixture().diagnostics)
        == result
    )


def test_cluster_missing_or_incomparable_fingerprint_never_assumes_independence():
    trials = [trial_fixture("a"), trial_fixture("b", "failed")]
    values = {t.trial_id: fingerprint_fixture(t, [1, 2, 3]) for t in trials}
    for changed, reason in [
        ({**values, "b": None}, "missing_fingerprint"),
        (
            {**values, "b": values["b"].model_copy(update={"epoch_id": "different"})},
            "incomparable_grid",
        ),
        (
            {
                **values,
                "b": values["b"].model_copy(
                    update={"grid": values["b"].grid[:3], "ranks": values["b"].ranks[:3]}
                ),
            },
            "incomparable_grid",
        ),
    ]:
        result = cluster_trials(trials, changed, protocol_fixture().diagnostics)
        assert result.raw_trials == 2 and result.effective_trials is None
        assert result.status == "insufficient_data" and result.reason == reason
    with pytest.raises(ValueError, match="degenerate"):
        fingerprint_fixture(trials[0], [1, 1, 1])


def test_above_20000_fallback_counts_canonical_families_without_resetting_attempts():
    config = protocol_fixture().diagnostics
    assert config.cluster_max_trials == 20000
    base = trial_fixture("template", "failed")
    trials = [
        base.model_copy(
            update={
                "trial_id": str(i),
                "family_id": f"renamed-{i}",
                "economic_lineage_id": str(i % 2),
            }
        )
        for i in range(20001)
    ]
    result = cluster_trials(trials, {}, config)
    assert result.status == "estimated" and result.effective_trials == 2
    assert result.raw_trials == len(result.missing_trials) == 20001
    assert result.basis == "economic_family_count_above_limit"
    at_limit = cluster_trials(trials[:20000], {}, config)
    assert at_limit.status == "insufficient_data" and at_limit.effective_trials is None


def test_shared_similarity_uses_mean_absolute_date_correlations_in_stable_order():
    a = pl.DataFrame(
        {
            "date": [date(2020, 1, d) for d in (2, 3) for _ in range(5)],
            "instrument": list("abcde") * 2,
            "rank": [1, 2, 3, 4, 5] * 2,
        }
    )
    b = a.with_columns(pl.Series("rank", [1, 2, 4, 3, 5, 5, 4, 3, 2, 1]))
    assert behavioral_similarity(a, b).value == pytest.approx((0.9 + 1) / 2)
    assert behavioral_similarity(a, b) == behavioral_similarity(a.reverse(), b.reverse())


@pytest.mark.pilot
def test_pilot_fingerprint_full_122_decisions_is_development_only(pilot_sources):
    _, tables, _ = pilot_sources
    protocol = protocol_fixture()
    artifact, digest, _ = builtin_definition("baseline")
    request = EvaluationRequest.model_validate_json(
        Path(
            "packages/qfr_eval/src/qfr_eval/private_contracts/EvaluationRequest.valid.json"
        ).read_bytes()
    ).model_copy(update={"artifact_version_id": artifact, "content_hash": digest})
    actual = pilot_fingerprint(request, protocol, tables)
    assert len({day for day, _ in actual.grid}) == 122
    assert max(day for day, _ in actual.grid) <= date(2022, 12, 31)
    truncated = {}
    for name, frame in tables.items():
        truncated[name] = (
            frame.filter(pl.col("date") <= date(2022, 12, 31)) if "date" in frame.columns else frame
        )
    assert pilot_fingerprint(request, protocol, truncated) == actual
    assert len(actual.grid) > 40 * 31  # The stock-profile sample is never inherited.
    broken = {**tables, "features": tables["features"].filter(pl.col("date") != date(2021, 12, 31))}
    with pytest.raises(ValueError, match="frozen original P0 development grid"):
        pilot_fingerprint(request, protocol, broken)
