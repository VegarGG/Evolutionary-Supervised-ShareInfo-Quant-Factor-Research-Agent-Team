"""Reading owner files from the imports folder; nothing outside it is reachable."""

import hashlib
from pathlib import Path

from pydantic import JsonValue


class ImportPathError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


def read_import(
    imports_dir: Path | None, name: str, max_bytes: int
) -> tuple[bytes, dict[str, JsonValue]]:
    if imports_dir is None:
        raise ImportPathError("IMPORTS_DIR_UNSET", "QFR_IMPORTS_DIR is not configured")
    root = imports_dir.resolve()
    candidate = (root / name).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        raise ImportPathError("PATH_OUTSIDE_IMPORTS", "name a file inside the imports folder")
    if not candidate.is_file():
        raise ImportPathError("FILE_NOT_FOUND", f"imports/{name} does not exist")
    size = candidate.stat().st_size
    if size > max_bytes:
        raise ImportPathError("FILE_TOO_LARGE", f"{size} bytes exceed the limit of {max_bytes}")
    data = candidate.read_bytes()
    return data, {
        "kind": "file",
        "file": candidate.relative_to(root).as_posix(),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
