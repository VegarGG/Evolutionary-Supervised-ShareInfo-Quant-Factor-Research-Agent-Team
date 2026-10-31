"""Bounded, ordered scans of service JSON-lines files; no log database (PLAN Section 15.5).

Files are `<service>/<YYYY-MM-DD>[.partN].jsonl`, gzip-compressed to `.jsonl.gz` by the
nightly job after 7 days. A line lives in the file of its own UTC date, so a scan reads
the days of the range in order and stops as soon as a page and its continuation line are
found: later days hold only later lines. Each raw line is checked for the requested ids,
events, levels and text before it is parsed, so a correlation over a month reads the
files once and parses only the lines that carry the id.
"""

import base64
import gzip
import hashlib
import json
import re
from bisect import insort
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import IO, Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from qfr_core.config import LoggingConfig, MCPConfig, canonical_json
from qfr_core.contracts import Contract, LogLine
from qfr_core.correlation import IDS

# A service's day file, its size parts and their compressed forms. Anything else in a
# service directory (a half-written compression, a stray file) is not a log file.
LOG_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\.part(\d+))?\.jsonl(\.gz)?$")
ID_KINDS = frozenset(
    {"job", "generation", "task", "run", "candidate", "version", "record", "request", "case", "sim"}
)
Key = tuple[str, str, int]


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


def log_files(root: Path) -> Iterator[tuple[date, Path]]:
    """Every log file under root with its day, never following a symlink out of root. When
    a day file exists both plain and compressed (the nightly job stopped between writing
    the archive and removing the original), only the plain file counts."""
    root = root.resolve()
    if not root.is_dir():
        return
    for service in sorted(root.iterdir()):
        if service.is_symlink() or not service.is_dir():
            continue
        names = {p.name for p in service.iterdir()}
        for name in sorted(names):
            match = LOG_FILE.match(name)
            if match is None:
                continue
            if match.group(3) and name.removesuffix(".gz") in names:
                continue
            path = service / name
            if path.is_symlink() or root not in path.resolve().parents:
                continue
            try:
                day = date.fromisoformat(match.group(1))
            except ValueError:
                continue
            yield day, path


def _open(path: Path) -> IO[str]:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


class LogReader:
    def __init__(self, root: Path, logging: LoggingConfig, mcp: MCPConfig) -> None:
        self.root = root.resolve()
        self.logging = logging
        self.mcp = mcp

    def _days(self, services: list[str]) -> dict[date, list[Path]]:
        days: dict[date, list[Path]] = {}
        for day, path in log_files(self.root):
            # A service name is a filter, never interpolated into a path.
            if services and path.parent.name not in services:
                continue
            days.setdefault(day, []).append(path)
        return days

    @staticmethod
    def _prefilter(query: LogQuery) -> list[list[str]]:
        """Substrings a raw line must contain (any of each group) before it is parsed."""
        groups = [[value] for value in query.ids.values()]
        if query.text:
            groups.append([query.text])
        if query.events:
            groups.append(list(query.events))
        if query.levels:
            groups.append(list(query.levels))
        return groups

    def search(
        self,
        query: LogQuery,
        now: datetime | None = None,
        default_span: timedelta | None = None,
    ) -> LogPage:
        """One page of matching lines, oldest first. Without dates the range is the last
        default_search_hours (or default_span, which correlate uses); a range over
        implicit_range_max_days needs both dates unless default_span set it."""
        now = now or datetime.now(UTC)
        limit = query.limit if query.limit is not None else self.mcp.list_default
        if limit > self.mcp.list_max:
            raise ValueError("limit exceeds the configured maximum")
        span = default_span or timedelta(hours=self.logging.default_search_hours)
        start = query.from_time or now - span
        end = query.to_time or now
        explicit = query.from_time is not None and query.to_time is not None
        if (
            end - start > timedelta(days=self.logging.implicit_range_max_days)
            and not explicit
            and default_span is None
        ):
            raise ValueError("long ranges require explicit dates")
        after: Key | None = None
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
        first_day = start.astimezone(UTC).date()
        if after is not None:
            first_day = max(first_day, date.fromisoformat(after[0][:10]))
        last_day = end.astimezone(UTC).date()
        groups = self._prefilter(query)
        found: list[tuple[Key, LogLine]] = []
        scanned = malformed = 0
        days = self._days(query.services)
        for day in sorted(d for d in days if first_day <= d <= last_day):
            for path in days[day]:
                relative = str(path.relative_to(self.root))
                with _open(path) as stream:
                    for number, raw in enumerate(stream):
                        scanned += 1
                        if not all(any(s in raw for s in group) for group in groups):
                            continue
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
                        if any(getattr(line, f) != value for f, value in query.ids.items()):
                            continue
                        if query.text and query.text not in raw:
                            continue
                        key = (line.ts.astimezone(UTC).isoformat(), relative, number)
                        if after is not None and key <= after:
                            continue
                        # Keep only one page plus the continuation sentinel in memory.
                        insort(found, (key, line), key=lambda item: item[0])
                        if len(found) > limit + 1:
                            found.pop()
            if len(found) > limit:
                break  # every line of a later day is later than the page and its sentinel
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
        """The last n lines, reading the newest days first and stopping once n are found."""
        size = self.logging.tail_default if n is None else n
        if not 0 < size <= self.mcp.list_max:
            raise ValueError("tail size outside configured limits")
        days = self._days([service] if service else [])
        retained: list[tuple[Key, LogLine]] = []
        scanned = malformed = 0
        for day in sorted(days, reverse=True):
            rows: list[tuple[Key, LogLine]] = []
            for path in days[day]:
                relative = str(path.relative_to(self.root))
                with _open(path) as stream:
                    for number, raw in enumerate(stream):
                        scanned += 1
                        try:
                            line = LogLine.model_validate_json(raw)
                        except ValueError:
                            malformed += 1
                            continue
                        rows.append(((line.ts.astimezone(UTC).isoformat(), relative, number), line))
            retained = sorted(rows, key=lambda item: item[0]) + retained
            if len(retained) >= size:
                break
        return LogPage(
            lines=[line for _, line in retained[-size:]],
            next_cursor=None,
            scanned=scanned,
            malformed=malformed,
        )

    def correlate(
        self, identifier: str, id_kind: str, query: LogQuery, now: datetime | None = None
    ) -> dict[str, JsonValue]:
        """Every line carrying the id, from every service, oldest first, grouped by service,
        with a one-line timeline. Without dates the last correlate_default_days are read."""
        if id_kind not in ID_KINDS:
            raise ValueError("unsupported id kind")
        query = query.model_copy(update={"ids": query.ids | {f"{id_kind}_id": identifier}})
        page = self.search(
            query, now, default_span=timedelta(days=self.logging.correlate_default_days)
        )
        grouped: dict[str, JsonValue] = {}
        for line in page.lines:
            values = grouped.setdefault(line.service, [])
            if isinstance(values, list):
                values.append(line.model_dump(mode="json", exclude_none=True))
        services: list[JsonValue] = [name for name in sorted(grouped)]
        return {
            "lines": [x.model_dump(mode="json", exclude_none=True) for x in page.lines],
            "grouped_by_service": grouped,
            "services": services,
            "next_cursor": page.next_cursor,
            "scanned": page.scanned,
            "malformed": page.malformed,
            "timeline": " → ".join(f"{line.service}:{line.event}" for line in page.lines),
        }

    def export(
        self, query: LogQuery, target: Path, now: datetime | None = None
    ) -> dict[str, JsonValue]:
        """Write every matching line (up to export_max_lines) as gzip JSON lines to target,
        atomically. Pages never split, so when the cap stops the export the result carries
        the cursor to continue from with the same filters."""
        now = now or datetime.now(UTC)
        cap = self.logging.export_max_lines
        written = scanned = 0
        cursor, next_cursor = query.cursor, None
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(f".{target.name}.partial")
        with gzip.open(staging, "wt", encoding="utf-8") as stream:
            while written < cap:
                page = self.search(
                    query.model_copy(
                        update={"limit": min(self.mcp.list_max, cap - written), "cursor": cursor}
                    ),
                    now,
                )
                scanned += page.scanned
                for line in page.lines:
                    stream.write(canonical_json(line.model_dump(mode="json", exclude_none=True)))
                    stream.write("\n")
                written += len(page.lines)
                next_cursor = cursor = page.next_cursor
                if next_cursor is None:
                    break
        staging.replace(target)
        return {
            "lines": written,
            "scanned": scanned,
            "truncated": next_cursor is not None,
            "next_cursor": next_cursor,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "bytes": target.stat().st_size,
        }
