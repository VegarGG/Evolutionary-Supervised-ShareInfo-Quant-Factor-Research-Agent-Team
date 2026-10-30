"""Check project notices and built distribution metadata without network access."""

from __future__ import annotations

import argparse
import hashlib
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPRESSION = "PolyForm-Noncommercial-1.0.0"
FILES = ("LICENSE", "NOTICE", "ADDITIONAL-PERMISSION.md", "THIRD-PARTY-NOTICES.md")
OFFICIAL_SHA256 = "c0ea4a896d2c8c394b29f9427589996db826cd501c512279ff0ed3ef48fabbe5"


def check_sources() -> list[str]:
    assert hashlib.sha256((ROOT / "LICENSE").read_bytes()).hexdigest() == OFFICIAL_SHA256
    packages = []
    for project in [ROOT, *sorted((ROOT / "packages").iterdir())]:
        metadata = tomllib.loads((project / "pyproject.toml").read_text())["project"]
        assert metadata["license"] == EXPRESSION, project
        assert metadata["license-files"] == list(FILES), project
        for name in FILES:
            assert (project / name).read_bytes() == (ROOT / name).read_bytes(), (project, name)
        if project != ROOT:
            packages.append(metadata["name"].replace("-", "_"))
    print(f"Project license and notices: {len(packages)} packages plus workspace metadata verified")
    return packages


def check_distributions(directory: Path, packages: list[str]) -> None:
    for package in packages:
        wheels = list(directory.glob(f"{package}-*.whl"))
        sdists = list(directory.glob(f"{package}-*.tar.gz"))
        assert len(wheels) == len(sdists) == 1, (package, wheels, sdists)
        with zipfile.ZipFile(wheels[0]) as wheel:
            paths = wheel.namelist()
            info = next(p for p in paths if p.endswith(".dist-info/METADATA"))
            metadata = BytesParser().parsebytes(wheel.read(info))
            assert metadata["License-Expression"] == EXPRESSION, package
            assert set(metadata.get_all("License-File", [])) == set(FILES), package
            prefix = info.removesuffix("METADATA") + "licenses/"
            for name in FILES:
                assert wheel.read(prefix + name) == (ROOT / name).read_bytes(), (package, name)
        with tarfile.open(sdists[0]) as sdist:
            members = sdist.getmembers()
            prefix = next(m.name for m in members if m.name.endswith("/PKG-INFO"))
            prefix = prefix.removesuffix("PKG-INFO")
            for name in FILES:
                stream = sdist.extractfile(prefix + name)
                assert stream is not None and stream.read() == (ROOT / name).read_bytes()
    print(f"Built distributions: {len(packages)} wheels and {len(packages)} sdists verified")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distributions", type=Path)
    args = parser.parse_args()
    packages = check_sources()
    if args.distributions is not None:
        check_distributions(args.distributions, packages)


if __name__ == "__main__":
    main()
