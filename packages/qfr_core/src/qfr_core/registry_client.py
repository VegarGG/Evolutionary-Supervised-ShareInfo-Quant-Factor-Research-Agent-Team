"""Bounded authenticated registry HTTP client; no database or evaluator controls."""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from pydantic import ValidationError

from qfr_core.contracts.publication import (
    ArtifactPage,
    PublicationRequest,
    PublicationResponse,
    PublishedArtifact,
    RegistryClientConfiguration,
)


class RegistryTransportError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class NoRedirects(HTTPRedirectHandler):
    # Returning None rejects every redirect before forwarding a bearer credential.
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


@dataclass(frozen=True)
class RegistryClient:
    config: RegistryClientConfiguration
    token: str = field(repr=False)

    @classmethod
    def from_environment(
        cls, config: RegistryClientConfiguration, environment: Mapping[str, str]
    ) -> "RegistryClient":
        value = environment.get(config.token_ref.removeprefix("env:"))
        if value is None or not re.fullmatch(r"[A-Za-z0-9._~+/-]{32,8192}=*", value):
            raise ValueError("registry client credential is missing or invalid")
        return cls(config, value)

    def request(
        self, path: str, *, body: bytes | None = None, request_id: UUID | None = None
    ) -> tuple[int, bytes]:
        if not path.startswith("v1/") or "://" in path or path.startswith("//"):
            raise ValueError("registry endpoint must be a relative v1 route")
        if body is not None and len(body) > self.config.max_request_bytes:
            raise RegistryTransportError("registry request size limit")
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if request_id is not None:
            headers["X-Request-ID"] = str(request_id)
        request = Request(
            str(self.config.base_url).rstrip("/") + "/" + path, data=body, headers=headers
        )
        try:
            with build_opener(NoRedirects()).open(
                request, timeout=self.config.timeout_seconds
            ) as response:
                data = response.read(self.config.max_response_bytes + 1)
                status = int(response.status)
        except HTTPError as error:
            status = error.code
            error.close()
            raise RegistryTransportError("registry HTTP request rejected", status) from None
        except (URLError, TimeoutError, OSError):
            raise RegistryTransportError("registry connection unavailable") from None
        if len(data) > self.config.max_response_bytes:
            raise RegistryTransportError("registry response size limit")
        if status not in (200, 201):
            raise RegistryTransportError("unexpected registry HTTP status", status)
        return status, data

    def publish(
        self, request: PublicationRequest, *, request_id: UUID | None = None
    ) -> PublicationResponse:
        status, data = self.request(
            "v1/artifacts", body=request.model_dump_json().encode(), request_id=request_id
        )
        try:
            result = PublicationResponse.model_validate_json(data)
        except ValidationError:
            raise RegistryTransportError("invalid registry publication response") from None
        if result.created != (status == 201):
            raise RegistryTransportError("inconsistent registry publication status")
        return result

    def get(self, identity: UUID) -> PublishedArtifact:
        _, data = self.request(f"v1/artifacts/{identity}")
        try:
            artifact = PublishedArtifact.model_validate_json(data)
        except ValidationError:
            raise RegistryTransportError("invalid registry artifact response") from None
        if artifact.manifest.artifact_version_id != str(identity):
            raise RegistryTransportError("registry artifact identity mismatch")
        return artifact

    def page(self, *, since_seq: int, limit: int) -> ArtifactPage:
        if since_seq < 0 or limit < 1:
            raise ValueError("invalid registry page bounds")
        _, data = self.request(
            "v1/artifacts?" + urlencode({"since_seq": since_seq, "limit": limit})
        )
        try:
            page = ArtifactPage.model_validate_json(data)
        except ValidationError:
            raise RegistryTransportError("invalid registry page response") from None
        if (
            len(page.items) > limit
            or (page.items and page.items[0].published_seq <= since_seq)
            or (not page.items and page.next_cursor != since_seq)
        ):
            raise RegistryTransportError("registry page does not match requested cursor")
        return page

    def payload(self, artifact: PublishedArtifact, asset_id: str) -> bytes:
        declared = next(
            (item for item in artifact.manifest.payload_files if item.asset_id == asset_id), None
        )
        if declared is None:
            raise ValueError("payload is not declared by this artifact")
        identity = UUID(artifact.manifest.artifact_version_id)
        _, data = self.request(
            f"v1/artifacts/{identity}/payload?" + urlencode({"asset_id": asset_id})
        )
        if hashlib.sha256(data).hexdigest() != declared.sha256:
            raise RegistryTransportError("registry payload checksum mismatch")
        return data
