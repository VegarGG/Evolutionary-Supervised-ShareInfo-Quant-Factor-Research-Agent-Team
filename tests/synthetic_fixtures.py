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


# 800 weekdays from 2010-01-04 end on 2013-01-25: the small epoch's windows plus a tail of
# 80 trading days after W3 and its embargo, which replay incubation plays as if it were
# live (Phase 6). The decay world's tail starts at W2 instead: its A3 signal switches
# off at the W2 midpoint, and BM-DECAY monitors an approved A3-like factor across it.
REPLAY_DAYS = 800
REPLAY_EPOCH = SMALL_EPOCH | {"epoch_id": "small_replay", "replay": {"start": "2012-10-08"}}
DECAY_REPLAY_EPOCH = SMALL_EPOCH | {"epoch_id": "small_decay", "replay": {"start": "2012-02-01"}}


# BM-DECAY (Phase 6) keeps the shipped generator's 300 instruments and 240-name universe
# on the 800-day replay calendar: the decay rule's delay does not depend on the window
# lengths, and on the 60-name test universe the daily RankIC is too noisy.
BENCHMARK_SIZE = {"instruments": 300, "universe": 240}
TEST_SIZE = {"instruments": 80, "universe": 60}

# BM-PLANTED, BM-NULL and BM-STRATEGY run on the shipped synthetic world and epoch
# (configs/data/synthetic_v1.yaml and configs/epochs/synthetic_001.yaml: W1, W2 and W3 of
# about 2.0, 1.3 and 1.5 years) with 100 more weekdays: the 20-day embargo after W3 and
# a replay tail of 80 trading days. The shipped acceptance gates need windows of that
# length: on the 800-day world a planted A1 form's HLZ t over W1 to W3 is 1.3 to 2.5,
# against 4.8 to 6.3 here (docs/decisions.md, Phase 6).
VALIDATION_WORLD_DAYS = 2700
VALIDATION_REPLAY_START = "2020-01-20"


def validation_epoch() -> dict[str, object]:
    shipped = yaml.safe_load(Path("configs/epochs/synthetic_001.yaml").read_text())
    return shipped | {"epoch_id": "synthetic_replay", "replay": {"start": VALIDATION_REPLAY_START}}


def small_config(trading_days: int = 700, size: dict[str, int] = TEST_SIZE) -> SyntheticConfig:
    return load_synthetic(Path("configs")).with_size(
        instruments=size["instruments"], trading_days=trading_days, universe=size["universe"]
    )


def small_epoch() -> EpochConfig:
    return EpochConfig.model_validate(SMALL_EPOCH)


def small_world(world: str = "planted") -> SyntheticWorld:
    return generate(small_config(), world, small_epoch(), SETTINGS, MINIMUM)  # type: ignore[arg-type]


def replay_epoch(world: str) -> dict[str, object]:
    return DECAY_REPLAY_EPOCH if world == "decay" else REPLAY_EPOCH


@dataclass(frozen=True)
class BuiltZones:
    root: Path
    world: SyntheticWorld
    full: Snapshot
    research: Snapshot


def build_small_zones(
    root: Path, world_name: str, *, replay: bool = False, size: dict[str, int] = TEST_SIZE
) -> BuiltZones:
    """A small world (planted, null or decay) written as full and research snapshots;
    with replay, the 800-day world whose epoch reserves a replay tail."""
    epoch = EpochConfig.model_validate(replay_epoch(world_name)) if replay else small_epoch()
    config = small_config(REPLAY_DAYS if replay else 700, size)
    return _build_zones(root, world_name, config, epoch)


def build_validation_zones(root: Path, world_name: str) -> BuiltZones:
    """The shipped synthetic world (planted or null) on its epoch with a replay tail."""
    shipped = load_synthetic(Path("configs"))
    config = shipped.with_size(shipped.instruments, VALIDATION_WORLD_DAYS, shipped.universe.size)
    epoch = EpochConfig.model_validate(validation_epoch())
    return _build_zones(root, world_name, config, epoch)


def _build_zones(
    root: Path, world_name: str, config: SyntheticConfig, epoch: EpochConfig
) -> BuiltZones:
    from qfr_core.data.panel import sanity_checks
    from qfr_core.data.snapshot import SnapshotData, SnapshotSource, ZoneDirs
    from qfr_eval.ingest.zones import build_zones

    world = generate(config, world_name, epoch, SETTINGS, MINIMUM)  # type: ignore[arg-type]
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
        epoch,
        ["full", "research"],
        research_source=research,
    )
    return BuiltZones(root, world, built.snapshots["full"], built.snapshots["research"])
