"""Research request limits over the shared authenticated ASGI boundary."""

from collections.abc import Callable

from qfr_core.access import BearerAuthority
from qfr_core.contracts.research import ResearchApiPolicy
from qfr_core.http_transport import ASGIApp, BoundedServiceBoundary


class ResearchBoundary(BoundedServiceBoundary):
    def __init__(
        self,
        app: ASGIApp,
        *,
        authority: BearerAuthority | None,
        policy: ResearchApiPolicy,
        request_log: Callable[[dict[str, object]], None],
    ):
        super().__init__(
            app,
            authority=authority,
            audience="research",
            maximum_bytes=policy.max_request_bytes,
            timeout_seconds=policy.request_body_timeout_seconds,
            request_log=request_log,
        )
