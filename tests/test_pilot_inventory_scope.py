"""Synthetic filesystem regression for original-input scope, not pilot parity."""

import os

import pytest
from pilot_inventory import original_package_inventory

from scripts.extract_pilot_evidence import PACKAGE_DIRS


@pytest.fixture
def deliveries(tmp_path):
    for directory in PACKAGE_DIRS.values():
        path = tmp_path / directory / "original_delivery" / "inputs.csv"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"synthetic original bytes\n")
    return tmp_path


def test_sibling_evidence_creation_changes_broad_inventory_but_not_original_inputs(deliveries):
    before = original_package_inventory(deliveries)
    broad_before = {p.relative_to(deliveries) for p in deliveries.rglob("*") if p.is_file()}
    evidence = deliveries / "acceptance-evidence" / "receipt.json"
    evidence.parent.mkdir()
    evidence.write_bytes(b'{"synthetic_result":"pending"}')
    assert {p.relative_to(deliveries) for p in deliveries.rglob("*") if p.is_file()} != broad_before
    assert original_package_inventory(deliveries) == before
    evidence.write_bytes(b'{"synthetic_result":"recorded"}')
    assert original_package_inventory(deliveries) == before
    evidence.unlink()
    assert original_package_inventory(deliveries) == before
    assert len(before) == 2


@pytest.mark.parametrize("model", ["P0", "P1"])
@pytest.mark.parametrize("change", ["bytes", "added", "removed", "renamed"])
def test_every_change_inside_either_original_package_is_detected(deliveries, model, change):
    before = original_package_inventory(deliveries)
    package = deliveries / PACKAGE_DIRS[model]
    original = package / "original_delivery" / "inputs.csv"
    if change == "bytes":
        original.write_bytes(b"changed original bytes\n")
    elif change == "added":
        (package / "unexpected-output.json").write_bytes(b"{}")
    elif change == "renamed":
        original.rename(original.with_suffix(".renamed"))
    else:
        # Retain another file so the inventory comparison tests deletion, not emptiness.
        (package / "retained.txt").write_bytes(b"retained")
        before = original_package_inventory(deliveries)
        original.unlink()
    assert original_package_inventory(deliveries) != before


@pytest.mark.parametrize("model", ["P0", "P1"])
def test_missing_or_empty_package_cannot_be_a_silent_empty_inventory(deliveries, model):
    package = deliveries / PACKAGE_DIRS[model]
    original = package / "original_delivery" / "inputs.csv"
    original.unlink()
    with pytest.raises(ValueError, match="empty"):
        original_package_inventory(deliveries)
    original.parent.rmdir()
    package.rmdir()
    with pytest.raises(ValueError, match="missing or replaced"):
        original_package_inventory(deliveries)


@pytest.mark.parametrize("kind", ["file_link", "directory_link", "package_link", "fifo"])
def test_replaced_or_nonregular_original_files_fail_before_reading(deliveries, kind):
    package = deliveries / PACKAGE_DIRS["P0"]
    if kind == "file_link":
        (package / "alias").symlink_to(package / "original_delivery" / "inputs.csv")
    elif kind == "directory_link":
        (package / "alias").symlink_to(package / "original_delivery", target_is_directory=True)
    elif kind == "package_link":
        renamed = package.with_name("moved-original")
        package.rename(renamed)
        package.symlink_to(renamed, target_is_directory=True)
    else:
        os.mkfifo(package / "not-a-file")
    with pytest.raises(ValueError):
        original_package_inventory(deliveries)
