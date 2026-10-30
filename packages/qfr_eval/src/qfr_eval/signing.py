"""Trusted evaluator-only signing; no key generation, grants or network service."""

import hashlib
import os
import stat
from pathlib import Path
from typing import Any, TypeVar

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from qfr_core.contracts.base import Contract
from qfr_core.contracts.reports import Signature
from qfr_core.contracts.signing import SignaturePurpose, VerificationKey, VerificationPolicy
from qfr_core.signatures import EvidenceVerifier, signature_message

T = TypeVar("T", bound=Contract)


class EvaluatorSigner:
    def __init__(self, raw_private_key: bytes, *, purposes: list[SignaturePurpose]):
        self._key = Ed25519PrivateKey.from_private_bytes(raw_private_key)
        public = self._key.public_key().public_bytes_raw()
        self.public_key = VerificationKey(
            algorithm="Ed25519",
            key_id="ed25519:" + hashlib.sha256(public).hexdigest(),
            public_key_hex=public.hex(),
            purposes=purposes,
        )

    @classmethod
    def from_private_file(
        cls, path: Path, *, purposes: list[SignaturePurpose]
    ) -> "EvaluatorSigner":
        # Pin the opened inode, disallow symlinks/FIFOs and never print its path or contents.
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077
                    or info.st_size != 32
                ):
                    raise ValueError("private signing key must be an owner-only 32-byte file")
                data = stream.read(33)
            if len(data) != 32:
                raise ValueError("private signing key changed while reading")
        except OSError:
            raise ValueError("private signing key unavailable") from None
        return cls(data, purposes=purposes)

    def verifier(self, *, maximum_document_bytes: int) -> EvidenceVerifier:
        return EvidenceVerifier(
            VerificationPolicy(
                revision=1,
                canonicalization="qfr-signed-json-v1",
                maximum_document_bytes=maximum_document_bytes,
                keys=[self.public_key],
            )
        )

    def seal(self, model: type[T], purpose: SignaturePurpose, body: dict[str, Any]) -> T:
        if purpose not in self.public_key.purposes or "signature" in body:
            raise ValueError("signing purpose or payload is not permitted")
        # Validate/normalize the complete typed model before signing. This temporary
        # structural signature never leaves this function or enters a database.
        shape = model.model_validate(
            {
                **body,
                "signature": Signature(
                    algorithm="Ed25519",
                    key_id=self.public_key.key_id,
                    signature_hex="0" * 128,
                ),
            }
        )
        payload = shape.model_dump(mode="json", exclude={"signature"})
        signature = Signature(
            algorithm="Ed25519",
            key_id=self.public_key.key_id,
            signature_hex=self._key.sign(
                signature_message(purpose, self.public_key.key_id, payload)
            ).hex(),
        )
        return model.model_validate({**payload, "signature": signature})
