"""Explicit public-service scopes; never evaluator-admin authority."""

from typing import Annotated, Literal, Self

from pydantic import Field, PositiveInt, StringConstraints, model_validator

from qfr_core.contracts.base import Contract, SecretRef, Text

ProgramId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")]
ServiceRole = Literal["reader", "research_lead"]


class ServiceTokenBinding(Contract):
    principal: Text
    token_ref: SecretRef
    roles: list[ServiceRole] = Field(min_length=1)
    programs: list[ProgramId] = Field(min_length=1)

    @model_validator(mode="after")
    def distinct_scopes(self) -> Self:
        if len(set(self.roles)) != len(self.roles) or len(set(self.programs)) != len(self.programs):
            raise ValueError("token scopes must be distinct")
        return self


class ServiceAuthentication(Contract):
    revision: PositiveInt
    audience: Literal["feedback", "research", "mcp"]
    minimum_token_bytes: PositiveInt = Field(ge=32)
    maximum_token_bytes: PositiveInt = Field(le=4096)
    bindings: list[ServiceTokenBinding] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def closed_roles(self) -> Self:
        if self.maximum_token_bytes < self.minimum_token_bytes:
            raise ValueError("invalid token length bounds")
        if self.audience == "feedback" and any(b.roles != ["reader"] for b in self.bindings):
            raise ValueError("feedback permits only reader tokens")
        if len({b.token_ref for b in self.bindings}) != len(self.bindings):
            raise ValueError("token references must be distinct")
        return self
