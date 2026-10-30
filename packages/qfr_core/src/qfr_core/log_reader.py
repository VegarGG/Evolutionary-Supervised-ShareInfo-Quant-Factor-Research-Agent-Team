"""Bounded, ordered scans of service JSON-lines files; no log database."""

import base64
import gzip
import hashlib
import json
from bisect import insort
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from qfr_core.config import LoggingConfig, MCPConfig, canonical_json
from qfr_core.contracts import Contract, LogLine
from qfr_core.correlation import IDS


class LogQuery(Contract):
    from_time: AwareDatetime | None = Field(default=None, alias="from")
    to_time: AwareDatetime | None = Field(default=None, alias="to")
    services: list[str] = Field(default_factory=list)
    levels: list[Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]] = Field(
        default_factory=list
    )
    events: list[str] = Field(default_factory=list)
    ids: dict[str, str] = Field(default_factory=dict)
    text: str | None = None
    cursor: str | None = None
    limit: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def safe_ids(self) -> "LogQuery":
        if set(self.ids) - IDS:
            raise ValueError("unsupported correlation id field")
        if self.from_time and self.to_time and self.from_time > self.to_time:
            raise ValueError("from must precede to")
        return self


class LogPage(Contract):
    lines: list[LogLine]
    next_cursor: str | None
    scanned: int
    malformed: int


class LogReader:
    def __init__(self, root: Path, logging: LoggingConfig, mcp: MCPConfig) -> None:
        self.root = root.resolve()
        self.logging = logging
        self.mcp = mcp

    def search(self, query: LogQuery, now: datetime | None = None) -> LogPage:
        now = now or datetime.now(UTC)
        limit = query.limit if query.limit is not None else self.mcp.list_default
        if limit > self.mcp.list_max:
            raise ValueError("limit exceeds the configured maximum")
        start = query.from_time or now - timedelta(hours=self.logging.default_search_hours)
        end = query.to_time or now
        if (end - start) > timedelta(days=self.logging.implicit_range_max_days) and (
            query.from_time is None or query.to_time is None
        ):
            raise ValueError("long ranges require explicit dates")
        after: tuple[str, str, int] | None = None
        fingerprint_fields = query.model_dump(
            mode="json", by_alias=True, exclude={"cursor", "limit"}
        )
        signature = hashlib.sha256(canonical_json(fingerprint_fields).encode()).hexdigest()
        if query.cursor:
            try:
                saved = json.loads(base64.urlsafe_b64decode(query.cursor))
                if saved["signature"] != signature:
                    raise ValueError("cursor belongs to another query")
                start, end = (
                    datetime.fromisoformat(saved["start"]),
                    datetime.fromisoformat(saved["end"]),
                )
                after = (str(saved["after"][0]), str(saved["after"][1]), int(saved["after"][2]))
            except (KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ValueError("invalid cursor") from error
        found: list[tuple[tuple[str, str, int], LogLine]] = []
        scanned = malformed = 0
        for path in sorted(self.root.glob("*/*.jsonl*")):
            # A service name is a filter, never interpolated into a path. Reject symlinks.
            if (
                path.is_symlink()
                or path.parent.is_symlink()
                or self.root not in path.resolve().parents
            ):
                continue
            if query.services and path.parent.name not in query.services:
                continue
            if path.name[:10] < start.date().isoformat() or path.name[:10] > end.date().isoformat():
                continue
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8") as stream:
                for number, raw in enumerate(stream):
                    scanned += 1
                    try:
                        line = LogLine.model_validate_json(raw)
                    except ValueError:
                        malformed += 1
                        continue
                    if not start <= line.ts <= end:
                        continue
                    if query.levels and line.level not in query.levels:
                        continue
                    if query.events and line.event not in query.events:
                        continue
                    if any(getattr(line, field) != value for field, value in query.ids.items()):
                        continue
                    if query.text and query.text not in raw:
                        continue
                    key = (
                        line.ts.astimezone(UTC).isoformat(),
                        str(path.relative_to(self.root)),
                        number,
                    )
                    if after is not None and key <= after:
                        continue
                    # Keep only one page plus the continuation sentinel in memory.
                    insort(found, (key, line), key=lambda item: item[0])
                    if len(found) > limit + 1:
                        found.pop()
        selected = found[:limit]
        cursor = None
        if len(found) > limit:
            payload = {
                "signature": signature,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "after": list(selected[-1][0]),
            }
            cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        return LogPage(
            lines=[v for _, v in selected], next_cursor=cursor, scanned=scanned, malformed=malformed
        )

    def tail(self, service: str | None = None, n: int | None = None) -> LogPage:
        size = self.logging.tail_default if n is None else n
        if not 0 < size <= self.mcp.list_max:
            raise ValueError("tail size outside configured limits")
        # Page through all dates, retaining only the last n rows.
        query = LogQuery.model_validate(
            {
                "from": "1970-01-01T00:00:00Z",
                "to": datetime.now(UTC).isoformat(),
                "services": [service] if service else [],
                "limit": self.mcp.list_max,
            }
        )
        retained: list[LogLine] = []
        scanned = malformed = 0
        while True:
            page = self.search(query)
            retained = (retained + page.lines)[-size:]
            scanned, malformed = page.scanned, page.malformed
            if page.next_cursor is None:
                break
            query = query.model_copy(update={"cursor": page.next_cursor})
        return LogPage(lines=retained, next_cursor=None, scanned=scanned, malformed=malformed)

    def correlate(self, identifier: str, id_kind: str, query: LogQuery) -> dict[str, JsonValue]:
        allowed = {
            "job",
            "generation",
            "task",
            "run",
            "candidate",
            "version",
            "record",
            "request",
            "case",
            "sim",
        }
        if id_kind not in allowed:
            raise ValueError("unsupported id kind")
        query = query.model_copy(update={"ids": query.ids | {f"{id_kind}_id": identifier}})
        page = self.search(query)
        grouped: dict[str, JsonValue] = {}
        for line in page.lines:
            values = grouped.setdefault(line.service, [])
            if isinstance(values, list):
                values.append(line.model_dump(mode="json", exclude_none=True))
        return {
            "lines": [x.model_dump(mode="json", exclude_none=True) for x in page.lines],
            "grouped_by_service": grouped,
            "next_cursor": page.next_cursor,
            "scanned": page.scanned,
            "malformed": page.malformed,
            "timeline": " → ".join(f"{line.service}:{line.event}" for line in page.lines),
        }
