"""Ephemeral keys, strict typed payloads and adversarial verification boundaries."""

import json
import os
import secrets
from pathlib import Path

import pytest
from pydantic import ValidationError
from qfr_core.contracts.delivery import DeliveryReceipt
from qfr_core.contracts.reports import ReleasedReport
from qfr_core.contracts.signing import VerificationPolicy
from qfr_core.signatures import EvidenceVerifier, SignatureRejected
from qfr_eval.signing import EvaluatorSigner

ROOT = Path(__file__).resolve().parents[1]


def signer():
    return EvaluatorSigner(
        secrets.token_bytes(32),
        purposes=["released_report", "measurement_receipt", "delivery_receipt"],
    )


def unsigned(model):
    body = json.loads((ROOT / f"contracts/examples/{model.__name__}.valid.json").read_bytes())
    body.pop("signature")
    return body


@pytest.mark.parametrize(
    "model,purpose,method",
    [
        (ReleasedReport, "released_report", "report"),
        (DeliveryReceipt, "delivery_receipt", "delivery"),
    ],
)
def test_signature_binds_exact_typed_content_and_rejects_tampering(model, purpose, method):
    key = signer()
    evidence = key.seal(model, purpose, unsigned(model))
    verify = getattr(key.verifier(maximum_document_bytes=1048576), method)
    assert verify(evidence.model_dump_json().encode()) == evidence
    assert key.seal(model, purpose, unsigned(model)) == evidence
    for field, value in [("schema_version", "2"), ("signature", None), ("unreleased", "private")]:
        body = evidence.model_dump(mode="json")
        body[field] = value
        with pytest.raises((SignatureRejected, ValidationError)):
            verify(json.dumps(body).encode())
    body = evidence.model_dump(mode="json")
    name = "report_id" if model is ReleasedReport else "receipt_id"
    body[name] += "-forged"
    with pytest.raises(SignatureRejected):
        verify(json.dumps(body).encode())
    body = evidence.model_dump(mode="json")
    body["signature"]["signature_hex"] = "0" * 128
    with pytest.raises(SignatureRejected):
        verify(json.dumps(body).encode())


def test_unknown_key_purpose_and_confusable_json_fail_closed():
    key, other = signer(), signer()
    report = key.seal(ReleasedReport, "released_report", unsigned(ReleasedReport))
    with pytest.raises(SignatureRejected, match="unknown key"):
        other.verifier(maximum_document_bytes=1048576).report(report)
    verifier = key.verifier(maximum_document_bytes=1048576)
    with pytest.raises(SignatureRejected, match="invalid evidence signature"):
        verifier.verify_payload(
            "delivery_receipt",
            report.model_dump(mode="json", exclude={"signature"}),
            report.signature,
        )
    restricted = key.public_key.model_copy(update={"purposes": ["delivery_receipt"]})
    limited = EvidenceVerifier(verifier.policy.model_copy(update={"keys": [restricted]}))
    with pytest.raises(SignatureRejected, match="purpose"):
        limited.report(report)
    encoded = report.model_dump_json().encode()
    for data in [b'{"schema_version":"1",' + encoded[1:], b'{"value":NaN}', b"\xff"]:
        with pytest.raises(SignatureRejected):
            verifier.report(data)
    with pytest.raises(SignatureRejected, match="limit"):
        key.verifier(maximum_document_bytes=50).report(encoded)
    with pytest.raises(SignatureRejected, match="limit"):
        key.verifier(maximum_document_bytes=50).report(report)


def test_trust_configuration_cannot_alias_or_duplicate_keys():
    policy = signer().verifier(maximum_document_bytes=1048576).policy
    with pytest.raises(ValidationError):
        VerificationPolicy.model_validate({**policy.model_dump(), "keys": policy.keys * 2})
    value = policy.model_dump()
    value["keys"][0]["key_id"] = "operator-claimed-key"
    with pytest.raises(ValidationError):
        VerificationPolicy.model_validate(value)


def test_private_signer_refuses_unsafe_files_without_printing_material(tmp_path):
    material = secrets.token_bytes(32)
    path = tmp_path / "ephemeral-test-key"
    path.write_bytes(material)
    path.chmod(0o600)
    key = EvaluatorSigner.from_private_file(path, purposes=["released_report"])
    assert material.hex() not in repr(key)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        EvaluatorSigner.from_private_file(path, purposes=["released_report"])
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="unavailable"):
        EvaluatorSigner.from_private_file(link, purposes=["released_report"])
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="32-byte"):
        EvaluatorSigner.from_private_file(path, purposes=["released_report"])
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo, mode=0o600)
    with pytest.raises(ValueError, match="32-byte"):
        EvaluatorSigner.from_private_file(fifo, purposes=["released_report"])
