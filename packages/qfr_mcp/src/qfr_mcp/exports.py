"""Deliverable export bundles (PLAN Sections 13.4 and 17.4, task P7.1).

qfr.deliverable.export writes one deliverable to exports/<job_id>/<deliverable_id>/:

  deliverable.json        deliverable/1 composed with owner-grade evidence (owner_only)
  iteration_history.md    every item's lineage hop by hop, with the evaluator's records
  bundle.json             export_bundle/1: the items and every file with its schema
  MANIFEST.sha256         `<sha256>  <path>` for every other file (shasum -a 256 -c)
  items/<version_id>/
    manifest.json         factor_manifest/1 or strategy_manifest/1
    trace.json            trace/1 of the version and its ancestors (research's export)
    owner_records.json    owner_evidence/1 of the version and each recorded ancestor
    series/<window>-<kind>-<run_id>.parquet and .csv
                          the evaluator's NAV, daily RankIC and long-short returns
    series/sim-<purpose>-<sim_id>-nav.parquet and .csv
                          each simulation account's daily NAV

The bundle is written to a hidden staging folder and renamed into place, so a reader
never sees half a bundle; exporting again replaces the folder. `qfr export verify`
re-checks every hash and validates every JSON file against its published schema.
"""

import hashlib
import io
import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

import jsonschema
import polars as pl
import typer
from pydantic import JsonValue
from qfr_core.config import canonical_json
from qfr_core.contracts import (
    HYGIENE_WARNING,
    BundleFile,
    BundleItem,
    BundleSchema,
    Deliverable,
    ExportBundle,
    FactorManifest,
    StrategyManifest,
    TraceExport,
)

MANIFEST = "MANIFEST.sha256"
INDEX = "bundle.json"
SCHEMA_FILES: dict[str, str] = {
    "deliverable": "public/deliverable.json",
    "factor_manifest": "public/factor_manifest.json",
    "strategy_manifest": "public/strategy_manifest.json",
    "trace_export": "public/trace_export.json",
    "export_bundle": "public/export_bundle.json",
    "owner_evidence": "private/owner_evidence.json",
}


def _json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class ItemSources:
    """What the front door fetched for one deliverable item."""

    version_id: UUID
    kind: Literal["factor", "strategy"]
    manifest: dict[str, JsonValue]
    trace: TraceExport
    deliverable_trace_hash: str
    owner_records: dict[str, JsonValue]
    history_markdown: str
    # (window, kind, run_id) -> Parquet bytes, already checked against the evaluator's hash.
    series: dict[tuple[str, str, str], bytes] = field(default_factory=dict)
    # (purpose, sim_id) -> daily NAV rows.
    sims: dict[tuple[str, str], list[dict[str, JsonValue]]] = field(default_factory=dict)


@dataclass
class Written:
    path: Path
    relative: str
    manifest_sha256: str
    bundle: ExportBundle


def _csv(parquet: bytes) -> bytes:
    buffer = io.BytesIO()
    pl.read_parquet(io.BytesIO(parquet)).write_csv(buffer)
    return buffer.getvalue()


def _frame_bytes(rows: list[dict[str, JsonValue]]) -> tuple[bytes, bytes]:
    frame = pl.DataFrame(rows) if rows else pl.DataFrame()
    parquet, csv = io.BytesIO(), io.BytesIO()
    frame.write_parquet(parquet, statistics=False)
    frame.write_csv(csv)
    return parquet.getvalue(), csv.getvalue()


Evidence = Literal["ok", "evaluator_not_configured", "evaluator_unavailable"]
EVIDENCE: tuple[Evidence, ...] = ("ok", "evaluator_not_configured", "evaluator_unavailable")


def write_bundle(
    exports: Path,
    deliverable: dict[str, JsonValue],
    items: list[ItemSources],
    evidence: Evidence,
    exported_at: datetime,
) -> Written:
    """Write the bundle atomically and return where it is and its manifest's hash."""
    document = Deliverable.model_validate(deliverable)
    job_id, deliverable_id = str(document.job_id), str(document.deliverable_id)
    target = exports / job_id / deliverable_id
    staging = exports / job_id / f".{deliverable_id}.partial"
    if staging.exists():
        shutil.rmtree(staging)
    files: dict[str, tuple[bytes, BundleSchema | None]] = {}
    files["deliverable.json"] = (_json(deliverable), "deliverable")
    history = [f"# Iteration history of deliverable {deliverable_id}", ""]
    bundle_items: list[BundleItem] = []
    for item in items:
        folder = f"items/{item.version_id}"
        manifest_schema: BundleSchema = (
            "factor_manifest" if item.kind == "factor" else "strategy_manifest"
        )
        model = FactorManifest if item.kind == "factor" else StrategyManifest
        model.model_validate(item.manifest)
        files[f"{folder}/manifest.json"] = (_json(item.manifest), manifest_schema)
        trace = item.trace.model_dump(mode="json", exclude={"owner_records"})
        files[f"{folder}/trace.json"] = (_json(trace), "trace_export")
        files[f"{folder}/owner_records.json"] = (_json(item.owner_records), "owner_records")
        for (window, kind, run_id), parquet in sorted(item.series.items()):
            stem = f"{folder}/series/{window}-{kind}-{run_id}"
            files[f"{stem}.parquet"] = (parquet, None)
            files[f"{stem}.csv"] = (_csv(parquet), None)
        for (purpose, sim_id), rows in sorted(item.sims.items()):
            parquet, csv = _frame_bytes(rows)
            stem = f"{folder}/series/sim-{purpose}-{sim_id}-nav"
            files[f"{stem}.parquet"] = (parquet, None)
            files[f"{stem}.csv"] = (csv, None)
        trace_hash = _sha(canonical_json(trace).encode())
        bundle_items.append(
            BundleItem(
                version_id=item.version_id,
                kind=item.kind,
                directory=folder,
                trace_hash=trace_hash,
                trace_hash_matches_deliverable=trace_hash == item.deliverable_trace_hash,
            )
        )
        history += [f"## {item.kind} {item.version_id}", "", item.history_markdown.rstrip(), ""]
    files["iteration_history.md"] = ("\n".join(history).encode(), None)
    bundle = ExportBundle(
        schema_version="export_bundle/1",
        deliverable_id=document.deliverable_id,
        job_id=document.job_id,
        exported_at=exported_at,
        visibility="owner_only",
        hygiene_warning=HYGIENE_WARNING,
        evidence=evidence,
        short_codes=list(document.short_codes),
        items=bundle_items,
        files=[
            BundleFile(path=path, sha256=_sha(data), bytes=len(data), schema_name=schema)
            for path, (data, schema) in sorted(files.items())
        ],
    )
    files[INDEX] = (_json(bundle.model_dump(mode="json")), None)
    manifest = "".join(f"{_sha(data)}  {path}\n" for path, (data, _) in sorted(files.items()))
    for path, (data, _) in files.items():
        destination = staging / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (staging / MANIFEST).write_text(manifest)
    if target.exists():
        retired = exports / job_id / f".{deliverable_id}.replaced"
        if retired.exists():
            shutil.rmtree(retired)
        target.rename(retired)
        staging.rename(target)
        shutil.rmtree(retired)
    else:
        staging.rename(target)
    return Written(
        path=target,
        relative=f"exports/{job_id}/{deliverable_id}",
        manifest_sha256=_sha(manifest.encode()),
        bundle=bundle,
    )


# Verification ------------------------------------------------------------------------


def _validator(schemas: Path, name: str) -> jsonschema.protocols.Validator:
    schema = json.loads((schemas / SCHEMA_FILES[name]).read_text())
    cls = jsonschema.validators.validator_for(schema)
    return cls(schema)


def verify_bundle(path: Path, schemas: Path) -> dict[str, Any]:
    """Re-check a bundle: every hash in MANIFEST.sha256, no file missing or extra, the
    index against export_bundle/1, every JSON file against its schema, each trace.json
    against the trace_hash the index records, and each series Parquet against the hash
    the evaluator recorded for it in deliverable.json."""
    errors: list[str] = []
    checked: dict[str, int] = {"hashes": 0, "schemas": 0, "series": 0, "traces": 0}
    manifest_path = path / MANIFEST
    if not manifest_path.is_file():
        return {"ok": False, "path": str(path), "errors": ["MANIFEST.sha256 is missing"]}
    listed: dict[str, str] = {}
    for line in manifest_path.read_text().splitlines():
        digest, _, name = line.partition("  ")
        listed[name] = digest
    present = {p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()} - {MANIFEST}
    for name in sorted(present - set(listed)):
        errors.append(f"{name}: not in MANIFEST.sha256")
    for name, digest in sorted(listed.items()):
        file = path / name
        if not file.is_file():
            errors.append(f"{name}: listed but missing")
            continue
        checked["hashes"] += 1
        if _sha(file.read_bytes()) != digest:
            errors.append(f"{name}: SHA-256 differs from MANIFEST.sha256")
    if errors:
        return {"ok": False, "path": str(path), "checked": checked, "errors": errors}
    index = json.loads((path / INDEX).read_text())
    for error in _validator(schemas, "export_bundle").iter_errors(index):
        errors.append(f"{INDEX}: {error.message}")
    checked["schemas"] += 1
    bundle = ExportBundle.model_validate(index)
    if {f.path for f in bundle.files} != set(listed) - {INDEX}:
        errors.append(f"{INDEX}: its file list differs from MANIFEST.sha256")
    evidence_check = _validator(schemas, "owner_evidence")
    for entry in bundle.files:
        if entry.schema_name is None:
            continue
        value = json.loads((path / entry.path).read_text())
        documents = (
            list(value.get("versions", {}).values())
            if entry.schema_name == "owner_records"
            else [value]
        )
        check = (
            evidence_check
            if entry.schema_name == "owner_records"
            else _validator(schemas, entry.schema_name)
        )
        for document in documents:
            checked["schemas"] += 1
            for error in check.iter_errors(document):
                errors.append(f"{entry.path}: {error.message}")
    deliverable = json.loads((path / "deliverable.json").read_text())
    for item in deliverable["items"]:
        if item.get("owner_evidence") is not None:
            checked["schemas"] += 1
            for error in evidence_check.iter_errors(item["owner_evidence"]):
                errors.append(f"deliverable.json owner_evidence: {error.message}")
    for bundled in bundle.items:
        trace = json.loads((path / bundled.directory / "trace.json").read_text())
        checked["traces"] += 1
        if _sha(canonical_json(trace).encode()) != bundled.trace_hash:
            errors.append(f"{bundled.directory}/trace.json: trace_hash differs")
    for item in deliverable["items"]:
        evidence = item.get("owner_evidence") or {}
        for ref in evidence.get("series", []):
            name = (
                f"items/{item['version_id']}/series/"
                f"{ref['window']}-{ref['kind']}-{ref['run_id']}.parquet"
            )
            checked["series"] += 1
            if name not in listed:
                errors.append(f"{name}: the evaluator's series is missing")
            elif listed[name] != ref["sha256"]:
                errors.append(f"{name}: differs from the evaluator's recorded SHA-256")
    return {"ok": not errors, "path": str(path), "checked": checked, "errors": errors}


app = typer.Typer(help="Check deliverable export bundles written to exports/.")


@app.command("verify")
def verify(
    path: Annotated[Path, typer.Argument(help="A bundle folder: exports/<job>/<deliverable>")],
    schemas: Annotated[Path, typer.Option(help="The published JSON schemas")] = Path("schemas"),
) -> None:
    """Re-check every hash and schema of an export bundle (SC8)."""
    report = verify_bundle(path, schemas)
    report["verified_at"] = datetime.now(UTC).isoformat()
    typer.echo(json.dumps(report, indent=2, sort_keys=True))
    if not report["ok"]:
        raise typer.Exit(1)
