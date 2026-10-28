"""Explicit static bearer bindings. No token generation, persistence or deployment."""

import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from fastapi import HTTPException, Request
from qfr_core.contracts.publication import RegistryAuthenticationConfiguration

from qfr_registry.publication import Principal

TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*")


@dataclass(frozen=True)
class BoundToken:
    digest: bytes = field(repr=False)
    principal: Principal


class StaticTokenAuthorizer:
    def __init__(self, config: RegistryAuthenticationConfiguration, environment: Mapping[str, str]):
        self.config = config
        tokens = []
        seen: set[bytes] = set()
        for binding in config.bindings:
            # Inspect only explicit references; never enumerate the process environment.
            value = environment.get(binding.token_ref.removeprefix("env:"))
            if value is None or not self.valid_token(value):
                raise ValueError("configured registry token is missing or invalid")
            digest = hashlib.sha256(value.encode("ascii")).digest()
            if digest in seen:
                raise ValueError("registry tokens must identify distinct principals")
            seen.add(digest)
            tokens.append(
                BoundToken(
                    digest,
                    Principal(
                        binding.principal, frozenset(binding.roles), frozenset(binding.programs)
                    ),
                )
            )
        self.tokens = tuple(tokens)

    def valid_token(self, value: str) -> bool:
        return (
            self.config.minimum_token_bytes <= len(value) <= self.config.maximum_token_bytes
            and TOKEN.fullmatch(value) is not None
        )

    def __call__(self, request: Request) -> Principal:
        headers = request.headers.getlist("authorization")
        selected = None
        if len(headers) == 1:
            parts = headers[0].split(" ")
            if len(parts) == 2 and parts[0].lower() == "bearer" and self.valid_token(parts[1]):
                digest = hashlib.sha256(parts[1].encode("ascii")).digest()
                # Compare every configured digest; do not reveal a token's position.
                for token in self.tokens:
                    if hmac.compare_digest(digest, token.digest):
                        selected = token.principal
        if selected is None:
            raise HTTPException(
                status_code=401,
                detail="registry authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return selected
