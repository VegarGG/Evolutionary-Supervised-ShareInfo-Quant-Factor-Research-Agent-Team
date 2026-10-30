"""The zone builder (PLAN Section 6.4 and P1.4).

The full snapshot holds every row and is mounted only into evaluation containers. The
research snapshot is the full data truncated to rows dated on or before the research
cutoff, the end of W0. Every panel column depends only on the past, so the truncated
rows equal the full rows; membership intervals are clipped at the cutoff so they reveal
nothing about later index changes. Research snapshots never carry extra files such as
the synthetic ground truth.
"""

from dataclasses import dataclass, replace

import polars as pl
from qfr_core.config import EpochConfig
from qfr_core.data.panel import DATE, sanity_checks
from qfr_core.data.snapshot import (
    DateRange,
    Snapshot,
    SnapshotData,
    SnapshotSource,
    Zone,
    ZoneDirs,
    check_research_snapshot,
    set_current,
    write_snapshot,
)
from qfr_core.logging import JsonLogger


def research_window(epoch: EpochConfig) -> DateRange:
    if epoch.W0.end is None:
        raise ValueError("W0 must have a resolved end date")
    return DateRange(start=epoch.W0.start, end=epoch.W0.end)


def truncate(data: SnapshotData, cutoff: DateRange) -> SnapshotData:
    end = cutoff.end
    membership = (
        data.membership.filter(pl.col("start") <= end)
        .with_columns(pl.min_horizontal(pl.col("end"), pl.lit(end)).alias("end"))
        .select(data.membership.columns)
    )
    return SnapshotData(
        panel=data.panel.filter(pl.col(DATE) <= end),
        membership=membership,
        calendar=data.calendar.filter(pl.col(DATE) <= end),
    )


@dataclass(frozen=True)
class BuildResult:
    snapshots: dict[Zone, Snapshot]


def build_zones(
    dirs: ZoneDirs,
    data: SnapshotData,
    source: SnapshotSource,
    epoch: EpochConfig,
    zones: list[Zone],
    research_source: SnapshotSource | None = None,
    logger: JsonLogger | None = None,
) -> BuildResult:
    """Write the requested zones, full first, and point each zone's current.json at it."""
    if not zones or any(z not in ("full", "research") for z in zones):
        raise ValueError("zones must be a nonempty subset of full, research")
    log = logger.logger if logger is not None else None
    built: dict[Zone, Snapshot] = {}
    full = write_snapshot(dirs.full, "full", data, source)
    if "full" in zones:
        set_current(dirs.full, full)
        built["full"] = full
        if log is not None:
            log.info(
                "snapshot_written",
                outcome="ok",
                payload={
                    "zone": "full",
                    "snapshot_id": full.snapshot_id,
                    "rows": full.manifest.row_counts,
                },
            )
    if "research" in zones:
        window = research_window(epoch)
        part = truncate(data, window)
        base = research_source or replace(source, source_details={})
        checks = sanity_checks(part.panel)
        research = write_snapshot(
            dirs.research,
            "research",
            part,
            replace(base, checks=checks),
            research_window=window,
            parent_snapshot_id=full.snapshot_id,
        )
        check_research_snapshot(research)
        set_current(dirs.research, research)
        built["research"] = research
        if log is not None:
            log.info(
                "research_truncated",
                outcome="ok",
                payload={
                    "zone": "research",
                    "snapshot_id": research.snapshot_id,
                    "parent_snapshot_id": full.snapshot_id,
                    "cutoff": window.end.isoformat(),
                    "rows": research.manifest.row_counts,
                },
            )
    return BuildResult(built)
