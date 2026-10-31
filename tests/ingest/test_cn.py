"""Qlib binary reader and CN ingest (PLAN 6.1, 6.2) on a hand-built release archive."""

import hashlib
import io
import json
import tarfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from qfr_core.data.qlib import QlibDirectory, QlibError
from qfr_eval.ingest import cn
from qfr_eval.ingest.cn import IngestError, ingest_cn, manifest_sha256, safe_extract
from qfr_eval.ingest.config import load_cn

CONFIG = load_cn(Path("configs"))
CALENDAR = [date(2019, 1, 1) + timedelta(days=i) for i in range(40) if (i % 7) < 5]


def write_bin(path: Path, start: int, values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.array([float(start), *values], dtype="<f4").tofile(path)


def qlib_tree(root: Path, *, drop_field: str | None = None, with_index: bool = True) -> Path:
    base = root / "qlib_bin"
    (base / "calendars").mkdir(parents=True)
    (base / "calendars" / "day.txt").write_text("\n".join(d.isoformat() for d in CALENDAR) + "\n")
    (base / "instruments").mkdir()
    (base / "instruments" / "csi300.txt").write_text(
        f"SH600000\t{CALENDAR[0]}\t{CALENDAR[9]}\nSH600000\t{CALENDAR[15]}\t2099-12-31\n"
        f"SZ000001\t{CALENDAR[0]}\t2099-12-31\n"
    )
    (base / "instruments" / "csi500.txt").write_text(f"SZ300001\t{CALENDAR[5]}\t2099-12-31\n")
    days = len(CALENDAR)
    for symbol, start, price, factor in (
        ("sh600000", 0, 10.0, 2.0),
        ("sz000001", 3, 20.0, 1.0),
        ("sz300001", 5, 30.0, 1.5),
    ):
        n = days - start
        close = [price * factor * (1 + 0.01 * ((i % 3) - 1)) for i in range(n)]
        if symbol == "sh600000":
            close[4] = float("nan")  # A missing day: suspended.
        fields = {
            "open": close,
            "high": [c * 1.01 for c in close],
            "low": [c * 0.99 for c in close],
            "close": close,
            "volume": [1e6] * n,
            "amount": [1e6 * c / factor for c in close],
            "factor": [factor] * n,
            "vwap": close,
        }
        for name, values in fields.items():
            if name != drop_field or symbol != "sz000001":
                write_bin(base / "features" / symbol / f"{name}.day.bin", start, values)
    if with_index:
        write_bin(
            base / "features" / "sh000300" / "close.day.bin",
            0,
            [1000.0 * (1.001**i) for i in range(days)],
        )
    return base


def archive_of(tree: Path, target: Path) -> Path:
    with tarfile.open(target, "w:gz") as tar:
        tar.add(tree, arcname="qlib_bin")
    return target


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def release(tmp_path):
    archive = archive_of(qlib_tree(tmp_path / "src"), tmp_path / "qlib_bin.tar.gz")
    manifest = tmp_path / "qlib_bin.manifest.json"
    manifest.write_text(
        json.dumps({"files": [{"name": "qlib_bin.tar.gz", "sha256": sha(archive)}]})
    )
    return archive, manifest


def ingest(tmp_path, archive, manifest=None, sha256=None):
    return ingest_cn(
        CONFIG,
        tmp_path / "raw",
        archive=archive,
        manifest=manifest,
        sha256=sha256,
        release_tag="2024-01-31",
    )


def test_reader_follows_the_qlib_binary_format(tmp_path):
    directory = QlibDirectory.locate(qlib_tree(tmp_path).parent)
    assert directory.calendar() == CALENDAR
    assert directory.symbols() == ["SH000300", "SH600000", "SZ000001", "SZ300001"]
    start, values = directory.read_field("SZ000001", "close", len(CALENDAR))
    assert start == 3 and values.size == len(CALENDAR) - 3
    membership = directory.membership("csi300")
    assert membership.filter(pl.col("instrument") == "SH600000").height == 2


def test_ingest_builds_the_panel_with_raw_prices_membership_and_benchmark(tmp_path, release):
    data, source = ingest(tmp_path, *release)
    panel = data.panel
    sh = panel.filter(pl.col("instrument") == "SH600000").sort("date")
    assert sh.height == len(CALENDAR)
    assert sh["is_suspended"].to_list()[4] is True
    assert sh["close_raw"].to_list()[0] == pytest.approx(9.9, rel=1e-6)  # (10 * 2 * 0.99) / 2.
    flags = sh["in_csi300"].to_list()
    assert flags[:10] == [True] * 10 and flags[10:15] == [False] * 5 and all(flags[15:])
    assert panel.filter(pl.col("instrument") == "SZ300001")["in_csi500"].all()
    assert set(panel["instrument"].unique()) == {"SH600000", "SZ000001", "SZ300001"}
    bench = data.calendar.sort("date")["benchmark_ret"].to_list()
    assert bench[0] is None and bench[1] == pytest.approx(0.001, rel=1e-4)
    assert source.conventions["benchmark"] == "SH000300"
    assert source.archive_sha256 == sha(release[0])
    assert source.release_tag == "2024-01-31"
    assert source.source_details["checksum_from"] == "release_manifest"
    assert source.checks["raw_close_share_in_range"] == 1.0


def test_building_the_panel_in_batches_gives_the_same_snapshot_data(tmp_path, release, monkeypatch):
    whole, _ = ingest(tmp_path / "whole", *release)
    monkeypatch.setattr(cn, "PANEL_BATCH", 1)
    batched, _ = ingest(tmp_path / "batched", *release)
    assert batched.panel.equals(whole.panel)
    assert batched.calendar.equals(whole.calendar)
    assert batched.membership.equals(whole.membership)


def test_equal_weight_benchmark_when_the_index_is_absent(tmp_path):
    archive = archive_of(
        qlib_tree(tmp_path / "src", with_index=False), tmp_path / "qlib_bin.tar.gz"
    )
    data, source = ingest(tmp_path, archive, sha256=sha(archive))
    assert source.conventions["benchmark"] == "equal_weight_csi300"
    assert source.source_details["checksum_from"] == "owner_supplied"
    assert data.calendar["benchmark_ret"].drop_nulls().len() > 0


def test_a_missing_required_field_is_a_clear_error(tmp_path):
    archive = archive_of(
        qlib_tree(tmp_path / "src", drop_field="amount"), tmp_path / "qlib_bin.tar.gz"
    )
    with pytest.raises(QlibError, match="SZ000001 lacks required fields: amount"):
        ingest(tmp_path, archive, sha256=sha(archive))


def test_the_archive_is_verified_before_extraction(tmp_path, release):
    archive, _ = release
    with pytest.raises(IngestError, match="does not match"):
        ingest(tmp_path, archive, sha256="0" * 64)
    with pytest.raises(IngestError, match="must be verified"):
        ingest(tmp_path, archive)
    assert not (tmp_path / "raw" / "extracted").exists()


@pytest.mark.parametrize(
    "manifest",
    [
        {"sha256": "H"},
        {"name": "qlib_bin.tar.gz", "sha256": "H"},
        {"qlib_bin.tar.gz": "H"},
        {"qlib_bin.tar.gz": {"sha256": "sha256:H"}},
        {"assets": {"qlib_bin.tar.gz": {"hash": "H"}}},
        [{"file": "dist/qlib_bin.tar.gz", "checksum": "H"}],
    ],
)
def test_manifest_shapes(manifest):
    digest = "ab" * 32
    text = json.dumps(manifest).replace("H", digest)
    assert manifest_sha256(json.loads(text), "qlib_bin.tar.gz") == digest


def test_manifest_without_the_archive_hash_is_refused():
    with pytest.raises(IngestError, match="pass --sha256"):
        manifest_sha256({"name": "other.tar.gz", "sha256": "ab" * 32}, "qlib_bin.tar.gz")
    with pytest.raises(IngestError):
        manifest_sha256({"version": "1"}, "qlib_bin.tar.gz")


def unsafe_archive(path: Path, member: tarfile.TarInfo, payload: bytes = b"x") -> Path:
    with tarfile.open(path, "w:gz") as tar:
        tar.addfile(member, io.BytesIO(payload) if member.isfile() else None)
    return path


def test_extraction_refuses_traversal_links_and_oversize(tmp_path):
    escape = tarfile.TarInfo("../escape.txt")
    escape.size = 1
    with pytest.raises(IngestError, match="escapes"):
        safe_extract(unsafe_archive(tmp_path / "a.tar.gz", escape), tmp_path / "out1", 10**6)
    link = tarfile.TarInfo("qlib_bin/link")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    with pytest.raises(IngestError, match="not a regular file"):
        safe_extract(unsafe_archive(tmp_path / "b.tar.gz", link), tmp_path / "out2", 10**6)
    big = tarfile.TarInfo("qlib_bin/big.bin")
    big.size = 100
    with pytest.raises(IngestError, match="size limit"):
        safe_extract(unsafe_archive(tmp_path / "c.tar.gz", big, b"0" * 100), tmp_path / "out3", 10)
    assert not (tmp_path / "escape.txt").exists()
