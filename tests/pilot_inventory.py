"""Test-only before/after inventory of the two original delivery directories."""

import hashlib
import stat
from pathlib import Path

from scripts.extract_pilot_evidence import PACKAGE_DIRS


def original_package_inventory(root: Path) -> dict[str, str]:
    """Include every original-package file, never sibling test/evidence outputs."""
    result = {}
    for directory in PACKAGE_DIRS.values():
        package = root / directory
        if package.is_symlink() or not package.is_dir():
            raise ValueError("original pilot package directory missing or replaced")
        count = 0
        for path in sorted(package.rglob("*")):
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError("original pilot package contains a non-regular file")
            with path.open("rb") as stream:
                result[path.relative_to(root).as_posix()] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
            count += 1
        if not count:
            raise ValueError("original pilot package is empty")
    return result
