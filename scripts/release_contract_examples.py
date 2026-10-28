"""Synthetic release contract shapes; no signed/public execution evidence."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from qfr_core.contracts.reports import ReleasedReport, ReleasedScalar
from qfr_eval.release.models import (
    BurnSummary,
    LadderBest,
    PilotReleasePolicy,
    PreparedRelease,
    QuotaDecision,
    QuotaSubject,
    ReleaseSource,
    StockReleasePolicy,
    StockReleaseRecord,
)


def examples(root: Path):
    pilot = PilotReleasePolicy.model_validate_json(
        (root / "configs/evaluation/release_pilot_v1.json").read_bytes()
    )
    stock = StockReleasePolicy.model_validate_json(
        (root / "configs/evaluation/release_stock_v1.json").read_bytes()
    )
    report = ReleasedReport.model_validate_json(
        (root / "contracts/examples/ReleasedReport.valid.json").read_bytes()
    )
    scalar_value = json.loads((root / "contracts/examples/ReleasedScalar.valid.json").read_bytes())
    scalar_value["measurement"] = {"value": 0.5, "missing_reason": None}
    best = LadderBest(
        schema_version="1",
        scope_sha256="0" * 64,
        unrounded_score=0.5,
        scalar=ReleasedScalar.model_validate(scalar_value),
    )
    prepared = PreparedRelease(
        schema_version="1",
        visibility="private_unsigned",
        report_id=UUID(int=1),
        source_id=UUID(int=2),
        source_kind="official_record",
        identity=report.identity,
        family_id=report.family_id,
        program_id=report.program_id,
        epoch_id="synthetic-epoch",
        generation_id="synthetic-generation",
        lineage_ids=["synthetic-lineage"],
        release_policy_ref=f"{pilot.policy_id}@{pilot.version}",
        release_policy_sha256=pilot.sha256,
        protocol_card_ref=report.protocol_card_ref,
        profile=pilot.profile,
        content=report.content,
        reason_codes=[],
        flags=[],
        eligible_at=datetime(2026, 10, 25, 18, tzinfo=UTC),
        numeric_values=0,
        ladder_updates={},
    )
    subject = QuotaSubject(
        schema_version="1",
        profile="stock_daily_v1",
        artifact_version_id=UUID(int=1),
        program_id="synthetic-program",
        family_id="synthetic-lineage",
        epoch_id="synthetic-epoch",
        stage="w1",
    )
    decision = QuotaDecision(
        schema_version="1",
        subject_sha256=subject.sha256,
        state="deferred",
        reason="QUOTA_DEFERRED",
        admission_id=None,
        next_eligible_at=None,
    )
    source = ReleaseSource(
        schema_version="1",
        source_kind="official_record",
        source_id=UUID(int=2),
        source_sha256="0" * 64,
        policy_sha256=pilot.sha256,
        program_id=prepared.program_id,
        family_id=prepared.family_id,
        epoch_id=prepared.epoch_id,
        stage="pilot",
        completed_at=prepared.eligible_at,
        eligible_at=prepared.eligible_at,
    )
    stock_record = StockReleaseRecord(
        schema_version="1",
        stage="stock_measurement",
        record_id=UUID(int=2),
        identity=report.identity,
        program_id="synthetic-program",
        family_id="synthetic-family",
        economic_lineage_id="synthetic-root",
        generation_id="synthetic-generation",
        epoch_id="synthetic-epoch",
        window="W1",
        sampling_unit="trading_date",
        period_count=0,
        status="failed",
        metrics={},
        yearly_rank_ic={},
        decay_profile={},
        library_artifact_version_id=None,
        coverage_bucket="unavailable",
        complexity=0,
        cost_basis_ref="synthetic-costs",
        baseline_version_id=None,
        gate_passed=False,
        reason_codes=[],
        flags=[],
        created_at=prepared.eligible_at,
    )
    return [
        BurnSummary(
            schema_version="1",
            epoch_id="synthetic-epoch",
            window="validation",
            trials=0,
            released_values=0,
            queries_used=0,
            query_budget=None,
            status="unthresholded",
        ),
        pilot,
        stock,
        stock.quotas,
        stock.rounding,
        stock_record,
        best,
        prepared,
        subject,
        decision,
        source,
    ]
