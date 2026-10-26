"""Qlib codec/ingest fixtures are synthetic; no CN supplier access is implied."""

import io
import tarfile
from pathlib import Path

import numpy as np
import pytest
from qfr_core.data_layer.qlib import StockImportConfig, extract_release, read_binary, read_qlib
from qfr_core.data_layer.snapshots import file_hash

ROOT = Path(__file__).resolve().parents[2]


def config():
    return StockImportConfig.model_validate_json(
        (ROOT / "configs/data/stock_import.json").read_bytes()
    )


def binary(path, start, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(np.asarray([start, *values], dtype="<f4").tobytes())


def fixture(root):
    (root / "calendars").mkdir()
    (root / "calendars/day.txt").write_text("2020-08-21\n2020-08-24\n2020-08-25\n2020-08-26\n")
    (root / "instruments").mkdir()
    (root / "instruments/csi300.txt").write_text(
        "SZ300001\t2020-08-21\t2020-08-24\nSZ300001\t2020-08-26\t2020-08-26\n"
    )
    for name in config().required_fields:
        values = (
            [10.0, 12.0, np.nan, 11.0]
            if name in {"open", "high", "low", "close"}
            else [2.0, 2.0, np.nan, 2.0]
        )
        binary(root / f"features/sz300001/{name}.day.bin", 0, values)


def read(root, authorization="fixture-only"):
    return read_qlib(
        root,
        config(),
        authorization_ref=authorization,
        release_tag="synthetic-codec-test",
        archive_sha256="0" * 64,
    )


def test_qlib_membership_gaps_raw_prices_limits_and_manifest(tmp_path):
    fixture(tmp_path)
    result = read(tmp_path)
    assert result.panel["close_raw"].to_list() == [5.0, 6.0, None, 5.5]
    assert result.panel["in_csi300"].to_list() == [True, True, False, True]
    assert result.panel["limit_up"].to_list() == [False, True, False, False]
    assert result.panel["is_suspended"].to_list() == [False, False, True, False]
    assert "index unavailable" in result.conventions["benchmark"]
    assert not config().enabled
    binary(tmp_path / "features/sh000300/close.day.bin", 1, [3000.0, 3010.0, 3020.0])
    assert read(tmp_path).conventions["benchmark"] == "SH000300"
    with pytest.raises(PermissionError):
        read(tmp_path, None)


def test_qlib_validation_is_explicit(tmp_path):
    fixture(tmp_path)
    (tmp_path / "features/sz300001/open.day.bin").unlink()
    with pytest.raises(ValueError, match="missing required field"):
        read(tmp_path)
    binary(tmp_path / "bad", -1, [1.0, 2.0])
    with pytest.raises(ValueError, match="offset"):
        read_binary(tmp_path / "bad", 4)
    binary(tmp_path / "bad", 3, [1.0, 2.0])
    with pytest.raises(ValueError, match="exceeds calendar"):
        read_binary(tmp_path / "bad", 4)


@pytest.mark.parametrize("name,link", [("../escape", False), ("safe", True)])
def test_archive_hash_and_safe_extraction(tmp_path, name, link):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as target:
        item = tarfile.TarInfo(name)
        if link:
            item.type, item.linkname = tarfile.SYMTYPE, "/etc/passwd"
        else:
            item.size = 1
        target.addfile(item, None if link else io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="SHA-256"):
        extract_release(archive, "0" * 64, tmp_path / "out", config(), authorization_ref="test")
    with pytest.raises(ValueError, match="unsafe"):
        extract_release(
            archive, file_hash(archive), tmp_path / "out", config(), authorization_ref="test"
        )
    assert not (tmp_path / "out").exists()
