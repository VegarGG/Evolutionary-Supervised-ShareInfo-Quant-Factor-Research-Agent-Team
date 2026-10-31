"""The envelope every MCP tool returns: the call's request id, a status and the data."""

from typing import Literal

from pydantic import JsonValue
from qfr_core.contracts import Contract

Status = Literal["ok", "partial", "not_implemented_in_phase_0"]


class ToolResult(Contract):
    request_id: str
    status: Status
    data: dict[str, JsonValue]
