"""The envelope every MCP tool returns: the call's request id, a status and the data,
and the label every response carrying owner-grade evidence gets (Section 13.4)."""

from typing import Literal

from pydantic import JsonValue
from qfr_core.contracts import HYGIENE_WARNING, OWNER_ONLY, Contract

Status = Literal["ok", "partial", "not_implemented_in_phase_0"]


class ToolResult(Contract):
    request_id: str
    status: Status
    data: dict[str, JsonValue]


def owner_grade(data: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Label a response that carries owner-grade evidence: owner_only visibility and the
    holdout-hygiene warning, so a host agent never mistakes it for research feedback."""
    return data | {"visibility": OWNER_ONLY, "hygiene_warning": HYGIENE_WARNING}
