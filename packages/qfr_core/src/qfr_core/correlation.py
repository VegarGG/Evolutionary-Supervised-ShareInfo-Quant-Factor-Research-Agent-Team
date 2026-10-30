"""The same correlation envelope crosses contexts, HTTP and future queue payloads."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

IDS = frozenset(
    "request_id job_id program_id generation_id task_id run_id candidate_id version_id "
    "family_id record_id report_id case_id sim_id step_id principal".split()
)
_context: ContextVar[dict[str, str] | None] = ContextVar("qfr_correlation", default=None)


class CorrelationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: dict[str, str]


def current() -> dict[str, str]:
    return dict(_context.get() or {})


@contextmanager
def bind(**ids: str | None) -> Iterator[dict[str, str]]:
    if set(ids) - IDS:
        raise ValueError("unknown correlation field")
    merged = current() | {k: v for k, v in ids.items() if v is not None}
    merged.setdefault("request_id", str(uuid4()))
    token = _context.set(merged)
    try:
        yield merged
    finally:
        _context.reset(token)


def to_headers() -> dict[str, str]:
    ctx = current()
    headers = {"X-Request-Id": ctx.get("request_id", str(uuid4()))}
    if "job_id" in ctx:
        headers["X-QFR-Job-Id"] = ctx["job_id"]
    return headers


def from_headers(headers: Mapping[str, str]) -> dict[str, str]:
    lower = {k.lower(): v for k, v in headers.items()}
    result = {"request_id": lower.get("x-request-id", str(uuid4()))}
    if "x-qfr-job-id" in lower:
        result["job_id"] = lower["x-qfr-job-id"]
    return result


def to_queue() -> CorrelationEnvelope:
    return CorrelationEnvelope(ids=current())


def from_queue(envelope: CorrelationEnvelope) -> dict[str, str]:
    if set(envelope.ids) - IDS or not envelope.ids.get("request_id"):
        raise ValueError("invalid queue correlation envelope")
    return envelope.ids
