"""The five v1 kind plugins; Stage 3 implements the screening stage only.

Release mappings are fixed status projections, not a release engine or endpoint.
Only a future authorized release policy may publish them.
"""

from dataclasses import dataclass
from typing import Literal

from qfr_core.contracts.artifacts import DataProductPayload, DocumentImplementation, StrategyPayload
from qfr_core.contracts.enums import ArtifactKind, ReasonCode
from qfr_core.contracts.execution import RunnerInput, RunnerOutput
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.contracts.reports import StatusRelease

from qfr_eval.sandbox.runner import ExecutionResult
from qfr_eval.screening.adapters import OutputAdapter, replay_strategy
from qfr_eval.screening.causality import run_probes
from qfr_eval.screening.documents import ReleasedEvidence, check_data_document, check_note
from qfr_eval.screening.execution import PreparedExecution
from qfr_eval.screening.models import KindAdapterProfile, ScreeningExecutionPolicy
from qfr_eval.screening.pilot import PilotOutputError
from qfr_eval.screening.records import ScreeningOutcome, ScreeningRecord


def failed_outcome(
    artifact: PublishedArtifact,
    code: ReasonCode,
    *,
    first: ExecutionResult | None = None,
) -> ScreeningOutcome:
    mode = artifact.manifest.implementation.type
    return ScreeningOutcome(
        schema_version="1",
        kind=artifact.manifest.kind,
        execution="dsl" if mode == "dsl" else "document" if mode == "document" else "sandbox",
        status="insufficient_data" if code == ReasonCode.LOW_COVERAGE else "failed",
        reason_codes=[code],
        coverage=None,
        causality=None,
        output_sha256=first.output_sha256 if first else None,
        document_checks={},
    )


@dataclass(frozen=True)
class KindPlugin:
    kind: ArtifactKind
    stages: tuple[str, ...] = ("screening",)

    def eligibility(
        self, artifact: PublishedArtifact, profile: KindAdapterProfile
    ) -> ReasonCode | None:
        manifest = artifact.manifest
        if manifest.kind != self.kind:
            return ReasonCode.KIND_UNSUPPORTED
        if self.kind == ArtifactKind.RESEARCH_NOTE:
            return (
                None
                if isinstance(manifest.implementation, DocumentImplementation)
                else ReasonCode.KIND_UNSUPPORTED
            )
        if profile.adapter == "pilot_rotation_v1" and self.kind not in (
            ArtifactKind.FACTOR,
            ArtifactKind.MODEL,
        ):
            return ReasonCode.KIND_UNSUPPORTED
        if self.kind == ArtifactKind.STRATEGY:
            payload = manifest.payload
            assert isinstance(payload, StrategyPayload)
            if (
                payload.cost_policy_ref != profile.strategy_cost_policy_ref
                or payload.execution_prices_ref != "next_close/1"
                or payload.rebalance_timing
                != "each declared observation; next authorized execution price"
                or payload.position_state_rules
                not in (
                    "equal weights over declared contemporaneous eligible universe",
                    "long_only_target_weights_with_cash/1",
                )
            ):
                return ReasonCode.DECLARATION_MISMATCH
        if self.kind == ArtifactKind.DATA_PRODUCT:
            payload = manifest.payload
            assert isinstance(payload, DataProductPayload)
            if (
                payload.dataset_manifest_ref != "authorized-input-prices"
                or payload.deterministic_check_refs != [profile.data_product_check]
                or payload.output_schema_ref != "RunnerOutput/1"
            ):
                return ReasonCode.DECLARATION_MISMATCH
        return None

    def run(
        self,
        stage: str,
        artifact: PublishedArtifact,
        *,
        adapter: OutputAdapter,
        execution_policy: ScreeningExecutionPolicy,
        development: RunnerInput,
        probes: RunnerInput | None,
        prepared: PreparedExecution | None,
        first: ExecutionResult | None,
        document: bytes | None,
        released: ReleasedEvidence,
    ) -> tuple[ScreeningOutcome, RunnerOutput | None]:
        if stage not in self.stages:
            raise ValueError("kind stage is not implemented in Stage 3")
        reason = self.eligibility(artifact, adapter.profile)
        if reason:
            return failed_outcome(artifact, reason), None
        if self.kind == ArtifactKind.RESEARCH_NOTE:
            if document is None:
                return failed_outcome(artifact, ReasonCode.SCHEMA_INVALID), None
            return check_note(artifact, document, execution_policy, released), None
        if isinstance(artifact.manifest.implementation, DocumentImplementation):
            if self.kind != ArtifactKind.DATA_PRODUCT or document is None:
                return failed_outcome(artifact, ReasonCode.KIND_UNSUPPORTED), None
            return check_data_document(artifact, document, development, adapter, execution_policy)
        if prepared is None or first is None:
            raise ValueError("executable kind requires actual prepared output")
        if first.code != "ok" or first.output is None:
            code = (
                ReasonCode.RUNTIME_LIMIT
                if first.code != "failed:invalid_output"
                else ReasonCode.DECLARATION_MISMATCH
            )
            return failed_outcome(artifact, code, first=first), first.output
        try:
            coverage = adapter.quality(first.output, development)
        except PilotOutputError as exc:
            return failed_outcome(artifact, exc.code, first=first), first.output
        if coverage.status != "passed":
            outcome = failed_outcome(artifact, coverage.reason_codes[0], first=first)
            return outcome.model_copy(update={"coverage": coverage}), first.output
        if probes is None:
            raise ValueError("a complete candidate requires authorized probe inputs")
        causality, output = run_probes(
            probes,
            prepared.execute,
            adapter.project,
            adapter.protocol.diagnostics.prefix_cutoffs,
            execution_policy,
            atol=adapter.protocol.atol,
            rtol=adapter.protocol.rtol,
        )
        if output is not None and self.kind == ArtifactKind.STRATEGY:
            replay_strategy(output, probes, adapter.profile)
        reason_codes: list[ReasonCode] = []
        if causality.status != "passed":
            reason_codes = [
                ReasonCode.LOOKAHEAD_DETECTED
                if causality.code == "failed:lookahead"
                else ReasonCode.LOW_COVERAGE
                if causality.status == "insufficient_data"
                else ReasonCode.DECLARATION_MISMATCH
                if causality.code in ("failed:invalid_output", "failed:nondeterministic")
                else ReasonCode.RUNTIME_LIMIT
            ]
        return ScreeningOutcome(
            schema_version="1",
            kind=self.kind,
            execution=prepared.mode,
            status=causality.status,
            reason_codes=reason_codes,
            coverage=coverage,
            causality=causality,
            output_sha256=causality.output_sha256,
            document_checks={},
        ), output

    def release_mapping(self, record: ScreeningRecord) -> tuple[StatusRelease, list[ReasonCode]]:
        if record.outcome.kind != self.kind:
            raise ValueError("kind differs from screening record")
        status: Literal["withheld", "pass", "failed"] = (
            "withheld"
            if record.feedback_disposition == "withheld:budget"
            else "pass"
            if record.outcome.status == "passed"
            else "failed"
        )
        # No candidate-produced text, output tables, private counts or timings.
        reasons = (
            []
            if record.feedback_disposition == "withheld:budget"
            else list(record.outcome.reason_codes)
        )
        return StatusRelease(type="screening", status=status), reasons


PLUGINS = {kind: KindPlugin(kind) for kind in ArtifactKind}
