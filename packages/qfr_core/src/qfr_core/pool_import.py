"""Raw factor pool import, pool_import/1 (PLAN Section 13.6).

Pure functions: parse a file, validate each entry exactly like an agent's draft, and
build the human_seed manifests. The front door does the I/O and the publication.
Invalid entries are reported with reason codes and skipped; no entry is ever applied
partially.
"""

import csv
import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import version
from typing import Literal
from uuid import UUID

import yaml
from pydantic import JsonValue, ValidationError

from qfr_core.config import canonical_json
from qfr_core.contracts import (
    Component,
    Contract,
    FactorDeclaration,
    FactorImplementation,
    FactorManifest,
    Hash,
    PoolImportEntry,
    Provenance,
    Rationale,
    ReasonCode,
    Review,
    StrategyDeclaration,
    StrategyImplementation,
    StrategyManifest,
    StrategyRationale,
)
from qfr_core.dsl import DslAnalysis, DslLimits, validate

SCHEMA_VERSION = "pool_import/1"
FORMATS = (".json", ".yaml", ".yml", ".csv")
CSV_COLUMNS = (
    "name",
    "title",
    "expression",
    "expected_sign",
    "horizon_days",
    "tags",
    "notes",
    "strategy",
)
CSV_REQUIRED = ("name", "title", "expected_sign", "horizon_days")
CSV_TAG_SEPARATOR = ";"
NO_DEFAULTS_NOTICE = (
    "No default factors. No default strategies. Research will start from exploration "
    "only. Library-correlation and novelty checks are vacuous until the pool has entries."
)


class ImportFileError(ValueError):
    """The file as a whole cannot be read; nothing is imported."""

    reason_code = ReasonCode.SCHEMA_INVALID


class EntryError(Contract):
    reason_code: ReasonCode
    message: str
    field: str | None = None


@dataclass(frozen=True)
class ValidEntry:
    index: int
    entry: PoolImportEntry
    analysis: DslAnalysis | None  # Set for factor entries.


@dataclass(frozen=True)
class InvalidEntry:
    index: int
    name: str | None
    kind: Literal["factor", "strategy"] | None
    errors: list[EntryError]


@dataclass(frozen=True)
class SeedIds:
    """Ids a seed's manifest references: the trace candidate, the seed hypothesis and
    the deterministic validation record (the DSL_VALIDATED trace step)."""

    candidate_id: UUID
    hypothesis_id: UUID
    validation_id: UUID


def qfr_core_version() -> str:
    return version("qfr-core")


def _csv_rows(text: str) -> list[JsonValue]:
    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    unknown = sorted(set(header) - set(CSV_COLUMNS))
    missing = [c for c in CSV_REQUIRED if c not in header]
    if unknown or missing:
        raise ImportFileError(f"CSV columns: unknown {unknown}, missing {missing}")
    rows: list[JsonValue] = []
    for raw in reader:
        if None in raw:
            raise ImportFileError(f"CSV row {reader.line_num} has more cells than columns")
        row: dict[str, JsonValue] = {}
        for key, cell in raw.items():
            value = (cell or "").strip()
            if key == "tags":
                row[key] = [t.strip() for t in value.split(CSV_TAG_SEPARATOR) if t.strip()]
            elif not value:
                continue
            elif key in ("expected_sign", "horizon_days"):
                try:
                    row[key] = int(value)
                except ValueError:
                    row[key] = value  # Reported by entry validation with its field.
            elif key == "strategy":
                try:
                    row[key] = json.loads(value)
                except ValueError:
                    row[key] = value
            else:
                row[key] = value
        rows.append(row)
    return rows


def parse_import_file(name: str, data: bytes) -> list[JsonValue]:
    """Return the raw entries of a pool_import/1 file (JSON, YAML or CSV)."""
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in FORMATS:
        raise ImportFileError(f"unsupported file type {suffix or '(none)'}; use {FORMATS}")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ImportFileError("the file is not UTF-8 text") from error
    if suffix == ".csv":
        return _csv_rows(text)
    try:
        document = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as error:
        raise ImportFileError(f"the file is not valid {suffix[1:].upper()}") from error
    if not isinstance(document, dict):
        raise ImportFileError("the file must be a mapping with an entries list")
    unknown = sorted(set(document) - {"schema_version", "entries"})
    if unknown:
        raise ImportFileError(f"unknown top-level keys {unknown}")
    if document.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ImportFileError(f"schema_version must be {SCHEMA_VERSION}")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ImportFileError("entries must be a list")
    return entries


def _schema_errors(error: ValidationError) -> list[EntryError]:
    return [
        EntryError(
            reason_code=ReasonCode.SCHEMA_INVALID,
            message=str(item["msg"]),
            field=".".join(str(p) for p in item["loc"]) or None,
        )
        for item in error.errors()
    ]


def _identity(raw: JsonValue) -> tuple[str | None, Literal["factor", "strategy"] | None]:
    if not isinstance(raw, Mapping):
        return None, None
    name = raw.get("name")
    kind: Literal["factor", "strategy"] | None = None
    if raw.get("strategy") is not None:
        kind = "strategy"
    elif raw.get("expression") is not None:
        kind = "factor"
    return (name if isinstance(name, str) else None), kind


def validate_entries(
    raw_entries: Sequence[JsonValue], limits: DslLimits
) -> list[ValidEntry | InvalidEntry]:
    """Validate every entry on its own, in file order."""
    results: list[ValidEntry | InvalidEntry] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(raw_entries):
        name, kind = _identity(raw)
        try:
            entry = PoolImportEntry.model_validate(raw)
        except ValidationError as error:
            results.append(InvalidEntry(index, name, kind, _schema_errors(error)))
            continue
        if entry.name in seen:
            message = f"duplicate name {entry.name!r}; entry {seen[entry.name]} uses it"
            error_item = EntryError(
                reason_code=ReasonCode.SCHEMA_INVALID, message=message, field="name"
            )
            results.append(InvalidEntry(index, entry.name, entry.kind, [error_item]))
            continue
        seen[entry.name] = index
        if entry.expression is None:
            results.append(ValidEntry(index, entry, None))
            continue
        check = validate(entry.expression, limits)
        if not check.ok:
            errors = [
                EntryError(
                    reason_code=ReasonCode(str(item["code"])),
                    message=str(item["message"]),
                    field="expression",
                )
                for item in check.errors
            ]
            results.append(InvalidEntry(index, entry.name, "factor", errors))
            continue
        results.append(ValidEntry(index, entry, check.analysis))
    valid_factors = {
        r.entry.name for r in results if isinstance(r, ValidEntry) and r.entry.kind == "factor"
    }
    checked: list[ValidEntry | InvalidEntry] = []
    for result in results:
        strategy = result.entry.strategy if isinstance(result, ValidEntry) else None
        if isinstance(result, ValidEntry) and strategy is not None:
            missing = [c.name for c in strategy.components if c.name not in valid_factors]
            if missing:
                error_item = EntryError(
                    reason_code=ReasonCode.COMPONENT_INVALID,
                    message=f"components {missing} are not valid factor entries of this import",
                    field="strategy.components",
                )
                result = InvalidEntry(result.index, result.entry.name, "strategy", [error_item])
        checked.append(result)
    return checked


def entry_digest(entry: PoolImportEntry, components: Mapping[str, UUID] | None = None) -> Hash:
    """Identity of an entry's definition. Tags are pool-entry data and are excluded, so a
    tag change never creates a new version (and a new trial)."""
    strategy: JsonValue = None
    if entry.strategy is not None:
        resolved = components or {}
        strategy = {
            "combination": entry.strategy.combination,
            "portfolio": entry.strategy.portfolio.model_dump(mode="json"),
            "components": [
                {
                    "name": c.name,
                    "sign": c.sign,
                    "weight": c.weight,
                    "version_id": str(resolved[c.name]),
                }
                for c in entry.strategy.components
            ],
        }
    identity: dict[str, JsonValue] = {
        "schema": SCHEMA_VERSION,
        "kind": entry.kind,
        "name": entry.name,
        "title": entry.title,
        "expression": entry.expression.strip() if entry.expression else None,
        "expected_sign": entry.expected_sign,
        "horizon_days": entry.horizon_days,
        "notes": entry.notes,
        "strategy": strategy,
    }
    return hashlib.sha256(canonical_json(identity).encode()).hexdigest()


def _mechanism(entry: PoolImportEntry) -> str:
    return entry.notes or "The owner gave no mechanism for this seed in the import file."


def _provenance(ids: SeedIds, parents: list[UUID], core_version: str) -> Provenance:
    return Provenance(
        job_id=None,
        program_id=None,
        generation_id=None,
        island_id=None,
        operator="human_seed",
        parent_version_ids=parents,
        agent_runs=[],
        trace_ref=ids.candidate_id,
        research_snapshot_id=None,
        qfr_core_version=core_version,
    )


def factor_seed_manifest(
    entry: PoolImportEntry,
    analysis: DslAnalysis,
    ids: SeedIds,
    family_id: UUID | None,
    previous_version_id: UUID | None,
    core_version: str,
) -> FactorManifest:
    assert entry.expression is not None
    direction = "positive" if entry.expected_sign == 1 else "negative"
    change = None
    if previous_version_id is not None:
        change = (
            f"The owner re-imported '{entry.name}' with a changed definition; "
            "this version follows the previously imported one."
        )
    return FactorManifest(
        schema_version="1",
        kind="factor",
        family_id=family_id,
        name=entry.name,
        title=entry.title,
        implementation=FactorImplementation(
            language="qfr-dsl/1", expression=entry.expression.strip()
        ),
        declared=FactorDeclaration(
            expected_sign=entry.expected_sign,
            horizon_days=entry.horizon_days,
            fields_used=list(analysis.fields),
            max_lookback_days=analysis.max_lookback_days,
        ),
        rationale=Rationale(
            hypothesis_id=ids.hypothesis_id,
            summary=f"Seed factor supplied by the owner in a raw pool import: {entry.title}.",
            mechanism=_mechanism(entry),
            falsification=(
                f"The evaluator's official records show no {direction} relation between "
                f"the factor and returns over {entry.horizon_days} trading days."
            ),
            change_summary=change,
        ),
        provenance=_provenance(
            ids, [previous_version_id] if previous_version_id else [], core_version
        ),
        self_assessment=None,
        review=Review(verdict_id=ids.validation_id, rounds=0),
    )


def strategy_seed_manifest(
    entry: PoolImportEntry,
    components: Mapping[str, UUID],
    ids: SeedIds,
    family_id: UUID | None,
    previous_version_id: UUID | None,
    core_version: str,
) -> StrategyManifest:
    strategy = entry.strategy
    assert strategy is not None
    parts = [
        Component(version_id=components[c.name], sign=c.sign, weight=c.weight)
        for c in strategy.components
    ]
    parents = [p.version_id for p in parts]
    change = f"Composed by the owner from {len(parts)} seed factor versions."
    if previous_version_id is not None:
        parents.append(previous_version_id)
        change += " It follows the previously imported version of this strategy."
    listed = "; ".join(
        f"{c.name} (sign {c.sign:+d}, weight {c.weight:g})" for c in strategy.components
    )
    return StrategyManifest(
        schema_version="1",
        kind="strategy",
        family_id=family_id,
        name=entry.name,
        title=entry.title,
        implementation=StrategyImplementation(
            language="qfr-strategy/1",
            components=parts,
            combination=strategy.combination,
            portfolio=strategy.portfolio,
        ),
        declared=StrategyDeclaration(expected_sign=1, horizon_days=entry.horizon_days),
        rationale=StrategyRationale(
            hypothesis_id=ids.hypothesis_id,
            summary=f"Seed strategy supplied by the owner in a raw pool import: {entry.title}.",
            mechanism=_mechanism(entry),
            falsification=(
                "The evaluator's official backtests show the composite does not beat the "
                f"equal-weight benchmark net of costs at the {entry.horizon_days}-day horizon."
            ),
            change_summary=change,
            composition_rationale=f"Components and weights as given by the owner: {listed}.",
        ),
        provenance=_provenance(ids, parents, core_version),
        self_assessment=None,
        review=Review(verdict_id=ids.validation_id, rounds=0),
    )
