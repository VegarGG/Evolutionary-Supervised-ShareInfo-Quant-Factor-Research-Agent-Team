"""Content-addressed opaque payloads; this store never imports or deserializes code."""

import hashlib
import os
import re
import tempfile
from pathlib import Path


class PayloadStore:
    def __init__(self, root: Path):
        if root.is_symlink():
            raise ValueError("payload root must not be a symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = root.resolve()

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        target = self.root / digest
        fd, name = tempfile.mkstemp(prefix=".pending-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
                os.fchmod(output.fileno(), 0o400)
            try:
                os.link(name, target)
            except FileExistsError:
                if self.read(digest) != data:
                    raise ValueError("immutable payload mismatch") from None
        finally:
            Path(name).unlink(missing_ok=True)
        return digest

    def read(self, digest: str) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid payload identity")
        fd = os.open(self.root / digest, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as source:
            result = source.read()
        if hashlib.sha256(result).hexdigest() != digest:
            raise ValueError("immutable payload checksum mismatch")
        return result
