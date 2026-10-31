"""Static bearer tokens mapped to registry roles (PLAN Sections 16.5 and 16.9)."""

import secrets
from collections.abc import Mapping
from typing import Literal

Role = Literal["publisher", "reader", "evaluator", "control"]
ROLES: tuple[Role, ...] = ("publisher", "reader", "evaluator", "control")
TOKEN_ENV: dict[Role, str] = {
    "publisher": "REGISTRY_PUBLISHER_TOKEN",
    "reader": "REGISTRY_READER_TOKEN",
    "evaluator": "REGISTRY_EVALUATOR_TOKEN",
    "control": "REGISTRY_CONTROL_TOKEN",
}


class TokenAuth:
    """One token per role. Every comparison is constant-time and every token is checked."""

    def __init__(self, tokens: Mapping[Role, str]) -> None:
        if set(tokens) != set(ROLES) or not all(tokens.values()):
            raise ValueError("every registry role needs a token")
        if len(set(tokens.values())) != len(ROLES):
            raise ValueError("registry role tokens must be distinct")
        self._tokens = dict(tokens)

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "TokenAuth":
        return cls({role: environ.get(name, "") for role, name in TOKEN_ENV.items()})

    def secrets(self) -> list[str]:
        return list(self._tokens.values())

    def role(self, authorization: str | None) -> Role | None:
        presented = (authorization or "").encode()
        found: Role | None = None
        for role, token in self._tokens.items():
            if secrets.compare_digest(presented, f"Bearer {token}".encode()):
                found = role
        return found
