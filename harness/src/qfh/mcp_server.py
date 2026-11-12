"""Optional MCP bridge over the same guarded, single-provider data boundary.

The DSH plugin is the supported credential UI. Embedders must provide a credential
reader; there is no credential-file CLI and no unguarded RiceQuant transport.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from qfh.data_gateway import DataPolicy, dispatch


def create_server(
    provider: str,
    run_id: str,
    policy: DataPolicy,
    root: Path,
    credential_reader: Callable[[], dict],
) -> FastMCP:
    server = FastMCP("qfh-research-sources")

    def fetch(kind, symbols, start, end, fiscal_year=None):
        return dispatch(
            {
                "provider": provider,
                "run_id": run_id,
                "kind": kind,
                "query": {"symbols": symbols, "start": start, "end": end},
                "fiscal_year": fiscal_year,
                "credentials": credential_reader(),
            },
            policy,
            root,
        )

    @server.tool()
    def market_daily_bars(symbols: list[str], start: str, end: str) -> dict:
        """Read daily close prices within the operator's persistent data allowance."""
        return fetch("bars", symbols, start, end)

    @server.tool()
    def research_reports(symbols: list[str], start: str, end: str, fiscal_year: str) -> dict:
        """Read broker summaries where supported and explicitly enabled."""
        return fetch("report_summaries", symbols, start, end, fiscal_year)

    @server.tool()
    def company_announcements(symbols: list[str], start: str, end: str) -> dict:
        """Read company disclosures where supported and explicitly enabled."""
        return fetch("announcements", symbols, start, end)

    @server.tool()
    def research_news(symbols: list[str], start: str, end: str) -> dict:
        """Read news titles, source links and timestamps where supported and enabled."""
        return fetch("news", symbols, start, end)

    @server.tool()
    def read_research_evidence(evidence_id: str, offset: int = 0, limit: int = 20) -> dict:
        """Read an immutable result already granted to this session."""
        return dispatch(
            {
                "provider": provider,
                "run_id": run_id,
                "kind": "read",
                "evidence_id": evidence_id,
                "offset": offset,
                "limit": limit,
            },
            policy,
            root,
        )

    return server
