"""Read original files only; never import or run the frozen model or recompute metrics."""

import argparse
import csv
import gzip
import hashlib
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIRS = {"P0": "P0_English_Delivery_20261022", "P1": "P1_English_Delivery_20261022"}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def csv_rows(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def metadata(path, spec=None):
    columns, rows = csv_rows(path)
    result = dict(sha256=sha(path), bytes=path.stat().st_size, rows=len(rows), columns=columns)
    if spec is not None:
        date_column = spec["date_column"]
        values = (
            [
                datetime.strptime(row[date_column], spec["date_format"]).date().isoformat()
                for row in rows
            ]
            if date_column
            else []
        )
        result["date_range"] = {"start": min(values), "end": max(values)} if values else None
        result["date_column"] = date_column
        result["date_format"] = spec["date_format"]
    return result


def verified_source(package, relative):
    manifest = json.loads((package / "SHA256SUMS.json").read_text())
    expected = manifest["files"][relative]["sha256"]
    if sha(package / relative) != expected:
        raise ValueError(f"Original source checksum mismatch: {package.name}/{relative}")
    return expected


def selected_rows(package, relative, predicate):
    columns, rows = csv_rows(package / relative)
    return dict(
        path=relative,
        sha256=verified_source(package, relative),
        columns=columns,
        selected_rows=[
            dict(source_csv_row=index, values=row)
            for index, row in enumerate(rows, start=2)
            if predicate(row)
        ],
    )


def extract(pilot_root):
    specifications = json.loads((ROOT / "fixtures/pilot/appendix-a3-spec.json").read_text())
    outputs = {}
    for name, spec in specifications.items():
        observed = {}
        for model, dirname in PACKAGE_DIRS.items():
            package = pilot_root / dirname
            verified_source(package, spec["path"])
            info = metadata(package / spec["path"], spec)
            assert info["rows"] == spec["rows"], f"Appendix A.3 row mismatch: {model}/{name}"
            assert len(info["columns"]) == spec["column_count"], f"Column count mismatch: {name}"
            expected_range = (
                dict(start=spec["start"], end=spec["end"]) if spec["date_column"] else None
            )
            assert info["date_range"] == expected_range, f"Appendix A.3 date mismatch: {name}"
            observed[model] = info
        assert observed["P0"] == observed["P1"], f"P0/P1 source mismatch: {name}"
        outputs[f"manifests/{name}.json"] = dict(
            schema_version="1",
            asset_id=name,
            path=spec["path"],
            packages=PACKAGE_DIRS,
            **observed["P1"],
            grain=spec["grain"],
            source=(
                "Appendix A.3 counts/ranges; full headers and hashes from original verified files"
            ),
            licence="Licensed iFinD data remain at owner-provided local path",
            logical_sha256=None,
            logical_hash_status="canonicalization deferred to Stage 1",
            exposure="previously_seen",
            vintage_status="unknown",
            timing_grade=(
                None
                if name == "industry_labels"
                else "B"
                if name in {"stock_finance", "features", "industry_signal_panel"}
                else "A"
            ),
            timing_basis=(
                "not_applicable"
                if name == "industry_labels"
                else "documented_financial_availability_rule"
                if name in {"stock_finance", "features", "industry_signal_panel"}
                else "observation_dates_only"
            ),
            membership_status="backfilled"
            if name in {"stock_finance", "features", "industry_signal_panel"}
            else "unknown",
        )
    golden = dict(
        schema_version="1",
        source="Original machine-readable files, never rounded Appendix A.6 prose",
        extraction="Exact CSV strings and file digests only; no factor or evaluation execution",
        exposure="previously_seen",
        packages={},
        aggregates={},
        ledgers={},
        reference_outputs={},
    )
    for model, dirname in PACKAGE_DIRS.items():
        package = pilot_root / dirname
        golden["packages"][model] = dict(
            directory=dirname, integrity_manifest_sha256=sha(package / "SHA256SUMS.json")
        )
        golden["aggregates"][model] = {
            "report_2026": selected_rows(
                package,
                "validation/report_2026/summary.csv",
                lambda row: row["group_name"] == "p60",
            ),
            "primary_window": selected_rows(
                package,
                "validation/source_evidence/algorithm_v4/evaluation_v1/window_metrics.csv",
                lambda row, model=model: (
                    row["window_kind"] == "primary"
                    and row["window"] == "2024-2026"
                    and row["variant"] == ("baseline" if model == "P0" else "P1_reversal_momentum")
                ),
            ),
        }
        ledger_path = "validation/report_2026/evaluation_ledger.csv"
        _, rows = csv_rows(package / ledger_path)
        counts = Counter(
            (row["model_cycle"], row["status"], row["in_execution_cohort"])
            for row in rows
            if row["group_name"] == "p60"
        )
        golden["ledgers"][model] = dict(
            path=ledger_path,
            sha256=verified_source(package, ledger_path),
            p60_counts=[
                dict(cycle=k[0], status=k[1], in_execution_cohort=k[2], rows=v)
                for k, v in sorted(counts.items())
            ],
        )
        refs = []
        for path in sorted((package / "reference_outputs").rglob("*.csv")):
            relative = path.relative_to(package).as_posix()
            verified_source(package, relative)
            refs.append(dict(path=relative, **metadata(path)))
        assert len(refs) == 24, f"{model} business CSV count differs from original oracle"
        golden["reference_outputs"][model] = refs
    p1 = pilot_root / PACKAGE_DIRS["P1"]
    selections = {
        "paired_intervals": (
            "validation/audit/original_primary_macro_intervals.csv",
            lambda row: row["metric"] == "extreme_macro_recall",
        ),
        "neighborhood_ranges": (
            "validation/robustness_results_v1/parameter_sensitivity.csv",
            lambda row: row["window_kind"] == "primary" and row["metric"] == "extreme_macro_recall",
        ),
        "neighborhood_values": (
            "validation/robustness_results_v1/window_metrics.csv",
            lambda row: row["window_kind"] == "primary",
        ),
        "leave_one_year_out": (
            "validation/audit/leave_one_year_out.csv",
            lambda row: row["metric"] == "extreme_macro_recall",
        ),
        "calendar_shift": (
            "validation/audit/circular_shift_summary.csv",
            lambda row: row["metric"] == "extreme_macro_recall",
        ),
    }
    for name, (relative, predicate) in selections.items():
        golden["aggregates"]["P1"][name] = selected_rows(p1, relative, predicate)
        assert golden["aggregates"]["P1"][name]["selected_rows"], name
    outputs["golden_evidence.json"] = golden
    return outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = os.environ.get("QFR_PILOT_ROOT")
    if not root:
        raise SystemExit(
            "Set QFR_PILOT_ROOT to the parent of the original P0 and P1 package folders"
        )
    for filename, content in extract(Path(root)).items():
        path = ROOT / "fixtures/pilot" / filename
        rendered = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if path.exists():
            if path.read_text() != rendered:
                raise SystemExit(
                    f"Oracle drift: {filename}; original evidence and a recorded decision required"
                )
        elif args.check:
            raise SystemExit(f"Missing fixture: {filename}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered)
    print("Verified seven manifests, both 24-CSV oracles and exact source evidence.")


if __name__ == "__main__":
    main()
