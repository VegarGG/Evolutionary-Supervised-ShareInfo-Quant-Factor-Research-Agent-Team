"""Bounded public-service HTTP transport with no credential-bearing redirects."""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, build_opener
from uuid import UUID

from qfr_core.contracts.access import PublicServiceClientConfiguration
from qfr_core.registry_client import NoRedirects


class ServiceTransportError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class PublicServiceClient:
    config: PublicServiceClientConfiguration
    token: str = field(repr=False)

    @classmethod
    def from_environment(
        cls, config: PublicServiceClientConfiguration, environment: Mapping[str, str]
    ) -> "PublicServiceClient":
        value = environment.get(config.token_ref.removeprefix("env:"))
        if value is None or not re.fullmatch(r"[A-Za-z0-9._~+/-]{32,4096}=*", value):
            raise ValueError("service client credential is missing or invalid")
        return cls(config, value)

    def request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        *,
        body: bytes | None = None,
        request_id: UUID | None = None,
        chunk_offset: int | None = None,
    ) -> tuple[int, bytes]:
        url = urlsplit(path)
        decoded = unquote(url.path)
        if (
            method not in {"GET", "POST"}
            or not decoded.startswith("v1/")
            or url.scheme
            or url.netloc
            or url.fragment
            or "\\" in decoded
            or any(part in {".", "..", ""} for part in decoded.split("/"))
            or any(ord(char) < 32 for char in path)
        ):
            raise ValueError("public service route must be a confined relative v1 path")
        if (method == "GET" and body is not None) or (
            body is not None and len(body) > self.config.max_request_bytes
        ):
            raise ServiceTransportError("invalid request body or size")
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if chunk_offset is not None:
            if (
                method != "POST"
                or not url.path.endswith("/chunks")
                or body is None
                or chunk_offset < 0
            ):
                raise ValueError("binary chunks require a confined upload route")
            headers["Content-Type"] = "application/octet-stream"
            headers["X-Chunk-Offset"] = str(chunk_offset)
            headers["X-Chunk-SHA256"] = hashlib.sha256(body).hexdigest()
        if request_id is not None:
            headers["X-Request-ID"] = str(request_id)
        request = Request(
            str(self.config.base_url).rstrip("/") + "/" + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with build_opener(NoRedirects()).open(
                request, timeout=self.config.timeout_seconds
            ) as response:
                value = response.read(self.config.max_response_bytes + 1)
                status = int(response.status)
        except HTTPError as error:
            status = error.code
            error.close()
            raise ServiceTransportError("public service request rejected", status) from None
        except (URLError, TimeoutError, OSError):
            raise ServiceTransportError("public service unavailable") from None
        if len(value) > self.config.max_response_bytes:
            raise ServiceTransportError("public service response exceeds size bound")
        if status not in (200, 201, 202):
            raise ServiceTransportError("unexpected public service response", status)
        return status, value
