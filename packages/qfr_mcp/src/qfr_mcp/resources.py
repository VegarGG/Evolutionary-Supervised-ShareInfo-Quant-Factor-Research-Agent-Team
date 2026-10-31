"""MCP resources and prompts of Phase 4 (PLAN Section 13.8).

Resources are read-only JSON documents a host agent can cache: the active cards, the
pools, a job, a deliverable (read without marking it fetched), a trace and the public
schemas. The host-agent guide resource arrives with the guide in Phase 7 (P7.5).
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from pydantic import JsonValue
from qfr_core.contracts import PUBLIC_CONTRACTS

from qfr_mcp.api_client import DownstreamRefused, DownstreamUnavailable
from qfr_mcp.job_tools import JobToolDeps
from qfr_mcp.prompts import BRIEF, REPORT_DELIVERABLE

JSON = "application/json"
# Resource names (Section 13.8) mapped to the public contracts they publish.
SCHEMAS = {
    "brief": "research_brief",
    "deliverable": "deliverable",
    "approval": "approval_record",
    "trace": "trace_export",
    "trace_step": "trace_step",
    "iteration_history": "iteration_history",
    "pool_import": "pool_import",
}
PoolPage = Callable[[Literal["factor", "strategy"]], Awaitable[dict[str, JsonValue]]]


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2)


def register(server: FastMCP, deps: JobToolDeps, pool_page: PoolPage) -> None:
    async def card(kind: Literal["protocol", "policy"]) -> str:
        if deps.feedback is not None:
            try:
                active = await deps.feedback.card(kind)
                view = active.model_dump(mode="json")
                return _dump({"state": "active", "ref": view["ref"], "card": view["card"]})
            except (DownstreamUnavailable, DownstreamRefused):
                pass
        bundled = json.loads((deps.config_dir / "public_cards.json").read_text())
        return _dump({"state": "preview_not_activated", "card": bundled[kind]})

    @server.resource(
        "qfr://cards/protocol",
        name="protocol-card",
        description="The active public protocol card (fields, operators, horizons, gates).",
        mime_type=JSON,
    )
    async def protocol_card() -> str:
        return await card("protocol")

    @server.resource(
        "qfr://cards/policy",
        name="policy-card",
        description=(
            "The active public release-policy card (release timing, rounding, coarsening). "
            "Reports are released as soon as the evaluator records them."
        ),
        mime_type=JSON,
    )
    async def policy_card() -> str:
        return await card("policy")

    @server.resource(
        "qfr://pools/factors",
        name="factor-pool",
        description="The first page of the factor pool with evidence tiers (qfr.pool.list).",
        mime_type=JSON,
    )
    async def factor_pool() -> str:
        return _dump(await pool_page("factor"))

    @server.resource(
        "qfr://pools/strategies",
        name="strategy-pool",
        description="The first page of the strategy pool with evidence tiers (qfr.pool.list).",
        mime_type=JSON,
    )
    async def strategy_pool() -> str:
        return _dump(await pool_page("strategy"))

    @server.resource(
        "qfr://jobs/{job_id}",
        name="job",
        description="One research job with its generations (as qfr.job.get).",
        mime_type=JSON,
    )
    async def job(job_id: str) -> str:
        client = deps.require_research()
        view = await client.job(UUID(job_id))
        generations = (
            await client.generations(view.program_id) if view.program_id is not None else None
        )
        return _dump(
            {
                "job": view.model_dump(mode="json"),
                "generations": []
                if generations is None
                else [g.model_dump(mode="json") for g in generations.items],
            }
        )

    @server.resource(
        "qfr://deliverables/{deliverable_id}",
        name="deliverable",
        description=(
            "One deliverable composed with owner-grade evidence (owner_only). Reading the "
            "resource does not mark the job DELIVERED; qfr.deliverable.get does."
        ),
        mime_type=JSON,
    )
    async def deliverable(deliverable_id: str) -> str:
        view = await deps.require_research().deliverable(UUID(deliverable_id), False)
        return _dump(await deps.compose(view))

    @server.resource(
        "qfr://trace/{version_id}",
        name="trace",
        description="The development trace (trace/1) of a published version.",
        mime_type=JSON,
    )
    async def trace(version_id: str) -> str:
        view = await deps.require_research().trace(UUID(version_id), None)
        return _dump(view.model_dump(mode="json"))

    @server.resource(
        "qfr://schemas/{name}",
        name="schema",
        description=(
            "A public JSON Schema: brief, deliverable, approval, trace, trace_step, "
            "iteration_history or pool_import."
        ),
        mime_type=JSON,
    )
    def schema(name: str) -> str:
        if name not in SCHEMAS:
            raise ValueError(f"SCHEMA_UNKNOWN: one of {', '.join(sorted(SCHEMAS))}")
        return _dump(PUBLIC_CONTRACTS[SCHEMAS[name]].model_json_schema())

    @server.prompt(
        name="qfr.brief",
        description=(
            "How to turn the owner's intent into a brief/1: modes, seeds, tiers and "
            "timelines, budgets, and what never to put in a brief."
        ),
    )
    def brief_prompt() -> str:
        return BRIEF

    @server.prompt(
        name="qfr.report_deliverable",
        description=(
            "How to present a deliverable: tier first, then the artifact and evidence, the "
            "caveats verbatim, the iteration history and the short codes."
        ),
    )
    def report_prompt() -> str:
        return REPORT_DELIVERABLE
