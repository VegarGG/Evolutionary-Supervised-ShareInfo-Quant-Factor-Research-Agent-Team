"""`qfr data serve` (P3.8): daily full-snapshot builds after the ingest time, the CN
latest-release check, the synthetic replay source, raw cleanup, and the evaluator
registering each new full snapshot while evaluation stays on the epoch's snapshot."""

import io
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from qfr_core.config import logging_config
from qfr_core.data.panel import sanity_checks
from qfr_core.data.snapshot import (
    SnapshotData,
    SnapshotSource,
    ZoneDirs,
    current_snapshot,
    read_snapshot,
)
from qfr_core.logging import JsonLogger
from qfr_eval.ingest.serve import (
    IngestService,
    Schedule,
    latest_release_tag,
    prune_raw,
    replay_source,
)
from qfr_eval.ingest.zones import build_zones

from tests.synthetic_fixtures import BuiltZones, small_epoch

SHANGHAI = ZoneInfo("Asia/Shanghai")
SCHEDULE = Schedule.from_deployment(
    {"timezone": "Asia/Shanghai", "schedule": {"ingest_local": "18:30"}}
)


def local(day: str, at: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{at}").replace(tzinfo=SHANGHAI)


def logger(tmp_path: Path) -> JsonLogger:
    return JsonLogger(
        "data-ingest", "eval", tmp_path, logging_config(Path("configs")), stdout=io.StringIO()
    )


def world_data(zones: BuiltZones) -> tuple[SnapshotData, SnapshotSource]:
    world = zones.world
    data = SnapshotData(world.panel, world.membership, world.calendar)
    source = SnapshotSource(
        "synthetic", None, None, {"world": "planted"}, {}, sanity_checks(world.panel)
    )
    return data, source


def test_the_schedule_is_once_per_local_day_after_the_ingest_time():
    assert not SCHEDULE.due(local("2026-11-02", "18:29"), None)
    assert SCHEDULE.due(local("2026-11-02", "18:30"), None)
    assert not SCHEDULE.due(local("2026-11-02", "23:00"), date(2026, 11, 2))
    assert SCHEDULE.due(local("2026-11-03", "18:31"), date(2026, 11, 2))
    # 18:30 Shanghai is 10:30 UTC.
    assert SCHEDULE.due(datetime(2026, 11, 3, 10, 30, tzinfo=UTC), date(2026, 11, 2))


def test_the_latest_cn_release_is_read_from_the_redirect():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chenditc/investment_data/releases/latest"
        return httpx.Response(
            302,
            headers={
                "location": "https://github.com/chenditc/investment_data/releases/tag/2026-10-30"
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    url = "https://github.com/chenditc/investment_data/releases/download/{tag}"
    assert latest_release_tag(url, client) == "2026-10-30"
    broken = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(RuntimeError, match="no latest-release redirect"):
        latest_release_tag(url, broken)


def test_replay_builds_one_more_day_per_local_day_and_keeps_old_snapshots(small_zones, tmp_path):
    data, source = world_data(small_zones)
    dirs = ZoneDirs.under(tmp_path / "snapshots")
    first = date(2012, 9, 3)
    service = IngestService(
        dirs, small_epoch(), SCHEDULE, replay_source(data, source, first), logger(tmp_path)
    )
    assert service.run_once(local("2026-11-02", "12:00")) == {"status": "not_due"}
    built = service.run_once(local("2026-11-02", "18:31"))
    assert built["status"] == "built" and built["through"] == "2012-09-03"
    assert service.run_once(local("2026-11-02", "22:00")) == {"status": "not_due"}
    second = service.run_once(local("2026-11-03", "18:45"))
    assert second["through"] == "2012-09-04" and second["snapshot_id"] != built["snapshot_id"]
    current = read_snapshot(current_snapshot(dirs.full))
    assert current.snapshot_id == second["snapshot_id"]
    assert current.manifest.date_range.end == date(2012, 9, 4)
    assert current.manifest.source_details["replay_through"] == "2012-09-04"
    kept = sorted(p.name for p in dirs.full.iterdir() if len(p.name) == 64)
    assert kept == sorted([built["snapshot_id"], second["snapshot_id"]])  # retained
    assert not dirs.research.exists() or not any(dirs.research.iterdir())  # never touched
    state = json.loads((dirs.full / ".ingest_state.json").read_text())
    assert state["last_build_day"] == "2026-11-03" and state["replay_builds"] == 2
    lines = (tmp_path / "data-ingest").glob("*.jsonl")
    events = [json.loads(x)["event"] for p in lines for x in p.read_text().splitlines()]
    assert events.count("ingest_daily_build") == 2


def test_no_new_release_and_failures_are_retried_later(tmp_path):
    calls = []

    def nothing_new(state):
        calls.append(state)
        return None

    dirs = ZoneDirs.under(tmp_path / "snapshots")
    service = IngestService(
        dirs, small_epoch(), SCHEDULE, nothing_new, logger(tmp_path), recheck_seconds=3600
    )
    assert service.run_once(local("2026-11-07", "18:31")) == {"status": "no_new_data"}
    assert service.run_once(local("2026-11-07", "19:00"))["status"] == "waiting"
    assert service.run_once(local("2026-11-07", "19:32")) == {"status": "no_new_data"}
    assert len(calls) == 2

    def broken(state):
        raise ConnectionError("github unreachable")

    service.build_fn = broken
    assert service.run_once(local("2026-11-08", "18:31"))["status"] == "failed"
    assert service.run_once(local("2026-11-08", "18:40"))["status"] == "waiting"


def test_raw_cleanup_keeps_the_newest_archives_and_the_current_extraction(tmp_path):
    raw = tmp_path / "raw"
    for i, tag in enumerate(("2026-10-28", "2026-10-29", "2026-10-30")):
        folder = raw / "investment_data" / tag
        folder.mkdir(parents=True)
        (folder / "qlib_bin.tar.gz").write_bytes(b"x")
        os.utime(folder, (1_000_000 + i, 1_000_000 + i))
    for sha in ("a" * 64, "b" * 64):
        (raw / "extracted" / sha).mkdir(parents=True)
    removed = prune_raw(raw, "b" * 64, 2)
    assert sorted(removed) == ["extracted/" + "a" * 64, "investment_data/2026-10-28"]
    assert sorted(p.name for p in (raw / "investment_data").iterdir()) == [
        "2026-10-29", "2026-10-30",
    ]  # fmt: skip


@pytest.mark.postgres
def test_the_evaluator_registers_new_full_snapshots_but_stays_on_the_epoch_snapshot(
    small_zones, tmp_path
):
    from tests.eval.eval_rig import eval_rig

    data, source = world_data(small_zones)
    root = tmp_path / "snapshots"
    dirs = ZoneDirs.under(root)
    built = build_zones(dirs, data, source, small_epoch(), ["full", "research"])
    zones = BuiltZones(root, small_zones.world, built.snapshots["full"],
                       built.snapshots["research"])  # fmt: skip
    with eval_rig(tmp_path, zones) as rig:
        rig.scheduler.tick()
        pinned = rig.db.scalar("SELECT snapshot_id FROM eval.epochs WHERE status = 'active'")
        assert pinned == built.snapshots["full"].snapshot_id
        service = IngestService(
            dirs, small_epoch(), SCHEDULE,
            replay_source(data, source, date(2012, 8, 1)), logger(tmp_path),
        )  # fmt: skip
        daily = service.run_once(local("2026-11-02", "18:31"))
        rig.scheduler.tick()
        registered = {
            r.snapshot_id for r in rig.db.rows("SELECT snapshot_id FROM eval.data_snapshots")
        }
        assert registered == {pinned, daily["snapshot_id"]}
        assert (
            rig.db.scalar("SELECT snapshot_id FROM eval.epochs WHERE status = 'active'") == pinned
        )
        summary = rig.db.rows(
            "SELECT snapshot_id FROM eval.data_snapshots ORDER BY created_at DESC LIMIT 1"
        )
        assert summary[0].snapshot_id in registered
