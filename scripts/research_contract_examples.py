"""Structural human-driven API examples; no service activation or credentials."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from qfr_core.contracts import research as r
from qfr_core.contracts import transfers as t
from qfr_core.contracts.artifacts import ArtifactReference
from qfr_core.contracts.blackboard import BlackboardRecord, ResearchProgram
from qfr_core.contracts.delivery import DeliveryProposal
from qfr_core.contracts.intake import InputBundle
from qfr_core.contracts.jobs import JobRecord, ResearchBrief


def examples(root: Path, existing):
    def pick(kind):
        return next(value for value in existing if isinstance(value, kind))

    at = datetime(2026, 10, 28, tzinfo=UTC)
    identity = UUID(int=30)
    checkpoint = r.HumanCheckpointRequest(
        checkpoint_id=identity,
        kind="clarification",
        question="Supply required input",
        proposal_id=None,
    )
    status = r.JobStatus(
        job=pick(JobRecord), revision=1, next_action="supply_new_intent", polling_seconds=5
    )
    upload = t.UploadDeclaration(
        operation_key="schema-upload",
        asset_id="schema-asset",
        sha256="0" * 64,
        bytes=1,
        media_type="text/plain",
        provenance="Schema example",
        intended_use="documentation",
        licence="Synthetic",
        source_is_untrusted_data=True,
    )
    transfer = t.UploadStatus(
        upload_id=identity,
        program_id=identity,
        state="staging",
        bytes_received=0,
        expected_bytes=1,
        chunk_bytes=4194304,
        source=None,
        validation="transport_only",
        execution_authorized=False,
        created_at=at,
    )
    return [
        t.IntakeTransportPolicy.model_validate_json(
            (root / "configs/research/intake_transport_v1.json").read_bytes()
        ),
        upload,
        t.MountedImportRequest(declaration=upload, mount_id="source", relative_path="README.txt"),
        t.FinalizeUpload(sha256="0" * 64),
        t.AssetPage(items=[transfer], next_after_id=None, has_more=False),
        r.ResearchApiPolicy.model_validate_json(
            (root / "configs/research/api_v1.json").read_bytes()
        ),
        r.ProgramCreate(
            program_id=identity, name="Schema example", charter={"purpose": "research"}
        ),
        r.ProgramPage(items=[pick(ResearchProgram)], next_after_id=None, has_more=False),
        r.DatasetRegistrationRequest(registration_id="0" * 64),
        r.BaselineRegistrationRequest(
            artifact=ArtifactReference(artifact_version_id=str(identity), content_hash="0" * 64)
        ),
        r.ProtocolProposal(
            proposal_id=identity,
            program_id=identity,
            objective="Propose a comparison",
            constraints=["Preserve original rules"],
            proposed_public_card_ref=None,
            authoritative=False,
        ),
        r.JobAdmission(
            idempotency_key="schema-example",
            input_bundle=pick(InputBundle),
            brief=pick(ResearchBrief),
        ),
        r.InputValidation(
            readiness="needs_input",
            unresolved_requirements=["Dataset required"],
            data_refs_verified=[],
            baseline_refs_verified=[],
            source_assets_verified=[],
            runnable=False,
        ),
        r.JobPage(items=[status], next_after_id=None, has_more=False),
        r.JobControl(operation_key="schema-pause", expected_revision=1, action="pause"),
        r.DeliveryProposalRequest(
            operation_key="schema-proposal", expected_revision=1, proposal=pick(DeliveryProposal)
        ),
        r.DeliveryReceiptRequest(
            operation_key="schema-receipt",
            expected_revision=1,
            receipt_id=identity,
            proposal_id=identity,
        ),
        r.HumanCheckpointRecord(
            request=checkpoint,
            job_id=identity,
            state="open",
            created_by="schema-example",
            created_at=at,
            answer=None,
            answered_by=None,
            answered_at=None,
        ),
        r.HumanCheckpointAnswer(
            operation_key="schema-answer", answer="Clarification", decision=None
        ),
        r.BlackboardPage(items=[pick(BlackboardRecord)], next_after_id=None, has_more=False),
        r.DeliveryExportRequest(operation_key="schema-export", shortlist_only=False),
        r.DeliveryExportReference(
            export_id=identity,
            job_id=identity,
            manifest_sha256="0" * 64,
            archive_sha256="0" * 64,
            archive_bytes=1,
            download_path=f"v1/exports/{identity}/download",
        ),
    ]
