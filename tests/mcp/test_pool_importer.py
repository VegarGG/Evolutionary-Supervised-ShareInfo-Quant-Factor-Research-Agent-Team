"""File access and size limits of the raw pool importer; refused before any registry call."""

import io
from pathlib import Path

import pytest
from qfr_core.config import logging_config, mcp_config
from qfr_core.logging import JsonLogger
from qfr_mcp.control_store import MemoryControlStore
from qfr_mcp.pool_importer import ImportRejected, PoolImporter
from qfr_mcp.registry_client import RegistryClient

from tests.registry_rig import LIMITS


def importer(tmp_path, imports=True, **limits):
    logger = JsonLogger(
        "qfr-mcp", "control", tmp_path, logging_config(Path("configs")), stdout=io.StringIO()
    )
    config = mcp_config(Path("configs")).model_copy(update=limits)
    # The registry is never reached: every case below is refused first.
    registry = RegistryClient("http://registry-api:8000", "token", 1.0, logger)
    folder = tmp_path / "imports"
    folder.mkdir(exist_ok=True)
    store = MemoryControlStore()
    built = PoolImporter(registry, store, LIMITS, config, folder if imports else None, logger)
    return built, folder, store


def refused(coroutine):
    import asyncio

    with pytest.raises(ImportRejected) as caught:
        asyncio.run(coroutine)
    return caught.value.code


def test_files_over_the_byte_limit_are_refused(tmp_path):
    built, folder, store = importer(tmp_path, import_max_bytes=10)
    (folder / "big.yaml").write_text("entries:\n  - name: x\n")
    assert refused(built.run(file="big.yaml")) == "FILE_TOO_LARGE"
    assert store.states == [] and store.steps == []


def test_imports_over_the_entry_limit_are_refused(tmp_path):
    built, _, store = importer(tmp_path, import_max_entries=2)
    assert refused(built.run(entries=[{}, {}, {}])) == "TOO_MANY_ENTRIES"
    assert store.states == []


def test_symlinks_out_of_the_imports_folder_are_refused(tmp_path):
    built, folder, _ = importer(tmp_path)
    secret = tmp_path / "secret.yaml"
    secret.write_text("entries: []\n")
    (folder / "link.yaml").symlink_to(secret)
    assert refused(built.run(file="link.yaml")) == "PATH_OUTSIDE_IMPORTS"
    assert refused(built.run(file=".")) == "PATH_OUTSIDE_IMPORTS"


def test_an_unconfigured_imports_folder_is_explicit(tmp_path):
    built, _, _ = importer(tmp_path, imports=False)
    assert refused(built.run(file="pool.yaml")) == "IMPORTS_DIR_UNSET"


def test_reading_a_file_records_its_digest(tmp_path):
    built, folder, _ = importer(tmp_path)
    (folder / "nested").mkdir()
    (folder / "nested" / "pool.yaml").write_bytes(b"entries: []\n")
    data, source = built.read_file("nested/pool.yaml")
    assert data == b"entries: []\n"
    assert source["file"] == "nested/pool.yaml" and source["bytes"] == 12
    assert len(str(source["sha256"])) == 64
