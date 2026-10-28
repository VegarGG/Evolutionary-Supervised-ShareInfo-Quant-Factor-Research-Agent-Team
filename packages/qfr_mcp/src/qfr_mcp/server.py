"""Maintained-SDK Streamable HTTP; durable jobs belong to Research API, not sessions."""

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar
from urllib.parse import urlencode
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel
from qfr_core.access import BearerAuthority, ServicePrincipal
from qfr_core.contracts.blackboard import BlackboardRecord, ResearchProgram
from qfr_core.contracts.data import ResearchDatasetRegistration
from qfr_core.contracts.mcp import MCPReply
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
    ProtocolProposal,
)
from qfr_core.contracts.transfers import (
    AssetPage,
    FinalizeUpload,
    MountedImportRequest,
    UploadDeclaration,
    UploadStatus,
)
from qfr_core.http_transport import BoundedServiceBoundary
from qfr_core.registry_client import RegistryTransportError
from qfr_core.service_client import ServiceTransportError
from qfr_core.signatures import SignatureRejected
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from qfr_mcp.gateway import Gateway

MCPContext = Context[Any, Request]
F = TypeVar("F", bound=Callable[..., Any])


def _log(value: dict[str, object]) -> None:
    logging.getLogger("qfr.mcp.requests").info(json.dumps(value, sort_keys=True))


def _principal(request: Request | None) -> ServicePrincipal:
    value = getattr(request.state, "principal", None) if request is not None else None
    if not isinstance(value, ServicePrincipal) or value.audience != "mcp":
        raise PermissionError("MCP authentication required")
    return value


def create_app(
    gateway: Gateway,
    *,
    authority: BearerAuthority,
    request_log: Callable[[dict[str, object]], None] = _log,
) -> Starlette:
    if authority.config.audience != "mcp":
        raise ValueError("MCP requires its own token audience")
    for binding in authority.config.bindings:
        configured_principal = ServicePrincipal(
            binding.principal, "mcp", frozenset(binding.roles), frozenset(binding.programs)
        )
        for program in binding.programs:
            gateway.backend(
                configured_principal, UUID(program)
            )  # Refuse incomplete or widened role mappings at startup.
    names: set[str] = set()

    async def middleware(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        caller = _principal(ctx.request)
        result = await call_next(ctx)
        if isinstance(result, CallToolResult) and not result.is_error:
            reply = MCPReply.model_validate(result.structured_content)
            result = result.model_copy(
                update={
                    "content": [
                        TextContent(
                            type="text",
                            text=reply.summary
                            + (" Resource: " + reply.resource_uri if reply.resource_uri else ""),
                        )
                    ]
                }
            )
        method = (
            ctx.method
            if ctx.method
            in {
                "initialize",
                "tools/list",
                "tools/call",
                "resources/list",
                "resources/templates/list",
                "resources/read",
                "ping",
                "notifications/initialized",
                "notifications/cancelled",
            }
            else "<other>"
        )
        tool = (ctx.params or {}).get("name")
        request_log(
            dict(
                principal=caller.name,
                at=datetime.now(UTC).isoformat(),
                method=method,
                tool=tool if tool in names else None,
                request_id=str(ctx.request.state.request_id) if ctx.request is not None else None,
            )
        )
        return result

    server = MCPServer(
        "QFR",
        version="0.1.0",
        instructions=(
            "Human-driven research only. Jobs survive disconnects. "
            "No evaluation administration or live model calls."
        ),
        middleware=[middleware],
    )
    readonly = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    write = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    def tool(name: str, *, mutation: bool = False, destructive: bool = False) -> Callable[[F], F]:
        names.add(name)
        hints = write if mutation else readonly
        if destructive:
            hints = ToolAnnotations(
                read_only_hint=False,
                destructive_hint=True,
                idempotent_hint=True,
                open_world_hint=False,
            )

        def register(function: F) -> F:
            server.tool(name=name, annotations=hints)(function)
            return function

        return register

    def caller(ctx: MCPContext, program: UUID, role: str | None = None) -> ServicePrincipal:
        principal = _principal(ctx.request_context.request)
        gateway.backend(principal, program, role=role)
        return principal

    async def invoke(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(function, *args, **kwargs)
        except (ServiceTransportError, RegistryTransportError) as exc:
            raise ToolError(
                f"Required public service refused or unavailable; status={exc.status}"
            ) from None
        except (ValueError, PermissionError, SignatureRejected):
            raise ToolError("Request scope, state or evidence verification refused") from None

    async def research(
        ctx: MCPContext,
        program: UUID,
        model: type[BaseModel],
        method: str,
        path: str,
        value: BaseModel | None = None,
        *,
        role: str | None = None,
        summary: str,
        uri: str | None = None,
    ) -> MCPReply:
        result = await invoke(
            gateway.research,
            caller(ctx, program, role),
            program,
            model,
            method,
            path,
            value,
            role=role,
        )
        return gateway.reply(result, summary, uri=uri)

    @tool("qfr_program_create", mutation=True)
    async def program_create(value: ProgramCreate, ctx: MCPContext) -> MCPReply:
        """Create explicit program context; starts no research or evaluation."""
        return await research(
            ctx,
            value.program_id,
            ResearchProgram,
            "POST",
            "v1/programs",
            value,
            role="research_lead",
            summary="Program recorded",
            uri=f"program://{value.program_id}/0",
        )

    @tool("qfr_program_read")
    async def program_read(program_id: UUID, ctx: MCPContext) -> MCPReply:
        """Read a program charter within the caller's scope."""
        return await research(
            ctx,
            program_id,
            ResearchProgram,
            "GET",
            f"v1/programs/{program_id}",
            summary="Program context",
            uri=f"program://{program_id}/0",
        )

    @tool("qfr_input_validate")
    async def input_validate(program_id: UUID, value: JobAdmission, ctx: MCPContext) -> MCPReply:
        """Validate frozen intent and source/data/baseline references without admitting a job."""
        return await research(
            ctx,
            program_id,
            InputValidation,
            "POST",
            f"v1/programs/{program_id}/input-validation",
            value,
            role="research_lead",
            summary="Input validation result",
        )

    @tool("qfr_dataset_register", mutation=True)
    async def dataset_register(
        program_id: UUID, value: DatasetRegistrationRequest, ctx: MCPContext
    ) -> MCPReply:
        """Register an existing trusted research catalog ID; does not build or fetch data."""
        return await research(
            ctx,
            program_id,
            ResearchDatasetRegistration,
            "POST",
            f"v1/programs/{program_id}/datasets",
            value,
            role="research_lead",
            summary="Research dataset registered",
        )

    @tool("qfr_baseline_register", mutation=True)
    async def baseline_register(
        program_id: UUID, value: BaselineRegistrationRequest, ctx: MCPContext
    ) -> MCPReply:
        """Register an immutable published Registry baseline."""
        return await research(
            ctx,
            program_id,
            PublishedArtifact,
            "POST",
            f"v1/programs/{program_id}/baselines",
            value,
            role="research_lead",
            summary="Baseline registered",
            uri=f"artifact://{program_id}/{value.artifact.artifact_version_id}/0",
        )

    @tool("qfr_protocol_propose", mutation=True)
    async def protocol_propose(
        program_id: UUID, value: ProtocolProposal, ctx: MCPContext
    ) -> MCPReply:
        """Record a non-authoritative proposal; cannot activate or edit evaluator protocols."""
        return await research(
            ctx,
            program_id,
            ProtocolProposal,
            "POST",
            f"v1/programs/{program_id}/protocol-proposals",
            value,
            role="research_lead",
            summary="Non-authoritative protocol proposal recorded",
        )

    @tool("qfr_research_submit", mutation=True)
    async def submit(program_id: UUID, value: JobAdmission, ctx: MCPContext) -> MCPReply:
        """Admit durable research with a caller key; repeating a lost submit recovers the job."""
        result = await invoke(
            gateway.research,
            caller(ctx, program_id, "research_lead"),
            program_id,
            JobStatus,
            "POST",
            f"v1/programs/{program_id}/jobs",
            value,
            role="research_lead",
        )
        return gateway.reply(
            result,
            f"Job {result.job.job_id}: {result.job.state.value}; "
            f"next={result.next_action}; poll={result.polling_seconds}s",
            uri=f"job://{program_id}/{result.job.job_id}/0",
        )

    @tool("qfr_research_status")
    async def status(program_id: UUID, job_id: UUID, ctx: MCPContext) -> MCPReply:
        """Read status promptly; request cancellation never cancels the durable job."""
        return await research(
            ctx,
            program_id,
            JobStatus,
            "GET",
            f"v1/jobs/{job_id}",
            summary="Durable research status",
            uri=f"job://{program_id}/{job_id}/0",
        )

    @tool("qfr_research_jobs")
    async def jobs(
        program_id: UUID, ctx: MCPContext, after_id: UUID | None = None, limit: int | None = None
    ) -> MCPReply:
        """Page durable jobs in this program, including explicit waiting states."""
        size = limit if limit is not None else gateway.policy.default_page_size
        gateway.page_size(size)
        query = urlencode({"limit": size, **({"after_id": str(after_id)} if after_id else {})})
        return await research(
            ctx,
            program_id,
            JobPage,
            "GET",
            f"v1/programs/{program_id}/jobs?{query}",
            summary="Durable job page",
            uri=f"jobs://{program_id}/{after_id or 'start'}/{size}/0",
        )

    @tool("qfr_research_control", mutation=True, destructive=True)
    async def control(
        program_id: UUID, job_id: UUID, value: JobControl, ctx: MCPContext
    ) -> MCPReply:
        """Control research only, with an idempotency key and expected revision."""
        return await research(
            ctx,
            program_id,
            JobStatus,
            "POST",
            f"v1/jobs/{job_id}/control",
            value,
            role="research_lead",
            summary="Research control recorded",
            uri=f"job://{program_id}/{job_id}/0",
        )

    @tool("qfr_blackboard_read")
    async def blackboard_read(
        program_id: UUID,
        ctx: MCPContext,
        after_id: UUID | None = None,
        limit: int = gateway.policy.default_page_size,
    ) -> MCPReply:
        """Read a bounded page of human research notes and immutable references."""
        gateway.page_size(limit)
        query = urlencode({"limit": limit, **({"after_id": str(after_id)} if after_id else {})})
        return await research(
            ctx,
            program_id,
            BlackboardPage,
            "GET",
            f"v1/programs/{program_id}/blackboard?{query}",
            summary="Blackboard page",
            uri=f"blackboard://{program_id}/{after_id or 'start'}/{limit}/0",
        )

    @tool("qfr_blackboard_record", mutation=True)
    async def blackboard_record(
        program_id: UUID, value: BlackboardRecord, ctx: MCPContext
    ) -> MCPReply:
        """Record an attributed human note; cited artifacts/reports must resolve."""
        return await research(
            ctx,
            program_id,
            BlackboardRecord,
            "POST",
            f"v1/programs/{program_id}/blackboard",
            value,
            role="research_lead",
            summary="Human research note recorded",
        )

    @tool("qfr_checkpoint_open", mutation=True)
    async def checkpoint_open(
        program_id: UUID, job_id: UUID, value: HumanCheckpointRequest, ctx: MCPContext
    ) -> MCPReply:
        """Persist a clarification or a request to approve the exact active delivery proposal."""
        return await research(
            ctx,
            program_id,
            HumanCheckpointRecord,
            "POST",
            f"v1/jobs/{job_id}/checkpoints",
            value,
            role="research_lead",
            summary="Human checkpoint opened",
        )

    @tool("qfr_checkpoint_read")
    async def checkpoint_read(
        program_id: UUID, job_id: UUID, checkpoint_id: UUID, ctx: MCPContext
    ) -> MCPReply:
        """Read the exact durable checkpoint and its recorded answer."""
        return await research(
            ctx,
            program_id,
            HumanCheckpointRecord,
            "GET",
            f"v1/jobs/{job_id}/checkpoints/{checkpoint_id}",
            summary="Human checkpoint",
        )

    @tool("qfr_checkpoint_answer", mutation=True)
    async def checkpoint_answer(
        program_id: UUID,
        job_id: UUID,
        checkpoint_id: UUID,
        value: HumanCheckpointAnswer,
        ctx: MCPContext,
    ) -> MCPReply:
        """Record an immutable answer under a separately authorized human-reviewer identity."""
        return await research(
            ctx,
            program_id,
            HumanCheckpointRecord,
            "POST",
            f"v1/jobs/{job_id}/checkpoints/{checkpoint_id}/answer",
            value,
            role="human_reviewer",
            summary="Human answer recorded",
        )

    @tool("qfr_delivery_propose", mutation=True)
    async def delivery_propose(
        program_id: UUID, job_id: UUID, value: DeliveryProposalRequest, ctx: MCPContext
    ) -> MCPReply:
        """Propose exact immutable outputs; does not trigger or control independent evaluation."""
        return await research(
            ctx,
            program_id,
            JobStatus,
            "POST",
            f"v1/jobs/{job_id}/delivery-proposals",
            value,
            role="research_lead",
            summary="Delivery proposal recorded",
            uri=f"job://{program_id}/{job_id}/0",
        )

    @tool("qfr_delivery_accept", mutation=True)
    async def delivery_accept(
        program_id: UUID, job_id: UUID, value: DeliveryReceiptRequest, ctx: MCPContext
    ) -> MCPReply:
        """Accept an already released independent receipt ID; verify its signature again here."""
        return await research(
            ctx,
            program_id,
            JobStatus,
            "POST",
            f"v1/jobs/{job_id}/delivery-receipts",
            value,
            role="research_lead",
            summary="Independent delivery receipt checked",
            uri=f"job://{program_id}/{job_id}/0",
        )

    @tool("qfr_artifact_read")
    async def artifact_read(program_id: UUID, artifact_id: UUID, ctx: MCPContext) -> MCPReply:
        """Read a hash-verified published manifest; executes nothing."""
        value = await invoke(gateway.artifact, caller(ctx, program_id), program_id, artifact_id)
        return gateway.reply(
            value, "Verified Registry manifest", uri=f"artifact://{program_id}/{artifact_id}/0"
        )

    @tool("qfr_artifacts_list")
    async def artifacts_list(
        program_id: UUID, ctx: MCPContext, since_seq: int = 0, limit: int | None = None
    ) -> MCPReply:
        """Page immutable Registry manifests in this program; executes no payload."""
        size = limit if limit is not None else gateway.policy.default_page_size
        value = await invoke(
            gateway.artifact_page,
            caller(ctx, program_id),
            program_id,
            since_seq=since_seq,
            limit=size,
        )
        return gateway.reply(
            value, "Published artifact page", uri=f"artifacts://{program_id}/{since_seq}/{size}/0"
        )

    @tool("qfr_report_read")
    async def report_read(program_id: UUID, report_id: UUID, ctx: MCPContext) -> MCPReply:
        """Read only released evidence, independently checking its configured signing key."""
        value = await invoke(gateway.report, caller(ctx, program_id), program_id, report_id)
        return gateway.reply(
            value,
            "Verified released report",
            uri=f"report://{program_id}/{report_id}/0",
            official=True,
        )

    @tool("qfr_reports_list")
    async def reports_list(
        program_id: UUID,
        ctx: MCPContext,
        after_id: UUID | None = None,
        limit: int = gateway.policy.default_page_size,
    ) -> MCPReply:
        """Read a bounded cursor page; every returned report must verify independently."""
        value = await invoke(
            gateway.report_page, caller(ctx, program_id), program_id, after=after_id, limit=limit
        )
        return gateway.reply(
            value,
            "Verified released report page",
            uri=f"reports://{program_id}/{after_id or 'start'}/{limit}/0",
            official=True,
        )

    @tool("qfr_delivery_export", mutation=True)
    async def delivery_export(
        program_id: UUID, job_id: UUID, value: DeliveryExportRequest, ctx: MCPContext
    ) -> MCPReply:
        """Verify an accepted export or shortlist view; returns references, not package bytes."""
        principal = caller(ctx, program_id, "research_lead")
        reference = await invoke(
            gateway.research,
            principal,
            program_id,
            DeliveryExportReference,
            "POST",
            f"v1/jobs/{job_id}/exports",
            value,
            role="research_lead",
        )
        await invoke(
            gateway.download, principal, program_id, job_id, reference.export_id, reference
        )
        public = reference.model_copy(
            update={
                "download_path": (
                    f"/v1/programs/{program_id}/jobs/{job_id}/exports/{reference.export_id}"
                )
            }
        )
        return gateway.reply(
            public,
            "Export verified; download separately with the same MCP credential",
            official=True,
        )

    @tool("qfr_upload_prepare", mutation=True)
    async def upload_prepare(
        program_id: UUID, value: UploadDeclaration, ctx: MCPContext
    ) -> MCPReply:
        """Reserve bounded quarantine transport; send bytes through authenticated HTTP chunks."""
        result = await invoke(
            gateway.intake,
            caller(ctx, program_id, "research_lead"),
            program_id,
            UploadStatus,
            "POST",
            f"v1/programs/{program_id}/uploads",
            value,
            write=True,
        )
        return gateway.reply(
            result,
            f"Upload {result.upload_id}; binary chunk endpoint "
            f"/v1/programs/{program_id}/uploads/{result.upload_id}/chunks",
        )

    @tool("qfr_upload_status")
    async def upload_status(program_id: UUID, upload_id: UUID, ctx: MCPContext) -> MCPReply:
        """Read resumable transport status; never exposes source bytes."""
        result = await invoke(
            gateway.intake,
            caller(ctx, program_id),
            program_id,
            UploadStatus,
            "GET",
            f"v1/programs/{program_id}/uploads/{upload_id}",
        )
        return gateway.reply(result, "Source transport status")

    @tool("qfr_sources_list")
    async def sources_list(
        program_id: UUID, ctx: MCPContext, after_id: UUID | None = None, limit: int | None = None
    ) -> MCPReply:
        """Page source transport metadata; staging is not snapshot readiness."""
        size = limit if limit is not None else gateway.policy.default_page_size
        gateway.page_size(size)
        query = urlencode({"limit": size, **({"after_id": str(after_id)} if after_id else {})})
        result = await invoke(
            gateway.intake,
            caller(ctx, program_id),
            program_id,
            AssetPage,
            "GET",
            f"v1/programs/{program_id}/assets?{query}",
        )
        return gateway.reply(
            result,
            "Source metadata page",
            uri=f"sources://{program_id}/{after_id or 'start'}/{size}/0",
        )

    @tool("qfr_upload_finalize", mutation=True)
    async def upload_finalize(
        program_id: UUID, upload_id: UUID, value: FinalizeUpload, ctx: MCPContext
    ) -> MCPReply:
        """Validate transport integrity; a rejected or incomplete source remains unusable."""
        result = await invoke(
            gateway.intake,
            caller(ctx, program_id, "research_lead"),
            program_id,
            UploadStatus,
            "POST",
            f"v1/programs/{program_id}/uploads/{upload_id}/finalize",
            value,
            write=True,
        )
        return gateway.reply(
            result, f"Source transport state: {result.state}; execution remains unauthorized"
        )

    @tool("qfr_source_import", mutation=True)
    async def source_import(
        program_id: UUID, value: MountedImportRequest, ctx: MCPContext
    ) -> MCPReply:
        """Import a regular file from an explicit read-only mapping, not a host path or URL."""
        result = await invoke(
            gateway.intake,
            caller(ctx, program_id, "research_lead"),
            program_id,
            UploadStatus,
            "POST",
            f"v1/programs/{program_id}/imports",
            value,
            write=True,
        )
        return gateway.reply(
            result,
            f"Source transport state: {result.state}; "
            "snapshot building requires separate authorization",
        )

    @server.resource("artifact://{program_id}/{artifact_id}/{page}", mime_type="application/json")
    async def artifact_resource(
        program_id: str, artifact_id: str, page: int, ctx: MCPContext
    ) -> str:
        program = UUID(program_id)
        value = await invoke(gateway.artifact, caller(ctx, program), program, UUID(artifact_id))
        return gateway.document_page(
            value, f"artifact://{program_id}/{artifact_id}/{page}", page
        ).model_dump_json()

    @server.resource("report://{program_id}/{report_id}/{page}", mime_type="application/json")
    async def report_resource(program_id: str, report_id: str, page: int, ctx: MCPContext) -> str:
        program = UUID(program_id)
        value = await invoke(gateway.report, caller(ctx, program), program, UUID(report_id))
        return gateway.document_page(
            value, f"report://{program_id}/{report_id}/{page}", page, official=True
        ).model_dump_json()

    @server.resource("job://{program_id}/{job_id}/{page}", mime_type="application/json")
    async def job_resource(program_id: str, job_id: str, page: int, ctx: MCPContext) -> str:
        program, identity = UUID(program_id), UUID(job_id)
        value = await invoke(
            gateway.research, caller(ctx, program), program, JobStatus, "GET", f"v1/jobs/{identity}"
        )
        return gateway.document_page(
            value, f"job://{program_id}/{job_id}/{page}", page
        ).model_dump_json()

    @server.resource("program://{program_id}/{page}", mime_type="application/json")
    async def program_resource(program_id: str, page: int, ctx: MCPContext) -> str:
        program = UUID(program_id)
        value = await invoke(
            gateway.research,
            caller(ctx, program),
            program,
            ResearchProgram,
            "GET",
            f"v1/programs/{program}",
        )
        return gateway.document_page(
            value, f"program://{program_id}/{page}", page
        ).model_dump_json()

    @server.resource("reports://{program_id}/{after}/{limit}/{page}", mime_type="application/json")
    async def reports_resource(
        program_id: str, after: str, limit: int, page: int, ctx: MCPContext
    ) -> str:
        program = UUID(program_id)
        value = await invoke(
            gateway.report_page,
            caller(ctx, program),
            program,
            after=UUID(after) if after != "start" else None,
            limit=limit,
        )
        return gateway.document_page(
            value, f"reports://{program_id}/{after}/{limit}/{page}", page, official=True
        ).model_dump_json()

    @server.resource(
        "blackboard://{program_id}/{after}/{limit}/{page}", mime_type="application/json"
    )
    async def blackboard_resource(
        program_id: str, after: str, limit: int, page: int, ctx: MCPContext
    ) -> str:
        program = UUID(program_id)
        gateway.page_size(limit)
        query = urlencode(
            {"limit": limit, **({"after_id": str(UUID(after))} if after != "start" else {})}
        )
        value = await invoke(
            gateway.research,
            caller(ctx, program),
            program,
            BlackboardPage,
            "GET",
            f"v1/programs/{program}/blackboard?{query}",
        )
        return gateway.document_page(
            value, f"blackboard://{program_id}/{after}/{limit}/{page}", page
        ).model_dump_json()

    @server.resource("jobs://{program_id}/{after}/{limit}/{page}", mime_type="application/json")
    async def jobs_resource(
        program_id: str, after: str, limit: int, page: int, ctx: MCPContext
    ) -> str:
        program = UUID(program_id)
        gateway.page_size(limit)
        query = urlencode(
            {"limit": limit, **({"after_id": str(UUID(after))} if after != "start" else {})}
        )
        value = await invoke(
            gateway.research,
            caller(ctx, program),
            program,
            JobPage,
            "GET",
            f"v1/programs/{program}/jobs?{query}",
        )
        return gateway.document_page(
            value, f"jobs://{program_id}/{after}/{limit}/{page}", page
        ).model_dump_json()

    @server.resource(
        "artifacts://{program_id}/{since}/{limit}/{page}", mime_type="application/json"
    )
    async def artifacts_resource(
        program_id: str, since: int, limit: int, page: int, ctx: MCPContext
    ) -> str:
        program = UUID(program_id)
        value = await invoke(
            gateway.artifact_page, caller(ctx, program), program, since_seq=since, limit=limit
        )
        return gateway.document_page(
            value, f"artifacts://{program_id}/{since}/{limit}/{page}", page
        ).model_dump_json()

    @server.resource("sources://{program_id}/{after}/{limit}/{page}", mime_type="application/json")
    async def sources_resource(
        program_id: str, after: str, limit: int, page: int, ctx: MCPContext
    ) -> str:
        program = UUID(program_id)
        gateway.page_size(limit)
        query = urlencode(
            {"limit": limit, **({"after_id": str(UUID(after))} if after != "start" else {})}
        )
        value = await invoke(
            gateway.intake,
            caller(ctx, program),
            program,
            AssetPage,
            "GET",
            f"v1/programs/{program}/assets?{query}",
        )
        return gateway.document_page(
            value, f"sources://{program_id}/{after}/{limit}/{page}", page
        ).model_dump_json()

    app = server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        max_request_body_size=gateway.policy.max_request_bytes,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=gateway.policy.allowed_hosts,
            allowed_origins=gateway.policy.allowed_origins,
        ),
    )

    async def download(request: Request) -> Response:
        try:
            program, job, identity = (
                UUID(request.path_params[k]) for k in ("program_id", "job_id", "export_id")
            )
            raw = await asyncio.to_thread(
                gateway.download, _principal(request), program, job, identity
            )
            return Response(
                raw,
                media_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="qfr-{identity}.zip"',
                    "ETag": '"' + hashlib.sha256(raw).hexdigest() + '"',
                },
            )
        except (ValueError, PermissionError, ServiceTransportError, RegistryTransportError):
            return JSONResponse({"detail": "verified export unavailable"}, status_code=503)

    async def chunk(request: Request) -> Response:
        try:
            program, identity = (UUID(request.path_params[k]) for k in ("program_id", "upload_id"))
            backend = gateway.backend(_principal(request), program, role="research_lead")
            offsets, hashes = (
                request.headers.getlist("x-chunk-offset"),
                request.headers.getlist("x-chunk-sha256"),
            )
            data = await request.body()
            if (
                len(offsets) != 1
                or len(hashes) != 1
                or len(offsets[0]) > 20
                or not offsets[0].isdigit()
                or len(data) > gateway.policy.upload_chunk_bytes
                or hashlib.sha256(data).hexdigest() != hashes[0]
            ):
                raise ValueError("invalid chunk")
            _, raw = await asyncio.to_thread(
                backend.intake.request,
                "POST",
                f"v1/programs/{program}/uploads/{identity}/chunks",
                body=data,
                chunk_offset=int(offsets[0]),
            )
            result = UploadStatus.model_validate_json(raw)
            if result.program_id != program or result.upload_id != identity:
                raise ValueError("source response differs")
            return JSONResponse(result.model_dump(mode="json"))
        except (ValueError, PermissionError, ServiceTransportError):
            return JSONResponse({"detail": "source chunk refused or unavailable"}, status_code=400)

    async def health(request: Request) -> Response:
        return JSONResponse({"status": "alive"})

    app.router.routes.extend(
        [
            Route("/healthz", health, methods=["GET"]),
            Route(
                "/v1/programs/{program_id}/jobs/{job_id}/exports/{export_id}",
                download,
                methods=["GET"],
            ),
            Route("/v1/programs/{program_id}/uploads/{upload_id}/chunks", chunk, methods=["POST"]),
        ]
    )
    app.add_middleware(
        BoundedServiceBoundary,
        authority=authority,
        audience="mcp",
        maximum_bytes=max(gateway.policy.max_request_bytes, gateway.policy.upload_chunk_bytes),
        timeout_seconds=gateway.policy.request_body_timeout_seconds,
        request_log=request_log,
        binary_route=lambda scope: scope["path"].endswith("/chunks"),
    )
    return app
