"""The front door's research-api client (PLAN Section 16.7). It holds the control token
only; research-api never sees owner-grade evidence and the front door never runs
research tools (INV-14)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import JsonValue
from qfr_core.contracts import AlertAckRequest
from qfr_core.research_api import (
    CloseRequest,
    CostReport,
    DeliverablePage,
    DeliverableView,
    GenerationPage,
    JobEventPage,
    JobPage,
    JobView,
    JobWait,
    ProbeReport,
    ProviderAlert,
    ProviderAlertPage,
    ResearchLineage,
    ResearchSummary,
    SteerRequest,
    SubmitJobRequest,
    SubmitJobResponse,
    TraceExportBundle,
    TraceView,
)

from qfr_mcp.api_client import ApiClient

Control = Literal["pause", "resume", "cancel"]
# Submitting publishes the seed expressions through registry-api before it answers.
SUBMIT_TIMEOUT_SECONDS = 60.0


class ResearchClient(ApiClient):
    backend = "research-api"

    async def submit(self, request: SubmitJobRequest) -> SubmitJobResponse:
        body = request.model_dump(mode="json")
        return await self._model(
            SubmitJobResponse, "POST", "/v1/jobs", body=body, timeout=SUBMIT_TIMEOUT_SECONDS
        )

    async def jobs(self, state: str | None, limit: int, cursor: UUID | None) -> JobPage:
        params = {"state": state, "limit": limit, "cursor": cursor}
        return await self._model(JobPage, "GET", "/v1/jobs", params=params)

    async def job(self, job_id: UUID) -> JobView:
        return await self._model(JobView, "GET", f"/v1/jobs/{job_id}")

    async def versions(self, job_id: UUID) -> list[UUID]:
        _, data = await self._call("GET", f"/v1/jobs/{job_id}/versions")
        return [UUID(v) for v in data["version_ids"]]

    async def events(self, job_id: UUID, after_seq: int, limit: int) -> JobEventPage:
        params = {"after_seq": after_seq, "limit": limit}
        return await self._model(JobEventPage, "GET", f"/v1/jobs/{job_id}/events", params=params)

    async def wait(self, job_id: UUID, timeout_s: float, state: str | None) -> JobWait:
        params = {"timeout_s": timeout_s, "state": state}
        return await self._model(
            JobWait, "GET", f"/v1/jobs/{job_id}/wait", params=params, timeout=timeout_s + 30
        )

    async def steer(self, job_id: UUID, request: SteerRequest) -> JobView:
        body = request.model_dump(mode="json")
        return await self._model(JobView, "POST", f"/v1/jobs/{job_id}/steer", body=body)

    async def control(self, job_id: UUID, action: Control) -> JobView:
        return await self._model(JobView, "POST", f"/v1/jobs/{job_id}/{action}")

    async def close(self, job_id: UUID, request: CloseRequest) -> JobView:
        body = request.model_dump(mode="json")
        return await self._model(JobView, "POST", f"/v1/jobs/{job_id}/close", body=body)

    async def generations(self, program_id: UUID) -> GenerationPage:
        return await self._model(GenerationPage, "GET", f"/v1/programs/{program_id}/generations")

    async def deliverables(self, job_id: UUID) -> DeliverablePage:
        return await self._model(DeliverablePage, "GET", f"/v1/jobs/{job_id}/deliverables")

    async def deliverable(self, deliverable_id: UUID, mark_fetched: bool) -> DeliverableView:
        params = {"mark_fetched": str(mark_fetched).lower()}
        path = f"/v1/deliverables/{deliverable_id}"
        return await self._model(DeliverableView, "GET", path, params=params)

    async def trace(self, version_id: UUID | None, candidate_id: UUID | None) -> TraceView:
        path = (
            f"/v1/trace/{version_id}"
            if version_id is not None
            else f"/v1/trace/candidates/{candidate_id}"
        )
        return await self._model(TraceView, "GET", path)

    async def trace_export(self, version_id: UUID) -> TraceExportBundle:
        return await self._model(TraceExportBundle, "GET", f"/v1/trace/{version_id}/export")

    async def lineage(self, version_id: UUID) -> ResearchLineage:
        return await self._model(ResearchLineage, "GET", f"/v1/lineage/{version_id}")

    async def costs(
        self,
        start: datetime | None,
        end: datetime | None,
        group_by: list[str] | None,
        job_id: UUID | None,
    ) -> CostReport:
        params: dict[str, Any] = {
            "from": start.isoformat() if start else None,
            "to": end.isoformat() if end else None,
            "group_by": group_by,
            "job_id": job_id,
        }
        return await self._model(CostReport, "GET", "/v1/costs", params=params)

    async def summary(self) -> ResearchSummary:
        return await self._model(ResearchSummary, "GET", "/v1/summary")

    async def probe(self) -> ProbeReport | None:
        _, data = await self._call("GET", "/v1/probes/latest")
        return None if data is None else ProbeReport.model_validate(data)

    async def control_all(self, paused: bool) -> dict[str, JsonValue]:
        path = "/v1/programs/pause_all" if paused else "/v1/programs/resume_all"
        _, data = await self._call("POST", path)
        return dict(data)

    async def alerts(self, state: str | None, kind: str | None, limit: int) -> ProviderAlertPage:
        params = {"state": state, "kind": kind, "limit": limit}
        return await self._model(ProviderAlertPage, "GET", "/v1/alerts", params=params)

    async def acknowledge_alert(self, alert_id: UUID, request: AlertAckRequest) -> ProviderAlert:
        path = f"/v1/alerts/{alert_id}/acknowledge"
        return await self._model(ProviderAlert, "POST", path, body=request.model_dump(mode="json"))
