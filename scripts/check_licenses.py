"""Check project notices and built distribution metadata without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPRESSION = "MIT"
FILES = ("LICENSE", "NOTICE", "THIRD-PARTY-NOTICES.md")
LICENSE_SHA256 = "1ba48843bce9d0054fd71d3caede16e5de6f097c90e04367bae418de73bd25b4"
DSH_LICENSE_SHA256 = "ebb4f09972aee8608be255debaf78451a68e95c290f55c240dec2ecfa16ea6be"


def check_sources() -> list[str]:
    assert hashlib.sha256((ROOT / "LICENSE").read_bytes()).hexdigest() == LICENSE_SHA256
    upstream = (
        (ROOT / "THIRD-PARTY-NOTICES.md")
        .read_text()
        .split("## DeepSeek Harness copyright and permission notice\n\n", 1)[1]
    )
    assert hashlib.sha256(upstream.encode()).hexdigest() == DSH_LICENSE_SHA256
    packages = []
    projects = [ROOT, *sorted((ROOT / "packages").iterdir()), ROOT / "harness"]
    for project in projects:
        metadata = tomllib.loads((project / "pyproject.toml").read_text())["project"]
        assert metadata["license"] == EXPRESSION, project
        assert metadata["license-files"] == list(FILES), project
        for name in FILES:
            assert (project / name).read_bytes() == (ROOT / name).read_bytes(), (project, name)
        assert not (project / "ADDITIONAL-PERMISSION.md").exists(), project
        if project.parent == ROOT / "packages":
            packages.append(metadata["name"].replace("-", "_"))
    plugin = ROOT / "harness/dsh-plugin"
    metadata = json.loads((plugin / "package.json").read_text())
    assert metadata["license"] == EXPRESSION, plugin
    assert set(FILES) <= set(metadata["files"]), plugin
    for name in FILES:
        assert (plugin / name).read_bytes() == (ROOT / name).read_bytes(), (plugin, name)
    assert not (plugin / "ADDITIONAL-PERMISSION.md").exists(), plugin
    print(f"MIT notices verified: {len(packages)} packages, workspace, harness and plugin")
    return packages


def check_distributions(directory: Path, packages: list[str]) -> None:
    for package in packages:
        wheels = list(directory.glob(f"{package}-*.whl"))
        sdists = list(directory.glob(f"{package}-*.tar.gz"))
        assert len(wheels) == len(sdists) == 1, (package, wheels, sdists)
        with zipfile.ZipFile(wheels[0]) as wheel:
            paths = wheel.namelist()
            assert not any(p.endswith("/ADDITIONAL-PERMISSION.md") for p in paths), package
            info = next(p for p in paths if p.endswith(".dist-info/METADATA"))
            metadata = BytesParser().parsebytes(wheel.read(info))
            assert metadata["License-Expression"] == EXPRESSION, package
            assert set(metadata.get_all("License-File", [])) == set(FILES), package
            prefix = info.removesuffix("METADATA") + "licenses/"
            for name in FILES:
                assert wheel.read(prefix + name) == (ROOT / name).read_bytes(), (package, name)
        with tarfile.open(sdists[0]) as sdist:
            members = sdist.getmembers()
            assert not any(m.name.endswith("/ADDITIONAL-PERMISSION.md") for m in members), package
            prefix = next(m.name for m in members if m.name.endswith("/PKG-INFO"))
            stream = sdist.extractfile(prefix)
            assert stream is not None, package
            metadata = BytesParser().parsebytes(stream.read())
            assert metadata["License-Expression"] == EXPRESSION, package
            assert set(metadata.get_all("License-File", [])) == set(FILES), package
            prefix = prefix.removesuffix("PKG-INFO")
            for name in FILES:
                stream = sdist.extractfile(prefix + name)
                assert stream is not None and stream.read() == (ROOT / name).read_bytes()
    print(f"Built distributions: {len(packages)} wheels and {len(packages)} sdists verified")


def check_plugin(archive: Path) -> None:
    with tarfile.open(archive) as packed:
        assert not any(m.name.endswith("/ADDITIONAL-PERMISSION.md") for m in packed.getmembers())
        stream = packed.extractfile("package/package.json")
        assert stream is not None
        assert json.loads(stream.read())["license"] == EXPRESSION
        for name in FILES:
            stream = packed.extractfile("package/" + name)
            assert stream is not None and stream.read() == (ROOT / name).read_bytes(), name
    print("Packed DSH plugin: MIT metadata and complete notices verified")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distributions", type=Path)
    parser.add_argument("--plugin-archive", type=Path)
    args = parser.parse_args()
    packages = check_sources()
    if args.distributions is not None:
        check_distributions(args.distributions, packages)
    if args.plugin_archive is not None:
        check_plugin(args.plugin_archive)


if __name__ == "__main__":
    main()
