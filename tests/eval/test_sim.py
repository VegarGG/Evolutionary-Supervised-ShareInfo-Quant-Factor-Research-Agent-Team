"""sim-engine (P6.4, Section 10.2): orders decided at the close and filled the next day,
board lots, limit-up and limit-down blocks, costs, positions, NAV and checkpoints, on a
replay incubation; staleness pauses forward simulations.

The version reaches incubation under the test protocol of tests/eval/test_validation.py.
"""

import math
from datetime import UTC, date, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from qfr_eval.configs import active_state
from qfr_eval.plugins import plugin_for
from qfr_eval.sim import stale_trading_days
from qfr_eval.worker import MANIFEST

from tests.eval.eval_rig import eval_rig, replay_config
from tests.eval.test_validation import LOOSE, REPLAY_DAYS_PER_TICK, run_until
from tests.registry_rig import factor_manifest
from tests.synthetic_fixtures import REPLAY_EPOCH

pytestmark = pytest.mark.postgres

SHANGHAI = ZoneInfo("Asia/Shanghai")
INGEST = time(18, 30)
LIMIT_UP_DAY, LIMIT_DOWN_DAY = 1, 6  # replay days (0 is the first) the test blocks


def test_staleness_counts_weekdays_after_the_last_day():
    friday = date(2026, 1, 9)
    evening = datetime(2026, 1, 12, 11, 0, tzinfo=UTC)  # Monday 19:00 in Shanghai
    morning = datetime(2026, 1, 12, 1, 0, tzinfo=UTC)  # Monday 09:00
    assert stale_trading_days(friday, evening, SHANGHAI, INGEST) == 1
    assert stale_trading_days(friday, morning, SHANGHAI, INGEST) == 0  # weekend only
    assert stale_trading_days(date(2026, 1, 12), evening, SHANGHAI, INGEST) == 0
    assert stale_trading_days(friday, datetime(2026, 1, 14, 11, 0, tzinfo=UTC), SHANGHAI,
                              INGEST) == 3  # fmt: skip


@pytest.fixture
def replayed(tmp_path, replay_zones):
    """One factor incubated by replay, with every buy blocked on one replay day (limit up)
    and every sell blocked on another (limit down)."""
    with eval_rig(
        tmp_path, replay_zones, epoch=REPLAY_EPOCH, config=replay_config(REPLAY_DAYS_PER_TICK)
    ) as rig:
        rig.activate_protocol("test-loose", LOOSE)
        response = rig.registry.publish(factor_manifest("reversal", "-Pct($close,5)"))
        version = UUID(response.json()["version"]["version_id"])
        rig.cycle()
        with rig.db.read() as conn:
            state = active_state(conn)
        assert state is not None
        manifest = MANIFEST.validate_python(
            rig.db.scalar("SELECT manifest FROM eval.intake WHERE version_id = :v", v=version)[
                "manifest"
            ]
        )
        data = rig.sim.markets.get(state.epoch.snapshot_id, plugin_for(state.protocol.config,
                                                                       manifest))  # fmt: skip
        start = next(i for i, d in enumerate(data.market.dates) if d >= state.epoch.replay_start)
        data.market.limit_up[start + LIMIT_UP_DAY, :] = True
        data.market.limit_down[start + LIMIT_DOWN_DAY, :] = True
        run_until(rig, version, {"AcceptanceReview"}, days=16)
        sim = rig.db.rows(
            "SELECT * FROM eval.sim_accounts WHERE version_id = :v AND purpose = 'incubation'",
            v=version,
        )[0]
        yield rig, sim, data.market.dates[start:]


def test_sim_01_replay_starts_at_the_tail_and_runs_the_required_days(replayed):
    rig, sim, days = replayed
    navs = rig.db.rows(
        "SELECT * FROM eval.sim_nav WHERE sim_id = :s ORDER BY day_number", s=sim.sim_id
    )
    assert [n.day_number for n in navs] == list(range(1, 61))
    assert [n.day for n in navs] == days[:60]
    assert sim.start_date == days[0] and sim.last_day == days[59]
    checkpoints = rig.db.rows(
        "SELECT payload FROM eval.sim_events WHERE sim_id = :s AND kind = 'CHECKPOINT' "
        "ORDER BY at, day",
        s=sim.sim_id,
    )
    assert [c.payload["day_number"] for c in checkpoints] == [20, 40, 60]


def test_sim_02_fills_respect_lots_limits_and_costs(replayed):
    rig, sim, days = replayed
    settings = sim.settings
    lot, buy, sell = settings["lot_size"], settings["buy_bps"] / 1e4, settings["sell_bps"] / 1e4
    fills = rig.db.rows("SELECT * FROM eval.sim_fills WHERE sim_id = :s", s=sim.sim_id)
    filled = [f for f in fills if f.status == "filled"]
    # Buys are whole board lots; a sell may close an odd lot left by a corporate action.
    assert filled and all(f.shares > 0 for f in filled)
    assert all(f.shares % lot == 0 for f in filled if f.side == "buy")
    for f in filled:
        assert math.isclose(f.value, f.shares * f.price, rel_tol=1e-12)
        rate = buy if f.side == "buy" else sell
        assert math.isclose(f.cost, f.value * rate, rel_tol=1e-9)
        assert f.decided_on < f.day  # decided at a close, filled at the next
    up = [f for f in fills if f.day == days[LIMIT_UP_DAY]]
    assert up and all(
        (f.status, f.reason) == ("blocked", "limit_up") for f in up if f.side == "buy"
    )
    down = [f for f in fills if f.day == days[LIMIT_DOWN_DAY] and f.side == "sell"]
    assert down and all((f.status, f.reason) == ("blocked", "limit_down") for f in down)
    # A blocked sell is ordered again the next day.
    again = rig.db.rows(
        "SELECT instrument FROM eval.sim_orders WHERE sim_id = :s AND decided_on = :d "
        "AND reason = 'pending'",
        s=sim.sim_id,
        d=days[LIMIT_DOWN_DAY],
    )
    assert {r.instrument for r in again} == {f.instrument for f in down}


def test_sim_03_nav_is_cash_plus_positions_every_day(replayed):
    rig, sim, _ = replayed
    navs = rig.db.rows(
        "SELECT * FROM eval.sim_nav WHERE sim_id = :s ORDER BY day_number", s=sim.sim_id
    )
    held = {
        r.day: (float(r.value), int(r.n))
        for r in rig.db.rows(
            "SELECT day, sum(value) AS value, count(*) AS n FROM eval.sim_positions "
            "WHERE sim_id = :s GROUP BY day",
            s=sim.sim_id,
        )
    }
    top_k = sim.settings["top_k"]
    previous = None
    for nav in navs:
        value, count = held.get(nav.day, (0.0, 0))
        assert math.isclose(nav.nav, nav.cash + value, rel_tol=1e-9)
        assert nav.holdings == count <= top_k and nav.cash >= 0
        if previous is not None:
            assert math.isclose(nav.net_return, nav.nav / previous.nav - 1, abs_tol=1e-12)
            assert math.isclose(
                nav.gross_return, (nav.nav + nav.costs) / previous.nav - 1, abs_tol=1e-12
            )
        previous = nav
    assert navs[0].nav <= float(sim.capital)


def test_sim_04_stale_data_pauses_a_forward_simulation_once(tmp_path, replay_zones):
    with eval_rig(tmp_path, replay_zones, epoch=REPLAY_EPOCH) as rig:  # forward mode
        rig.activate_protocol("test-loose", LOOSE)
        response = rig.registry.publish(factor_manifest("reversal", "-Pct($close,5)"))
        version = UUID(response.json()["version"]["version_id"])
        run_until(rig, version, {"Incubating"}, days=16)
        sim = rig.db.rows("SELECT * FROM eval.sim_accounts WHERE version_id = :v", v=version)[0]
        assert sim.mode == "forward"
        rig.sim.tick()  # the snapshot ends in 2013; the clock is in 2026
        status = rig.db.scalar(
            "SELECT status FROM eval.sim_accounts WHERE sim_id = :s", s=sim.sim_id
        )
        alerts = rig.db.rows("SELECT kind, details FROM eval.alerts")
        rig.sim.tick()
        assert status in ("waiting", "paused")
        assert [a.kind for a in alerts] == ["staleness"]
        assert alerts[0].details["missing_trading_days"] >= 2
        assert rig.db.scalar("SELECT count(*) FROM eval.alerts") == 1  # raised once
        assert rig.db.scalar("SELECT count(*) FROM eval.sim_nav") == 0  # nothing simulated
