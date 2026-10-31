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


# The benchmark worlds (Phase 6) keep the shipped generator's 300 instruments and
# 240-name universe on the 800-day replay calendar: on the 60-name test universe a
# planted signal's daily RankIC is too noisy for the W2, holdout and acceptance gates.
BENCHMARK_SIZE = {"instruments": 300, "universe": 240}
TEST_SIZE = {"instruments": 80, "universe": 60}


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
    from qfr_core.data.panel import sanity_checks
    from qfr_core.data.snapshot import SnapshotData, SnapshotSource, ZoneDirs
    from qfr_eval.ingest.zones import build_zones

    epoch = EpochConfig.model_validate(replay_epoch(world_name)) if replay else small_epoch()
    config = small_config(REPLAY_DAYS if replay else 700, size)
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
