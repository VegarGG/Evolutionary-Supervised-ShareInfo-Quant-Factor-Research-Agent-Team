"""`qfr data serve`: the data-ingest service's daily full-snapshot builds (PLAN P3.8, 6.4).

Once a day, after deployment.yaml's ingest time (18:30 Asia/Shanghai), the service
builds a new full snapshot and moves the full zone's current pointer:
  - cn: the latest investment_data release, built only when its tag is new;
  - replay: a synthetic world revealed one more trading day per build (tests only).
The research snapshot is never updated within an epoch (Section 6.4), so daily builds
write the full zone only. Old full snapshots are retained so official records stay
reproducible; only the extracted copies of older raw releases are removed, because the
verified archive can always be extracted again. The evaluator registers each new full
snapshot on its next tick; evaluation itself stays pinned to the epoch's snapshot.
"""

import json
import re
import shutil
import time as _time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from qfr_core.config import EpochConfig
from qfr_core.data.snapshot import (
    DateRange,
    SnapshotData,
    SnapshotError,
    SnapshotSource,
    ZoneDirs,
    current_snapshot,
    read_snapshot,
)
from qfr_core.logging import JsonLogger

from qfr_eval.ingest.cn import ingest_cn
from qfr_eval.ingest.config import CnIngestConfig
from qfr_eval.ingest.zones import build_zones, truncate

STATE_FILE = ".ingest_state.json"
Built = tuple[SnapshotData, SnapshotSource, dict[str, Any]]
BuildFn = Callable[[dict[str, Any]], Built | None]


@dataclass(frozen=True)
class Schedule:
    at_local: time
    tz: ZoneInfo

    @classmethod
    def from_deployment(cls, deployment: dict[str, Any]) -> "Schedule":
        hour, minute = (int(x) for x in str(deployment["schedule"]["ingest_local"]).split(":"))
        return cls(time(hour, minute), ZoneInfo(str(deployment["timezone"])))

    def local_day(self, now: datetime) -> date:
        return now.astimezone(self.tz).date()

    def due(self, now: datetime, last_build_day: date | None) -> bool:
        local = now.astimezone(self.tz)
        return local.time() >= self.at_local and (
            last_build_day is None or last_build_day < local.date()
        )


def latest_release_tag(release_url: str, client: httpx.Client) -> str:
    """The tag that GitHub's /releases/latest redirects to (no API token, no JSON)."""
    latest = re.sub(r"/download/\{tag\}/?$", "/latest", release_url)
    if latest == release_url:
        raise ValueError("release_url must end with /download/{tag}")
    response = client.get(latest, follow_redirects=False)
    match = re.search(r"/releases/tag/([^/?#]+)", response.headers.get("location", ""))
    if response.status_code not in (301, 302, 303, 307, 308) or match is None:
        raise RuntimeError(f"no latest-release redirect from {latest}")
    return match.group(1)


def cn_source(
    config: CnIngestConfig,
    raw_dir: Path,
    client: httpx.Client,
    logger: JsonLogger | None = None,
    keep_raw_releases: int = 2,
) -> BuildFn:
    """Build from the latest investment_data release when its tag is new."""

    def build(state: dict[str, Any]) -> Built | None:
        tag = latest_release_tag(config.release_url, client)
        if tag == state.get("release_tag"):
            return None
        data, source = ingest_cn(
            config, raw_dir, archive=None, manifest=None, sha256=None, release_tag=tag,
            logger=logger,
        )  # fmt: skip
        prune_raw(raw_dir, source.archive_sha256, keep_raw_releases)
        return data, source, {"release_tag": tag}

    return build


def prune_raw(raw_dir: Path, current_sha256: str | None, keep_releases: int) -> list[str]:
    """Drop extracted copies except the current one, and all but the newest archives."""
    removed: list[str] = []
    extracted = raw_dir / "extracted"
    if extracted.is_dir():
        for path in extracted.iterdir():
            if path.is_dir() and path.name != current_sha256:
                shutil.rmtree(path, ignore_errors=True)
                removed.append(f"extracted/{path.name}")
    releases = raw_dir / "investment_data"
    if releases.is_dir():
        folders = sorted(
            (p for p in releases.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in folders[max(keep_releases, 1) :]:
            shutil.rmtree(path, ignore_errors=True)
            removed.append(f"investment_data/{path.name}")
    return removed


def replay_source(data: SnapshotData, source: SnapshotSource, first: date) -> BuildFn:
    """Reveal the synthetic world through one more trading day per build, from `first`."""
    dates = data.calendar.get_column("date").to_list()
    start = next((i for i, d in enumerate(dates) if d >= first), len(dates))

    def build(state: dict[str, Any]) -> Built | None:
        index = start + int(state.get("replay_builds", 0))
        if index >= len(dates):
            return None
        cut: date = dates[index]
        part = truncate(data, DateRange(start=dates[0], end=cut))
        details = dict(source.source_details) | {"replay_through": cut.isoformat()}
        revealed = SnapshotSource(
            source.source, source.release_tag, source.archive_sha256, details,
            source.conventions, source.checks,
        )  # fmt: skip
        snapshot = SnapshotData(part.panel, part.membership, part.calendar, dict(data.extras))
        return snapshot, revealed, {"replay_builds": index - start + 1, "through": cut.isoformat()}

    return build


class IngestService:
    """One daily build per local day; a failed or empty check is retried later."""

    def __init__(
        self,
        dirs: ZoneDirs,
        epoch: EpochConfig,
        schedule: Schedule,
        build_fn: BuildFn,
        logger: JsonLogger,
        recheck_seconds: float = 3600,
    ) -> None:
        self.dirs, self.epoch, self.schedule, self.build_fn = dirs, epoch, schedule, build_fn
        self.log, self.recheck = logger.logger, timedelta(seconds=recheck_seconds)
        self.state_path = dirs.full / STATE_FILE

    def state(self) -> dict[str, Any]:
        if self.state_path.is_file():
            return dict(json.loads(self.state_path.read_text(encoding="utf-8")))
        try:  # first start after `qfr data build`: remember what is already current
            manifest = read_snapshot(current_snapshot(self.dirs.full), verify=False).manifest
        except SnapshotError:
            return {}
        return {"release_tag": manifest.release_tag} if manifest.release_tag else {}

    def _save(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, sort_keys=True, default=str) + "\n", encoding="utf-8")
        tmp.replace(self.state_path)

    def run_once(self, now: datetime, force: bool = False) -> dict[str, Any]:
        state = self.state()
        last = state.get("last_build_day")
        last_day = date.fromisoformat(last) if last else None
        retry_at = state.get("retry_after")
        if not force and not self.schedule.due(now, last_day):
            return {"status": "not_due"}
        if not force and retry_at and now < datetime.fromisoformat(retry_at):
            return {"status": "waiting", "retry_after": retry_at}
        day = self.schedule.local_day(now).isoformat()
        try:
            built = self.build_fn(state)
        except Exception as error:
            self._save(state | {"retry_after": (now + self.recheck).isoformat()})
            self.log.error(
                "ingest_daily_build_failed",
                outcome="failed",
                error_type=type(error).__name__,
                payload={"day": day, "message": str(error)},
            )
            return {"status": "failed", "error": type(error).__name__}
        if built is None:
            # No new release yet (weekends, holidays, a late upload): check again later.
            self._save(state | {"retry_after": (now + self.recheck).isoformat()})
            self.log.info("ingest_no_new_data", outcome="skipped", payload={"day": day})
            return {"status": "no_new_data"}
        data, source, update = built
        result = build_zones(self.dirs, data, source, self.epoch, ["full"])
        full = result.snapshots["full"]
        state = {k: v for k, v in state.items() if k != "retry_after"} | update
        self._save(state | {"last_build_day": day, "full_snapshot_id": full.snapshot_id})
        self.log.info(
            "ingest_daily_build",
            outcome="ok",
            payload={
                "day": day,
                "snapshot_id": full.snapshot_id,
                "last_date": full.manifest.date_range.end.isoformat(),
            }
            | update,
        )
        return {"status": "built", "snapshot_id": full.snapshot_id} | update

    def serve(self, check_seconds: float, stop: Callable[[], bool] = lambda: False) -> None:
        while not stop():
            try:
                self.run_once(datetime.now(UTC))
            except Exception:
                self.log.exception("ingest_loop_failed", outcome="failed")
            _time.sleep(check_seconds)
