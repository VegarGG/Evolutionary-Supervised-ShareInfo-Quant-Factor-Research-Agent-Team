"""Static, audience-bound bearer verification without secret persistence or HTTP."""

import hashlib
import hmac
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import TypeAdapter

from qfr_core.contracts.access import ProgramId, ServiceAuthentication

TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*")
PROGRAM = TypeAdapter(ProgramId)


class AuthenticationRequired(Exception):
    pass


@dataclass(frozen=True)
class ServicePrincipal:
    name: str
    audience: str
    roles: frozenset[str]
    programs: frozenset[str]

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.roles or not self.programs:
            raise ValueError("explicit service principal and scopes required")
        if self.audience not in ("feedback", "research", "mcp"):
            raise ValueError("unsupported public service audience")
        if not self.roles <= {"reader", "research_lead"}:
            raise ValueError("unsupported public service role")
        if self.audience == "feedback" and self.roles != {"reader"}:
            raise ValueError("feedback permits only reader authority")
        for program in self.programs:
            PROGRAM.validate_python(program)


@dataclass(frozen=True)
class _Token:
    digest: bytes = field(repr=False)
    principal: ServicePrincipal


class BearerAuthority:
    def __init__(self, config: ServiceAuthentication, environment: Mapping[str, str]) -> None:
        self.config = config
        tokens, seen = [], set()
        for binding in config.bindings:
            value = environment.get(binding.token_ref.removeprefix("env:"))
            if value is None or not self.valid_token(value):
                raise ValueError("configured service token is missing or invalid")
            digest = hashlib.sha256(value.encode("ascii")).digest()
            if digest in seen:
                raise ValueError("service tokens must be distinct")
            seen.add(digest)
            tokens.append(
                _Token(
                    digest,
                    ServicePrincipal(
                        binding.principal,
                        config.audience,
                        frozenset(binding.roles),
                        frozenset(binding.programs),
                    ),
                )
            )
        self._tokens = tuple(tokens)

    def valid_token(self, value: str) -> bool:
        return (
            self.config.minimum_token_bytes <= len(value) <= self.config.maximum_token_bytes
            and TOKEN.fullmatch(value) is not None
        )

    def authenticate(self, headers: Sequence[str], *, audience: str) -> ServicePrincipal:
        if audience != self.config.audience:
            raise AuthenticationRequired("service authentication required")
        result = None
        if len(headers) == 1:
            parts = headers[0].split(" ")
            if len(parts) == 2 and parts[0].lower() == "bearer" and self.valid_token(parts[1]):
                digest = hashlib.sha256(parts[1].encode("ascii")).digest()
                for item in self._tokens:
                    if hmac.compare_digest(digest, item.digest):
                        result = item.principal
        if result is None:
            raise AuthenticationRequired("service authentication required")
        return result
