"""Public verification configuration. No private key or private receipt payload."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import Field, PositiveInt, model_validator

from qfr_core.contracts.base import Contract, Text

SignaturePurpose = Literal["released_report", "measurement_receipt", "delivery_receipt"]


class VerificationKey(Contract):
    algorithm: Literal["Ed25519"]
    key_id: Text
    public_key_hex: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    purposes: list[SignaturePurpose] = Field(min_length=1)

    @model_validator(mode="after")
    def content_addressed_key(self) -> Self:
        expected = "ed25519:" + hashlib.sha256(bytes.fromhex(self.public_key_hex)).hexdigest()
        if self.key_id != expected or len(set(self.purposes)) != len(self.purposes):
            raise ValueError("key identity or purpose set is invalid")
        return self


class VerificationPolicy(Contract):
    revision: Literal[1]
    canonicalization: Literal["qfr-signed-json-v1"]
    maximum_document_bytes: PositiveInt = Field(le=16777216)
    keys: list[VerificationKey] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_keys(self) -> Self:
        if len({key.key_id for key in self.keys}) != len(self.keys):
            raise ValueError("duplicate trusted key")
        return self
