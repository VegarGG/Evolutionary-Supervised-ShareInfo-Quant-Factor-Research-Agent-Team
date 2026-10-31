"""Raw factor pool import through the front door (PLAN Section 13.6; SET-01, SET-02).

For every valid entry, factors first and then strategies over them:

  1. The entry digest (its definition without tags) is looked up in control_db. A digest
     seen before reuses the manifest stored with its DSL_VALIDATED step, so a re-import
     publishes byte-identical content and the registry answers idempotently.
  2. Otherwise the seed manifest is built (a new version of the same family when the
     name was imported before) and its DSL_VALIDATED step is written first.
  3. The manifest is published with publish key seed:<digest>, the version is added to
     its pool as a seed carrying the setup reference, and SEEDS_PUBLISHED is written.

Invalid entries are reported with reason codes, logged and skipped. The setup reference
is the state_id of the "importing" setup_state row; the final row records the counts.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue
from qfr_core.config import MCPConfig
from qfr_core.contracts import Contract, FactorManifest, ReasonCode, StrategyManifest, TraceStep
from qfr_core.correlation import bind, current
from qfr_core.dsl import DslLimits
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from qfr_core.pool_import import (
    NO_DEFAULTS_NOTICE,
    EntryError,
    ImportFileError,
    InvalidEntry,
    SeedIds,
    ValidEntry,
    entry_digest,
    factor_seed_manifest,
    parse_import_file,
    qfr_core_version,
    strategy_seed_manifest,
    validate_entries,
)
from qfr_core.registry_api import (
    AddEntryRequest,
    AppendEventRequest,
    PoolCounts,
    PublishResponse,
    RegistrySummary,
)

from qfr_mcp.control_store import ControlStore, SetupState
from qfr_mcp.imports import ImportPathError, read_import
from qfr_mcp.registry_client import RegistryClient, RegistryRefused, RegistryUnavailable

ACTOR = "qfr-mcp/pool-import"
Kind = Literal["factor", "strategy"]


class ImportRejected(ValueError):
    """The request as a whole is refused; nothing was imported."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


class RegistryFailure(Contract):
    status: int
    error: str
    message: str


class EntryOutcome(Contract):
    index: int
    name: str | None
    kind: Kind | None
    outcome: Literal["published", "unchanged", "invalid", "failed"]
    version_id: UUID | None = None
    family_id: UUID | None = None
    version_no: int | None = None
    content_hash: str | None = None
    entry_id: UUID | None = None
    reasons: list[EntryError] = Field(default_factory=list)
    registry_error: RegistryFailure | None = None


class ImportCounts(Contract):
    entries: int = 0
    published: int = 0
    unchanged: int = 0
    invalid: int = 0
    failed: int = 0


class ImportReport(Contract):
    setup_ref: UUID | None
    source: dict[str, JsonValue]
    counts: ImportCounts
    entries: list[EntryOutcome]
    pool_counts: dict[str, PoolCounts]
    notice: str | None


def pool_counts(summary: RegistrySummary) -> dict[str, PoolCounts]:
    return {"factor": summary.factor_pool, "strategy": summary.strategy_pool}


class PoolImporter:
    def __init__(
        self,
        registry: RegistryClient,
        control: ControlStore,
        limits: DslLimits,
        config: MCPConfig,
        imports_dir: Path | None,
        logger: JsonLogger,
    ) -> None:
        self.registry, self.control, self.limits = registry, control, limits
        self.config, self.imports_dir, self.logger = config, imports_dir, logger
        # One import at a time: digest lookups and family resolution assume no
        # concurrent import is publishing the same names.
        self._lock = asyncio.Lock()

    # ---- entry points -------------------------------------------------------------

    async def run(
        self,
        *,
        file: str | None = None,
        entries: list[JsonValue] | None = None,
        no_pool: bool = False,
    ) -> ImportReport:
        if [file is not None, entries is not None, no_pool].count(True) != 1:
            raise self._reject("ARGUMENTS_INVALID", "give exactly one of file, entries or no_pool")
        async with self._lock:
            if no_pool:
                return await self._declare_empty()
            if file is not None:
                data, source = await asyncio.to_thread(self.read_file, file)
                try:
                    raw = parse_import_file(file, data)
                except ImportFileError as error:
                    raise self._reject("IMPORT_FILE_INVALID", str(error)) from None
            else:
                assert entries is not None
                raw, source = entries, {"kind": "inline", "entries": len(entries)}
            if not raw:
                raise self._reject("EMPTY_IMPORT", "there are no entries; use no_pool instead")
            if len(raw) > self.config.import_max_entries:
                raise self._reject(
                    "TOO_MANY_ENTRIES",
                    f"{len(raw)} entries exceed the limit of {self.config.import_max_entries}",
                )
            return await self._import(validate_entries(raw, self.limits), source)

    def read_file(self, name: str) -> tuple[bytes, dict[str, JsonValue]]:
        """Read one file under the imports folder; nothing outside it is reachable."""
        try:
            return read_import(self.imports_dir, name, self.config.import_max_bytes)
        except ImportPathError as error:
            raise self._reject(error.code, error.message) from None

    # ---- helpers ------------------------------------------------------------------

    def _reject(self, code: str, message: str) -> ImportRejected:
        self.logger.logger.warning(
            "pool_import_rejected", outcome="failed", error_code=code, payload={"message": message}
        )
        return ImportRejected(code, message)

    async def _state(self, state_id: UUID, status: str, details: dict[str, JsonValue]) -> None:
        context = current()
        state = SetupState(
            state_id=state_id,
            at=_now(),
            step="pool",
            status=status,
            details=details,
            principal=context.get("principal", "owner"),
            request_id=context["request_id"],
        )
        await asyncio.to_thread(self.control.append_setup_state, state)

    async def _trace(
        self,
        step_id: UUID,
        step_type: Literal["DSL_VALIDATED", "SEEDS_PUBLISHED"],
        candidate_id: UUID,
        version_id: UUID | None,
        inputs: dict[str, JsonValue],
        payload: dict[str, JsonValue],
    ) -> None:
        step = TraceStep(
            schema_version="trace_step/1",
            step_id=step_id,
            at=_now(),
            job_id=None,
            program_id=None,
            generation_id=None,
            task_id=None,
            candidate_id=candidate_id,
            version_id=version_id,
            step_type=step_type,
            actor_kind="deterministic",
            actor=ACTOR,
            inputs=inputs,
            payload=payload,
            outcome="ok",
            request_id=current()["request_id"],
        )
        await asyncio.to_thread(self.control.append_trace_step, step)

    # ---- the empty start ----------------------------------------------------------

    async def _declare_empty(self) -> ImportReport:
        summary = await self.registry.summary()
        counts = pool_counts(summary)
        notice = NO_DEFAULTS_NOTICE if summary.empty else None
        status = "empty" if summary.empty else "kept"
        details: dict[str, JsonValue] = {
            "choice": "no_pool",
            "pool_counts": {k: v.model_dump(mode="json") for k, v in counts.items()},
            "notice": notice,
        }
        await self._state(uuid7(), status, details)
        self.logger.logger.info(
            "setup_pool_declined", outcome="ok", payload={"status": status, "notice": notice}
        )
        return ImportReport(
            setup_ref=None,
            source={"kind": "none"},
            counts=ImportCounts(),
            entries=[],
            pool_counts=counts,
            notice=notice,
        )

    # ---- the import ---------------------------------------------------------------

    async def _import(
        self, results: list[ValidEntry | InvalidEntry], source: dict[str, JsonValue]
    ) -> ImportReport:
        setup_ref = uuid7()
        await self._state(setup_ref, "importing", {"source": source, "entries": len(results)})
        outcomes: dict[int, EntryOutcome] = {}
        factors: dict[str, UUID] = {}
        try:
            for result in results:
                if isinstance(result, InvalidEntry):
                    outcomes[result.index] = self._invalid(
                        result.index, result.name, result.kind, result.errors
                    )
            for result in results:
                if isinstance(result, ValidEntry) and result.entry.kind == "factor":
                    outcome = await self._seed(result, setup_ref, source, None)
                    outcomes[result.index] = outcome
                    if outcome.version_id and outcome.outcome in ("published", "unchanged"):
                        factors[result.entry.name] = outcome.version_id
            for result in results:
                if not isinstance(result, ValidEntry) or result.entry.strategy is None:
                    continue
                names = [c.name for c in result.entry.strategy.components]
                missing = [n for n in names if n not in factors]
                if missing:
                    error = EntryError(
                        reason_code=ReasonCode.COMPONENT_INVALID,
                        message=f"components {missing} were not published in this import",
                        field="strategy.components",
                    )
                    outcomes[result.index] = self._invalid(
                        result.index, result.entry.name, "strategy", [error]
                    )
                    continue
                components = {n: factors[n] for n in names}
                outcomes[result.index] = await self._seed(result, setup_ref, source, components)
        except RegistryUnavailable as error:
            done = [outcomes[i] for i in sorted(outcomes)]
            await self._state(
                uuid7(),
                "failed",
                {
                    "setup_ref": str(setup_ref),
                    "source": source,
                    "counts": _counts(len(results), done).model_dump(mode="json"),
                    "error": str(error),
                },
            )
            self.logger.logger.error(
                "pool_import_failed",
                outcome="failed",
                error_code="REGISTRY_UNAVAILABLE",
                payload={"setup_ref": str(setup_ref)},
            )
            raise
        ordered = [outcomes[i] for i in sorted(outcomes)]
        counts = _counts(len(results), ordered)
        summary = await self.registry.summary()
        notice = NO_DEFAULTS_NOTICE if summary.empty else None
        pools = pool_counts(summary)
        await self._state(
            uuid7(),
            "imported",
            {
                "setup_ref": str(setup_ref),
                "source": source,
                "counts": counts.model_dump(mode="json"),
                "version_ids": [str(o.version_id) for o in ordered if o.version_id],
                "pool_counts": {k: v.model_dump(mode="json") for k, v in pools.items()},
                "notice": notice,
            },
        )
        self.logger.logger.info(
            "pool_import_completed",
            outcome="ok",
            payload={"setup_ref": str(setup_ref), "counts": counts.model_dump(mode="json")},
        )
        return ImportReport(
            setup_ref=setup_ref,
            source=source,
            counts=counts,
            entries=ordered,
            pool_counts=pools,
            notice=notice,
        )

    def _invalid(
        self, index: int, name: str | None, kind: Kind | None, errors: list[EntryError]
    ) -> EntryOutcome:
        self.logger.logger.warning(
            "pool_import_entry_rejected",
            outcome="failed",
            error_code=str(errors[0].reason_code) if errors else None,
            payload={
                "index": index,
                "name": name,
                "kind": kind,
                "reasons": [e.model_dump(mode="json") for e in errors],
            },
        )
        return EntryOutcome(index=index, name=name, kind=kind, outcome="invalid", reasons=errors)

    def _manifest(
        self,
        valid: ValidEntry,
        components: dict[str, UUID] | None,
        ids: SeedIds,
        family_id: UUID | None,
        previous: UUID | None,
    ) -> FactorManifest | StrategyManifest:
        if valid.entry.kind == "factor":
            assert valid.analysis is not None
            return factor_seed_manifest(
                valid.entry, valid.analysis, ids, family_id, previous, qfr_core_version()
            )
        assert components is not None
        return strategy_seed_manifest(
            valid.entry, components, ids, family_id, previous, qfr_core_version()
        )

    async def _seed(
        self,
        valid: ValidEntry,
        setup_ref: UUID,
        source: dict[str, JsonValue],
        components: dict[str, UUID] | None,
    ) -> EntryOutcome:
        entry, kind = valid.entry, valid.entry.kind
        digest = entry_digest(entry, components)
        prior = await asyncio.to_thread(self.control.find_validation, digest)
        manifest: FactorManifest | StrategyManifest
        if prior is not None and prior.candidate_id is not None:
            stored = prior.payload["manifest"]
            model = FactorManifest if kind == "factor" else StrategyManifest
            manifest = model.model_validate(stored)
            candidate_id = prior.candidate_id
        else:
            previous = await asyncio.to_thread(self.control.latest_publication, kind, entry.name)
            family_id = UUID(str(previous.payload["family_id"])) if previous else None
            previous_version = previous.version_id if previous else None
            ids = SeedIds(candidate_id=uuid7(), hypothesis_id=uuid7(), validation_id=uuid7())
            manifest = self._manifest(valid, components, ids, family_id, previous_version)
            checks: JsonValue = (
                valid.analysis.model_dump(mode="json")
                if valid.analysis is not None
                else {"components": {n: str(v) for n, v in (components or {}).items()}}
            )
            await self._trace(
                ids.validation_id,
                "DSL_VALIDATED",
                ids.candidate_id,
                None,
                {
                    "entry_digest": digest,
                    "kind": kind,
                    "name": entry.name,
                    "index": valid.index,
                    "setup_ref": str(setup_ref),
                    "source": source,
                },
                {"checks": checks, "manifest": manifest.model_dump(mode="json")},
            )
            candidate_id = ids.candidate_id
        publish_key = f"seed:{digest}"
        with bind(candidate_id=str(candidate_id)):
            try:
                published = await self.registry.publish(manifest, publish_key)
            except RegistryRefused as refusal:
                return self._failed(valid, refusal, None)
            version = published.version
            with bind(version_id=str(version.version_id), family_id=str(version.family_id)):
                try:
                    added = await self.registry.add_entry(
                        kind,
                        AddEntryRequest(
                            version_id=version.version_id,
                            title=entry.title,
                            status="seed",
                            setup_ref=setup_ref,
                            tags=entry.tags,
                            note=entry.notes,
                        ),
                    )
                    new_tags = [t for t in entry.tags if t not in added.entry.tags]
                    if not added.created and new_tags:
                        await self.registry.append_event(
                            kind,
                            added.entry.entry_id,
                            AppendEventRequest(
                                action="ANNOTATED",
                                tags=new_tags,
                                note=f"Tags added by raw pool import {setup_ref}.",
                            ),
                        )
                except RegistryRefused as refusal:
                    return self._failed(valid, refusal, published)
                created = published.created or added.created
                recorded = await asyncio.to_thread(self.control.publication_of, version.version_id)
                if created or recorded is None:
                    await self._trace(
                        uuid7(),
                        "SEEDS_PUBLISHED",
                        candidate_id,
                        version.version_id,
                        {
                            "setup_ref": str(setup_ref),
                            "entry_digest": digest,
                            "kind": kind,
                            "name": entry.name,
                            "publish_key": publish_key,
                            "source": source,
                        },
                        {
                            "version_id": str(version.version_id),
                            "family_id": str(version.family_id),
                            "version_no": version.version_no,
                            "content_hash": version.content_hash,
                            "canonical_hash": version.canonical_hash,
                            "pool": kind,
                            "entry_id": str(added.entry.entry_id),
                            "version_created": published.created,
                            "entry_created": added.created,
                        },
                    )
                outcome: Literal["published", "unchanged"] = "published" if created else "unchanged"
                self.logger.logger.info(
                    f"pool_import_entry_{outcome}",
                    outcome="ok",
                    payload={
                        "index": valid.index,
                        "name": entry.name,
                        "kind": kind,
                        "entry_id": str(added.entry.entry_id),
                        "version_no": version.version_no,
                    },
                )
        return EntryOutcome(
            index=valid.index,
            name=entry.name,
            kind=kind,
            outcome=outcome,
            version_id=version.version_id,
            family_id=version.family_id,
            version_no=version.version_no,
            content_hash=version.content_hash,
            entry_id=added.entry.entry_id,
        )

    def _failed(
        self, valid: ValidEntry, refusal: RegistryRefused, published: PublishResponse | None
    ) -> EntryOutcome:
        self.logger.logger.warning(
            "pool_import_entry_failed",
            outcome="failed",
            error_code=refusal.error,
            payload={
                "index": valid.index,
                "name": valid.entry.name,
                "kind": valid.entry.kind,
                "registry_error": refusal.as_dict(),
            },
        )
        version = published.version if published else None
        return EntryOutcome(
            index=valid.index,
            name=valid.entry.name,
            kind=valid.entry.kind,
            outcome="failed",
            version_id=version.version_id if version else None,
            family_id=version.family_id if version else None,
            version_no=version.version_no if version else None,
            content_hash=version.content_hash if version else None,
            registry_error=RegistryFailure(
                status=refusal.status, error=refusal.error, message=refusal.message
            ),
        )


def _counts(total: int, outcomes: list[EntryOutcome]) -> ImportCounts:
    tally = {"published": 0, "unchanged": 0, "invalid": 0, "failed": 0}
    for outcome in outcomes:
        tally[outcome.outcome] += 1
    return ImportCounts(entries=total, **tally)


def _now() -> datetime:
    return datetime.now(UTC)
