"""A small synthetic world and its snapshots, shared by data, ingest and workbench tests."""

from dataclasses import dataclass
from pathlib import Path

import yaml
from qfr_core.config import EpochConfig
from qfr_core.data.snapshot import Snapshot
from qfr_core.eligibility import Eligibility
from qfr_core.metrics.factor import MetricSettings
from qfr_eval.ingest.config import SyntheticConfig, load_synthetic
from qfr_eval.ingest.synthetic import SyntheticWorld, generate

PROTOCOL = yaml.safe_load(Path("configs/protocols/cn_csi300_daily_v1.yaml").read_text())
SETTINGS = MetricSettings.from_protocol(PROTOCOL)
ELIGIBILITY = Eligibility.from_protocol(PROTOCOL["universe"], PROTOCOL["eligibility"])
MINIMUM = ELIGIBILITY.cross_section_min

# 700 weekdays from 2010-01-04 end on 2012-09-07.
SMALL_EPOCH = {
    "epoch_id": "small_test",
    "version": "1",
    "W0": {"start": "2010-01-04", "end": "2011-06-30"},
    "W1": {"start": "2011-08-01", "end": "2011-12-30"},
    "W2": {"start": "2012-02-01", "end": "2012-05-31"},
    "W3": {"start": "2012-07-02", "end": "2012-09-07"},
    "embargo_trading_days": 20,
}


def small_config() -> SyntheticConfig:
    return load_synthetic(Path("configs")).with_size(instruments=80, trading_days=700, universe=60)


def small_epoch() -> EpochConfig:
    return EpochConfig.model_validate(SMALL_EPOCH)


def small_world(world: str = "planted") -> SyntheticWorld:
    return generate(small_config(), world, small_epoch(), SETTINGS, MINIMUM)  # type: ignore[arg-type]


@dataclass(frozen=True)
class BuiltZones:
    root: Path
    world: SyntheticWorld
    full: Snapshot
    research: Snapshot


def build_small_zones(root: Path, world_name: str) -> BuiltZones:
    """A small world (planted, null or decay) written as full and research snapshots."""
    from qfr_core.data.panel import sanity_checks
    from qfr_core.data.snapshot import SnapshotData, SnapshotSource, ZoneDirs
    from qfr_eval.ingest.zones import build_zones

    world = small_world(world_name)
    data = SnapshotData(
        world.panel, world.membership, world.calendar, {"ground_truth.json": b"{}\n"}
    )
    source = SnapshotSource(
        "synthetic", None, None, {"world": world_name}, {}, sanity_checks(world.panel)
    )
    research = SnapshotSource("synthetic", None, None, {}, {}, {})
    built = build_zones(
        ZoneDirs.under(root),
        data,
        source,
        small_epoch(),
        ["full", "research"],
        research_source=research,
    )
    return BuiltZones(root, world, built.snapshots["full"], built.snapshots["research"])
