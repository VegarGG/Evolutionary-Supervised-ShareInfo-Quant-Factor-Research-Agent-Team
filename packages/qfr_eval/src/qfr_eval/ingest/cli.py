"""`qfr data`: build and verify market data snapshots (evaluation side, PLAN P1.4)."""

import hashlib
import json
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, cast

import httpx
import typer
from pydantic import JsonValue
from qfr_core.config import RuntimeSettings, canonical_json, logging_config
from qfr_core.data.panel import sanity_checks
from qfr_core.data.snapshot import (
    SnapshotData,
    SnapshotSource,
    Zone,
    ZoneDirs,
    check_research_snapshot,
    read_snapshot,
)
from qfr_core.logging import JsonLogger
from qfr_core.metrics.factor import MetricSettings

from qfr_eval.ingest.cn import ingest_cn
from qfr_eval.ingest.config import World, load_cn, load_epoch, load_synthetic, load_yaml
from qfr_eval.ingest.serve import BuildFn, IngestService, Schedule, cn_source, replay_source
from qfr_eval.ingest.synthetic import generate
from qfr_eval.ingest.zones import build_zones
from qfr_eval.runtime import eval_config, start_heartbeat

app = typer.Typer(no_args_is_help=True, help="Market data snapshots (evaluation side).")

PROTOCOL_FILE = "protocols/cn_csi300_daily_v1.yaml"
SYNTHETIC_CONVENTIONS: dict[str, JsonValue] = {
    "prices": "adjusted; close_raw = close / factor; factor is 1 at each listing",
    "volume": "raw shares divided by factor",
    "vwap": "mean of open, high, low and close",
    "suspended": "zero-volume rows with the last close; market fields null in the panel",
    "ret_1d": "adjusted close over the last traded adjusted close, minus 1",
    "limits": "10% of the ex-rights reference, half-up 0.01 tick",
    "benchmark": "equal_weight_csi300",
}


LOCAL_SNAPSHOTS = Path("data/snapshots")
LOCAL_RAW = Path("data/raw")


def _dirs(out: Path | None) -> ZoneDirs:
    """--out wins; then the Compose mount points; then data/snapshots for local runs."""
    if out is not None:
        return ZoneDirs.under(out)
    local = ZoneDirs.under(LOCAL_SNAPSHOTS)
    return ZoneDirs(
        Path(os.environ.get("QFR_FULL_SNAPSHOT_DIR") or local.full),
        Path(os.environ.get("QFR_RESEARCH_SNAPSHOT_DIR") or local.research),
    )


def _logger(settings: RuntimeSettings) -> JsonLogger:
    return JsonLogger(
        settings.service,
        "eval",
        settings.log_dir,
        logging_config(settings.config_dir),
        stdout=sys.stderr,
    )


def _zones(text: str) -> list[Zone]:
    zones = [z.strip() for z in text.split(",") if z.strip()]
    if not zones or any(z not in ("full", "research") for z in zones):
        raise typer.BadParameter("zones are a comma-separated subset of full,research")
    return cast(list[Zone], zones)


def _synthetic(
    config_dir: Path, world: World, protocol: dict[str, object], logger: JsonLogger
) -> tuple[SnapshotData, SnapshotSource, SnapshotSource, str]:
    config = load_synthetic(config_dir)
    epoch = load_epoch(config_dir, config.epoch)
    settings = MetricSettings.from_protocol(protocol)  # type: ignore[arg-type]
    eligibility = protocol["eligibility"]
    assert isinstance(eligibility, dict)
    minimum = int(eligibility["cross_section_min"])
    logger.logger.info("synthetic_generation_started", payload={"world": world})
    result = generate(config, world, epoch, settings, minimum)
    truth = json.dumps(result.ground_truth, sort_keys=True, indent=2).encode() + b"\n"
    data = SnapshotData(
        result.panel, result.membership, result.calendar, {"ground_truth.json": truth}
    )
    config_hash = hashlib.sha256(canonical_json(config.model_dump(mode="json")).encode())
    checks = sanity_checks(result.panel)
    full = SnapshotSource(
        source="synthetic",
        release_tag=None,
        archive_sha256=None,
        source_details={
            "generator": config.generator,
            "world": world,
            "seed": config.seed,
            "config_sha256": config_hash.hexdigest(),
            "ground_truth": "ground_truth.json",
        },
        conventions=SYNTHETIC_CONVENTIONS,
        checks=checks,
    )
    # Research learns neither the world nor the planted signals.
    research = SnapshotSource(
        "synthetic", None, None, {"generator": config.generator}, SYNTHETIC_CONVENTIONS, {}
    )
    return data, full, research, config.epoch


@app.command("build")
def build(
    source: Annotated[str, typer.Option(help="synthetic or cn")],
    zones: Annotated[str, typer.Option(help="Comma-separated: full,research")] = "full,research",
    world: Annotated[str, typer.Option(help="Synthetic world: planted, null or decay")] = "planted",
    epoch: Annotated[str | None, typer.Option(help="Epoch id; defaults per source")] = None,
    archive: Annotated[Path | None, typer.Option(help="Local qlib_bin.tar.gz (cn)")] = None,
    manifest: Annotated[Path | None, typer.Option(help="Release manifest JSON (cn)")] = None,
    sha256: Annotated[str | None, typer.Option(help="Owner-verified archive SHA-256")] = None,
    release_tag: Annotated[str | None, typer.Option(help="investment_data release tag")] = None,
    out: Annotated[
        Path | None, typer.Option(help="Write <out>/full and <out>/research instead")
    ] = None,
    raw_dir: Annotated[Path | None, typer.Option(help="Raw download dir (QFR_RAW_DIR)")] = None,
) -> None:
    """Build the full snapshot and, by default, the date-truncated research snapshot."""
    settings = RuntimeSettings()
    logger = _logger(settings)
    log = logger.logger
    requested = _zones(zones)
    if source not in ("synthetic", "cn"):
        raise typer.BadParameter("source must be synthetic or cn")
    if world not in ("planted", "null", "decay"):
        raise typer.BadParameter("world must be planted, null or decay")
    dirs = _dirs(out)
    log.info("data_build_started", payload={"source": source, "zones": requested})
    try:
        protocol = load_yaml(settings.config_dir / PROTOCOL_FILE)
        if source == "synthetic":
            data, full, research, epoch_id = _synthetic(
                settings.config_dir, cast(World, world), protocol, logger
            )
        else:
            raw = raw_dir or Path(os.environ.get("QFR_RAW_DIR") or LOCAL_RAW)
            data, full = ingest_cn(
                load_cn(settings.config_dir),
                raw,
                archive=archive,
                manifest=manifest,
                sha256=sha256,
                release_tag=release_tag,
                logger=logger,
            )
            research, epoch_id = full, str(protocol["epoch_ref"])
        log.info("data_checks_passed", outcome="ok", payload={"checks": full.checks})
        result = build_zones(
            dirs,
            data,
            full,
            load_epoch(settings.config_dir, epoch or epoch_id),
            requested,
            research_source=research,
            logger=logger,
        )
    except Exception as error:
        log.error(
            "data_build_failed",
            outcome="failed",
            error_type=type(error).__name__,
            payload={"message": str(error)},
        )
        typer.echo(
            json.dumps({"status": "error", "error": type(error).__name__, "message": str(error)})
        )
        raise typer.Exit(1) from None
    typer.echo(
        json.dumps(
            {
                "status": "ok",
                "source": source,
                "snapshots": {
                    zone: {"snapshot_id": s.snapshot_id, "path": str(s.path)}
                    for zone, s in result.snapshots.items()
                },
            },
            sort_keys=True,
        )
    )


@app.command("verify")
def verify(
    path: Path,
    zone: Annotated[
        str | None, typer.Option(help="Require this zone (research runs BND-06)")
    ] = None,
) -> None:
    """Verify every file hash and the snapshot id; for research, the BND-06 cutoff."""
    try:
        snapshot = read_snapshot(path)
        if zone is not None and snapshot.manifest.zone != zone:
            raise ValueError(f"snapshot zone is {snapshot.manifest.zone}, not {zone}")
        report: dict[str, object] = {
            "status": "ok",
            "snapshot_id": snapshot.snapshot_id,
            "zone": snapshot.manifest.zone,
            "files": len(snapshot.manifest.files),
        }
        if snapshot.manifest.zone == "research":
            report["research_cutoff"] = check_research_snapshot(snapshot).isoformat()
            report["bnd_06"] = "pass"
    except Exception as error:
        typer.echo(
            json.dumps({"status": "error", "error": type(error).__name__, "message": str(error)})
        )
        raise typer.Exit(1) from None
    typer.echo(json.dumps(report, sort_keys=True))


@app.command("serve")
def serve(
    source: Annotated[
        str, typer.Option(help="cn; replay (synthetic, tests only); off (no builds)")
    ] = "cn",
    world: Annotated[str, typer.Option(help="Replay: synthetic world")] = "planted",
    replay_from: Annotated[
        str | None, typer.Option(help="Replay: first revealed date (default W1 start)")
    ] = None,
    once: Annotated[bool, typer.Option(help="Run one check, print the result and exit")] = False,
    force: Annotated[bool, typer.Option(help="With --once: build now, ignoring the clock")] = False,
    out: Annotated[
        Path | None, typer.Option(help="Use <out>/full and <out>/research instead")
    ] = None,
    raw_dir: Annotated[Path | None, typer.Option(help="Raw download dir (QFR_RAW_DIR)")] = None,
) -> None:
    """The daily job: build a new full snapshot after the ingest time (PLAN P3.8)."""
    settings = RuntimeSettings()
    logger = _logger(settings)
    if source not in ("cn", "replay", "off"):
        raise typer.BadParameter("source must be cn, replay or off")
    beat = os.environ.get("QFR_HEARTBEAT_FILE")
    if source == "off":
        # A synthetic dry run: keep the service healthy without downloading CN data.
        logger.logger.info("ingest_disabled", payload={"source": "off"})
        if once:
            typer.echo(json.dumps({"status": "disabled"}))
            return
        start_heartbeat(Path(beat) if beat else None)
        while True:
            time.sleep(3600)
    if world not in ("planted", "null", "decay"):
        raise typer.BadParameter("world must be planted, null or decay")
    config = eval_config(settings.config_dir).ingest
    deployment = load_yaml(settings.config_dir / "deployment.yaml")
    protocol = load_yaml(settings.config_dir / PROTOCOL_FILE)
    build_fn: BuildFn
    if source == "cn":
        epoch_id = str(protocol["epoch_ref"])
        raw = raw_dir or Path(os.environ.get("QFR_RAW_DIR") or LOCAL_RAW)
        cn = load_cn(settings.config_dir)
        client = httpx.Client(timeout=cn.download_timeout_seconds)
        build_fn = cn_source(cn, raw, client, logger, config.keep_raw_releases)
    else:
        data, full, _, epoch_id = _synthetic(
            settings.config_dir, cast(World, world), protocol, logger
        )
        first = load_epoch(settings.config_dir, epoch_id).W1.start
        build_fn = replay_source(
            data, full, date.fromisoformat(replay_from) if replay_from else first
        )
    service = IngestService(
        _dirs(out),
        load_epoch(settings.config_dir, epoch_id),
        Schedule.from_deployment(deployment),
        build_fn,
        logger,
        config.recheck_seconds,
    )
    logger.logger.info("service_started", payload={"phase": 3, "source": source})
    if once:
        result = service.run_once(datetime.now(UTC), force=force)
        typer.echo(json.dumps(result, sort_keys=True))
        raise typer.Exit(1 if result["status"] == "failed" else 0)
    start_heartbeat(Path(beat) if beat else None)
    service.serve(config.check_seconds)
