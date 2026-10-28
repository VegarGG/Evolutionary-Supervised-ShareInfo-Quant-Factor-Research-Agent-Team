"""Typed human-driven HTTP front door; no evaluation control or provider calls."""

import json
import logging
from collections.abc import Callable
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from qfr_core.access import BearerAuthority, ServicePrincipal
from qfr_core.contracts.blackboard import BlackboardRecord, ResearchProgram
from qfr_core.contracts.data import ResearchDatasetRegistration
from qfr_core.contracts.delivery import DeliveryCandidate
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.contracts.research import (
    BaselineRegistrationRequest,
    BlackboardPage,
    DatasetRegistrationRequest,
    DeliveryExportReference,
    DeliveryExportRequest,
    DeliveryProposalRequest,
    DeliveryReceiptRequest,
    HumanCheckpointAnswer,
    HumanCheckpointRecord,
    HumanCheckpointRequest,
    InputValidation,
    JobAdmission,
    JobControl,
    JobPage,
    JobStatus,
    ProgramCreate,
    ProgramPage,
    ProtocolProposal,
)
from qfr_core.service_client import ServiceTransportError
from qfr_core.signatures import SignatureRejected

from qfr_research.api.boundary import ResearchBoundary
from qfr_research.api.errors import (
    InvalidResearchRequest,
    ResearchConflict,
    ResearchNotFound,
    ResearchUnavailable,
)
from qfr_research.api.exports import Exports


def _log(value: dict[str, object]) -> None:
    logging.getLogger("qfr.research.requests").info(json.dumps(value, sort_keys=True))


def principal(request: Request) -> ServicePrincipal:
    value = request.state.principal
    if not isinstance(value, ServicePrincipal):
        raise PermissionError("research authentication required")
    return value


Principal = Annotated[ServicePrincipal, Depends(principal)]


def request_id(request: Request) -> UUID:
    return UUID(request.state.request_id)


def create_app(
    service: Exports,
    *,
    authority: BearerAuthority | None = None,
    request_log: Callable[[dict[str, object]], None] = _log,
) -> FastAPI:
    if authority is not None and authority.config.audience != "research":
        raise ValueError("research requires its own token audience")
    app = FastAPI(title="QFR human-driven research", version="1", docs_url=None, redoc_url=None)
    app.add_middleware(
        ResearchBoundary, authority=authority, policy=service.policy, request_log=request_log
    )

    async def invalid(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "invalid research request"}, status_code=400)

    async def missing(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "research object unavailable"}, status_code=404)

    async def conflict(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "research revision or operation conflict"}, status_code=409)

    async def forbidden(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "research operation not authorized"}, status_code=403)

    async def unavailable(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            {"detail": "research evidence or persistence unavailable"}, status_code=503
        )

    error: type[Exception]
    for error in (InvalidResearchRequest, RequestValidationError, ValueError):
        app.add_exception_handler(error, invalid)
    app.add_exception_handler(ResearchNotFound, missing)
    for error in (ResearchConflict, psycopg.errors.UniqueViolation):
        app.add_exception_handler(error, conflict)
    app.add_exception_handler(PermissionError, forbidden)
    for error in (
        ResearchUnavailable,
        SignatureRejected,
        ServiceTransportError,
        psycopg.Error,
        OSError,
    ):
        app.add_exception_handler(error, unavailable)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.post("/v1/programs", response_model=ResearchProgram)
    def create(value: ProgramCreate, caller: Principal, request: Request) -> ResearchProgram:
        return service.create(caller, value, request_id(request))

    @app.get("/v1/programs", response_model=ProgramPage)
    def programs(caller: Principal, after_id: UUID | None = None, limit: int = 20) -> ProgramPage:
        return service.programs(caller, after=after_id, limit=limit)

    @app.get("/v1/programs/{program_id}", response_model=ResearchProgram)
    def program(program_id: UUID, caller: Principal) -> ResearchProgram:
        return service.get(caller, program_id)

    @app.post("/v1/programs/{program_id}/datasets", response_model=ResearchDatasetRegistration)
    def register_dataset(
        program_id: UUID, value: DatasetRegistrationRequest, caller: Principal, request: Request
    ) -> ResearchDatasetRegistration:
        return service.dataset(caller, program_id, value, request_id(request))

    @app.get(
        "/v1/programs/{program_id}/datasets/{dataset_id}",
        response_model=ResearchDatasetRegistration,
    )
    def dataset(
        program_id: UUID, dataset_id: str, caller: Principal
    ) -> ResearchDatasetRegistration:
        return service.registered_dataset(caller, program_id, dataset_id)

    @app.post("/v1/programs/{program_id}/baselines", response_model=PublishedArtifact)
    def register_baseline(
        program_id: UUID, value: BaselineRegistrationRequest, caller: Principal, request: Request
    ) -> PublishedArtifact:
        return service.baseline(caller, program_id, value, request_id(request))

    @app.get("/v1/programs/{program_id}/baselines/{artifact_id}", response_model=PublishedArtifact)
    def baseline(program_id: UUID, artifact_id: UUID, caller: Principal) -> PublishedArtifact:
        return service.registered_baseline(caller, program_id, artifact_id)

    @app.post("/v1/programs/{program_id}/protocol-proposals", response_model=ProtocolProposal)
    def protocol_proposal(
        program_id: UUID, value: ProtocolProposal, caller: Principal, request: Request
    ) -> ProtocolProposal:
        return service.propose_protocol(caller, program_id, value, request_id(request))

    @app.post("/v1/programs/{program_id}/input-validation", response_model=InputValidation)
    def validate(program_id: UUID, value: JobAdmission, caller: Principal) -> InputValidation:
        return service.validate_input(caller, program_id, value)

    @app.post("/v1/programs/{program_id}/jobs", response_model=JobStatus)
    def submit(
        program_id: UUID, value: JobAdmission, caller: Principal, request: Request
    ) -> JobStatus:
        return service.admit(caller, program_id, value, request_id(request))

    @app.get("/v1/programs/{program_id}/jobs", response_model=JobPage)
    def jobs(
        program_id: UUID, caller: Principal, after_id: UUID | None = None, limit: int = 20
    ) -> JobPage:
        return service.jobs(caller, program_id, after=after_id, limit=limit)

    @app.get("/v1/jobs/{job_id}", response_model=JobStatus)
    def status(job_id: UUID, caller: Principal) -> JobStatus:
        return service.get_job(caller, job_id)

    @app.post("/v1/jobs/{job_id}/control", response_model=JobStatus)
    def control(job_id: UUID, value: JobControl, caller: Principal, request: Request) -> JobStatus:
        return service.control(caller, job_id, value, request_id(request))

    @app.post("/v1/programs/{program_id}/blackboard", response_model=BlackboardRecord)
    def note(
        program_id: UUID, value: BlackboardRecord, caller: Principal, request: Request
    ) -> BlackboardRecord:
        return service.note(caller, program_id, value, request_id(request))

    @app.get("/v1/programs/{program_id}/blackboard", response_model=BlackboardPage)
    def notes(
        program_id: UUID, caller: Principal, after_id: UUID | None = None, limit: int = 20
    ) -> BlackboardPage:
        return service.notes(caller, program_id, after=after_id, limit=limit)

    @app.post("/v1/jobs/{job_id}/checkpoints", response_model=HumanCheckpointRecord)
    def open_checkpoint(
        job_id: UUID, value: HumanCheckpointRequest, caller: Principal, request: Request
    ) -> HumanCheckpointRecord:
        return service.open_checkpoint(caller, job_id, value, request_id(request))

    @app.get("/v1/jobs/{job_id}/checkpoints/{checkpoint_id}", response_model=HumanCheckpointRecord)
    def checkpoint(job_id: UUID, checkpoint_id: UUID, caller: Principal) -> HumanCheckpointRecord:
        return service.get_checkpoint(caller, job_id, checkpoint_id)

    @app.post(
        "/v1/jobs/{job_id}/checkpoints/{checkpoint_id}/answer", response_model=HumanCheckpointRecord
    )
    def answer(
        job_id: UUID,
        checkpoint_id: UUID,
        value: HumanCheckpointAnswer,
        caller: Principal,
        request: Request,
    ) -> HumanCheckpointRecord:
        return service.answer_checkpoint(caller, job_id, checkpoint_id, value, request_id(request))

    @app.post("/v1/jobs/{job_id}/delivery-proposals", response_model=JobStatus)
    def propose_delivery(
        job_id: UUID, value: DeliveryProposalRequest, caller: Principal, request: Request
    ) -> JobStatus:
        return service.propose_delivery(caller, job_id, value, request_id(request))

    @app.get("/v1/jobs/{job_id}/delivery-proposals/{proposal_id}", response_model=DeliveryCandidate)
    def delivery_candidate(job_id: UUID, proposal_id: UUID, caller: Principal) -> DeliveryCandidate:
        return service.delivery_candidate(caller, job_id, proposal_id)

    @app.post("/v1/jobs/{job_id}/delivery-receipts", response_model=JobStatus)
    def accept_receipt(
        job_id: UUID, value: DeliveryReceiptRequest, caller: Principal, request: Request
    ) -> JobStatus:
        return service.accept_receipt(caller, job_id, value, request_id(request))

    @app.post("/v1/jobs/{job_id}/exports", response_model=DeliveryExportReference)
    def export(
        job_id: UUID, value: DeliveryExportRequest, caller: Principal, request: Request
    ) -> DeliveryExportReference:
        return service.export(caller, job_id, value, request_id(request))

    @app.get("/v1/jobs/{job_id}/exports/{export_id}")
    def download(job_id: UUID, export_id: UUID, caller: Principal) -> Response:
        ref, data = service.download(caller, job_id, export_id)
        return Response(
            data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="qfr-{export_id}.zip"',
                "ETag": '"' + ref.archive_sha256 + '"',
                "X-Manifest-SHA256": ref.manifest_sha256,
            },
        )

    return app
