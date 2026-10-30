"""Verification only. Trust comes from configured public keys, never from a report."""

import json
from typing import Any, TypeVar

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from qfr_core.contracts.base import Contract
from qfr_core.contracts.delivery import DeliveryReceipt
from qfr_core.contracts.reports import ReleasedReport, Signature
from qfr_core.contracts.signing import SignaturePurpose, VerificationPolicy

T = TypeVar("T", bound=Contract)


class SignatureRejected(ValueError):
    """Untrusted evidence must not receive an official label."""


def signature_message(purpose: SignaturePurpose, key_id: str, body: dict[str, Any]) -> bytes:
    if "signature" in body:
        raise SignatureRejected("signature must be outside the signed payload")
    return b"qfr-signed-json-v1\n" + json.dumps(
        {"purpose": purpose, "algorithm": "Ed25519", "key_id": key_id, "payload": body},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SignatureRejected("duplicate JSON member")
        result[key] = value
    return result


def _invalid_number(value: str) -> Any:
    raise SignatureRejected("nonfinite JSON number")


class EvidenceVerifier:
    def __init__(self, policy: VerificationPolicy):
        self.policy = VerificationPolicy.model_validate(policy.model_dump())
        self._keys = {key.key_id: key for key in self.policy.keys}

    def verify_payload(
        self, purpose: SignaturePurpose, body: dict[str, Any], signature: Signature
    ) -> None:
        signature = Signature.model_validate(signature.model_dump())
        key = self._keys.get(signature.key_id)
        if key is None or purpose not in key.purposes:
            raise SignatureRejected("unknown key or unauthorized signing purpose")
        message = signature_message(purpose, signature.key_id, body)
        if len(message) > self.policy.maximum_document_bytes:
            raise SignatureRejected("signed document exceeds configured limit")
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(key.public_key_hex)).verify(
                bytes.fromhex(signature.signature_hex), message
            )
        except (InvalidSignature, ValueError):
            raise SignatureRejected("invalid evidence signature") from None

    def _document(self, data: bytes, model: type[T]) -> T:
        if len(data) > self.policy.maximum_document_bytes:
            raise SignatureRejected("signed document exceeds configured limit")
        try:
            value = json.loads(
                data, object_pairs_hook=_unique_pairs, parse_constant=_invalid_number
            )
            return model.model_validate(value)
        except (ValueError, TypeError, RecursionError):
            raise SignatureRejected("invalid signed document") from None

    def report(self, value: ReleasedReport | bytes) -> ReleasedReport:
        report = (
            self._document(value, ReleasedReport)
            if isinstance(value, bytes)
            else ReleasedReport.model_validate(value.model_dump())
        )
        self.verify_payload(
            "released_report",
            report.model_dump(mode="json", exclude={"signature"}),
            report.signature,
        )
        return report

    def delivery(self, value: DeliveryReceipt | bytes) -> DeliveryReceipt:
        receipt = (
            self._document(value, DeliveryReceipt)
            if isinstance(value, bytes)
            else DeliveryReceipt.model_validate(value.model_dump())
        )
        self.verify_payload(
            "delivery_receipt",
            receipt.model_dump(mode="json", exclude={"signature"}),
            receipt.signature,
        )
        return receipt
