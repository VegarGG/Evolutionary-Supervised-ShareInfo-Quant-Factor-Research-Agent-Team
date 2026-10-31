"""sim-engine: simulated trading for incubation and monitoring (PLAN Sections 10.2 to 10.4).

A simulation account trades one version: a factor through the reference strategy, a
strategy through its own TopK-dropout parameters, both with the protocol's costs. For
each new trading day d the engine
  1. scales held shares by the ratio of consecutive adjustment factors (splits and
     dividends);
  2. fills the orders decided at d-1 at the raw close of d: sells first (a suspended or
     limit-down name stays pending), then buys down the ranking (suspended or limit-up
     names are skipped) in 100-share lots sized at NAV / k from available cash;
  3. computes the version's values at d and decides the orders for d+1;
  4. marks to market at the raw close of d and writes NAV;
  5. records the RankIC of the decision day whose label has just completed.
Capital is 100,000,000 CNY notional. There is no backfill: a simulation starts on the
first trading day after the later of its publication and its admission.

Forward mode follows the newest registered full snapshot. Replay mode, for tests and
benchmarks only, plays the epoch's reserved historical tail as if it were live, a few
days per tick; it is refused unless the snapshot is synthetic, and the mode is recorded
on the simulation and its acceptance case. When no new data has arrived for 2 trading
days, the engine raises a staleness alert and pauses forward simulations until data
returns. A revised past value never rewrites history: the engine continues from its
recorded state and logs DATA_REVISION.

Incubation lasts 60 trading days with a checkpoint every 20, visible to the owner at
once. When it ends the engine releases the sim report and opens the acceptance case.
Monitoring simulations run for library entries and accepted versions; the v1 decay rule
raises an alert when the rolling 60-day s x RankIC_mean stays below 0 for 20 days.
"""

import math
import os
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import numpy as np
from numpy.typing import NDArray
from pydantic import JsonValue
from qfr_core.config import RuntimeSettings, canonical_json
from qfr_core.contracts import StrategyManifest
from qfr_core.correlation import bind, current
from qfr_core.data.snapshot import read_snapshot
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from qfr_core.metrics.factor import MetricSettings, evaluate_factor, rank_ic_series, sharpe
from qfr_core.metrics.matrix import Array, Market
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_eval.acceptance import compute_gates, open_case, refs
from qfr_eval.alerts import raise_alert
from qfr_eval.configs import ActiveState, active_state
from qfr_eval.ingest.config import load_yaml
from qfr_eval.plugins import plugin_for
from qfr_eval.reports import queue_report
from qfr_eval.runtime import (
    Clock,
    Database,
    EvalConfig,
    EvalEnvironment,
    SystemClock,
    eval_config,
    heartbeat,
    service_logger,
)
from qfr_eval.store import ArtifactStore
from qfr_eval.worker import MANIFEST, Evaluator, MarketCache, make_runner, read_components

SERVICE = "sim-engine"
LIVE = ("waiting", "running", "paused")


@dataclass(frozen=True)
class SimMarket:
    """The snapshot as matrices, with the raw prices and adjustment factors trading uses."""

    snapshot_id: str
    source: str
    market: Market
    close_raw: Array
    adjustment: Array
    present: NDArray[np.bool_]
    index: dict[date, int]


class SimMarkets:
    def __init__(self, full_dir: Path) -> None:
        self.full_dir = full_dir
        self._cache: dict[tuple[str, str], SimMarket] = {}

    def get(self, snapshot_id: str, plugin: Any) -> SimMarket:
        key = (snapshot_id, canonical_json(plugin.eligibility.model_dump(mode="json")))
        if key not in self._cache:
            snapshot = read_snapshot(self.full_dir / snapshot_id)
            panel = snapshot.panel()
            market = Market.from_panel(panel, plugin.eligibility, snapshot.calendar())
            present = np.zeros(market.shape, dtype=bool)
            present[market.rows, market.cols] = True
            self._cache = {
                key: SimMarket(
                    snapshot_id,
                    snapshot.manifest.source,
                    market,
                    market.matrix(panel.get_column("close_raw")),
                    market.matrix(panel.get_column("factor")),
                    present,
                    {d: i for i, d in enumerate(market.dates)},
                )
            }
        return self._cache[key]


def sim_settings(protocol: dict[str, Any], manifest: Any) -> dict[str, JsonValue]:
    """The settings a simulation pins at creation (immutable afterwards)."""
    sim, monitoring, costs = protocol["simulation"], protocol["monitoring"], protocol["costs"]
    if isinstance(manifest, StrategyManifest):
        portfolio = manifest.implementation.portfolio
        top_k, dropout, sign = portfolio.top_k, portfolio.dropout, 1
    else:
        reference = protocol["reference_strategy"]
        top_k, dropout = int(reference["top_k"]), int(reference["dropout"])
        sign = int(manifest.declared.expected_sign)
    return {
        "top_k": top_k,
        "dropout": dropout,
        "sign": sign,
        "buy_bps": float(costs["buy_bps"]),
        "sell_bps": float(costs["sell_bps"]),
        "lot_size": int(sim["lot_size"]),
        "checkpoint_days": int(sim["checkpoint_days"]),
        "staleness_days": int(sim["staleness_days"]),
        "horizon": int(protocol["label"]["primary"]),
        "rolling_days": int(monitoring["rolling_days"]),
        "rankic_mean_below": float(monitoring["rankic_mean_below"]),
        "consecutive_days": int(monitoring["consecutive_days"]),
    }


def stale_trading_days(last_date: date, now: datetime, tz: ZoneInfo, ingest_at: Any) -> int:
    """Weekdays after last_date up to the latest day whose data should have arrived: today
    once the local ingest time has passed, else the previous weekday. Exchange holidays
    are not known in advance, so a holiday can count as a missing day."""
    local = now.astimezone(tz)
    expected = local.date() if local.time() >= ingest_at else local.date() - timedelta(days=1)
    count = 0
    day = last_date + timedelta(days=1)
    while day <= expected:
        if day.weekday() < 5:
            count += 1
        day += timedelta(days=1)
    return count


@dataclass
class SimTick:
    advanced: dict[str, int] = field(default_factory=dict)
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    cases: list[str] = field(default_factory=list)
    note: str | None = None


class SimFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SimEngine:
    def __init__(
        self,
        db: Database,
        env: EvalEnvironment,
        config: EvalConfig,
        logger: JsonLogger,
        runner: Any = None,
        clock: Clock | None = None,
        deployment: dict[str, Any] | None = None,
    ) -> None:
        self.db, self.env, self.config = db, env, config
        self.logger, self.log = logger, logger.logger
        self.clock = clock or SystemClock()
        self.store = ArtifactStore(env.store_dir)
        # The engine reads the evaluation store (fingerprints and trial series) but never
        # writes it; the runner's scratch files go to a private temporary directory.
        if runner is None:
            scratch = Path(os.environ.get("QFR_SCRATCH_DIR") or tempfile.gettempdir()) / "qfr-sim"
            scratch.mkdir(parents=True, exist_ok=True)
            runner = make_runner(config, self.store, scratch)
        self.evaluator = Evaluator(env, runner, MarketCache(env.full_snapshot_dir))
        self.markets = SimMarkets(env.full_snapshot_dir)
        deployment = deployment or load_yaml(env.config_dir / "deployment.yaml")
        self.tz = ZoneInfo(str(deployment["timezone"]))
        schedule = deployment["schedule"]
        assert isinstance(schedule, dict)
        hour, minute = (int(x) for x in str(schedule["ingest_local"]).split(":"))
        self.ingest_at = datetime(2000, 1, 1, hour, minute).time()

    # The loop ------------------------------------------------------------------------

    def tick(self) -> SimTick:
        report = SimTick()
        with bind():
            with self.db.read() as conn:
                state = active_state(conn)
                latest = conn.execute(
                    text(
                        "SELECT snapshot_id, last_date, manifest ->> 'source' AS source "
                        "FROM eval.data_snapshots WHERE zone = 'full' "
                        "ORDER BY last_date DESC, created_at DESC LIMIT 1"
                    )
                ).first()
                sims = conn.execute(
                    text(
                        "SELECT * FROM eval.sim_accounts WHERE status IN ('waiting', 'running', "
                        "'paused') ORDER BY created_at, sim_id"
                    )
                ).all()
            if state is None or latest is None:
                report.note = "waiting for an active configuration and a full snapshot"
                return report
            stale = self._staleness(state, latest, sims, report)
            for sim in sims:
                if sim.mode == "forward" and stale:
                    continue
                with bind(version_id=str(sim.version_id)):
                    try:
                        self._advance(sim, state, latest, report)
                    except SimFailure as error:
                        self._fail(sim, state, error.code, str(error), report)
                    except Exception as error:  # noqa: BLE001 - recorded, then retried
                        self.log.exception(
                            "sim_tick_failed",
                            outcome="failed",
                            error_type=type(error).__name__,
                            payload={"sim_id": str(sim.sim_id)},
                        )
            if report.advanced or report.completed or report.failed or report.alerts:
                self.log.info(
                    "sim_tick",
                    outcome="ok",
                    payload={
                        "advanced": report.advanced,
                        "completed": report.completed,
                        "failed": report.failed,
                        "alerts": report.alerts,
                        "cases": report.cases,
                    },
                )
        return report

    def _staleness(
        self, state: ActiveState, latest: Any, sims: Sequence[Any], report: SimTick
    ) -> bool:
        """Raise the staleness alert and pause forward simulations, or resume them."""
        forward = [s for s in sims if s.mode == "forward"]
        if not forward:
            return False
        limit = int(state.protocol.config["simulation"]["staleness_days"])
        missing = stale_trading_days(latest.last_date, self.clock.now(), self.tz, self.ingest_at)
        now = self.clock.now()
        request_id = current()["request_id"]
        with self.db.transaction(lock=False) as conn:
            if missing >= limit:
                alert = raise_alert(
                    conn, "staleness", f"staleness:{latest.snapshot_id}",
                    {"last_date": latest.last_date.isoformat(), "missing_trading_days": missing,
                     "limit": limit},
                    now, SERVICE, request_id, logger=self.logger,
                )  # fmt: skip
                if alert is not None:
                    report.alerts.append(str(alert))
                for sim in forward:
                    if sim.status == "running":
                        self._set_status(conn, sim.sim_id, "paused", now)
                        self._event(conn, sim.sim_id, "PAUSED", None, {"missing": missing}, now)
                return True
            for sim in forward:
                if sim.status == "paused":
                    self._set_status(conn, sim.sim_id, "running", now)
                    self._event(conn, sim.sim_id, "RESUMED", None, {}, now)
        return False

    # One simulation --------------------------------------------------------------------

    def _snapshot_for(self, sim: Any, state: ActiveState, latest: Any) -> str:
        if sim.mode == "forward":
            return str(latest.snapshot_id)
        if state.epoch.replay_start is None:
            raise SimFailure("REPLAY_NOT_ALLOWED", "the epoch reserves no replay tail")
        return state.epoch.snapshot_id

    def _pending_days(self, sim: Any, data: SimMarket, state: ActiveState) -> list[int]:
        dates = data.market.dates
        if sim.last_day is not None:
            if sim.last_day not in data.index:
                raise SimFailure("CALENDAR_CHANGED", "the last simulated day left the calendar")
            first = data.index[sim.last_day] + 1
        else:
            start = sim.not_before
            if sim.mode == "replay":
                # The reserved historical tail stands in for the days after publication,
                # so a replay starts at the tail whatever the publication date.
                assert state.epoch.replay_start is not None
                start = state.epoch.replay_start
            first = next((i for i, d in enumerate(dates) if d >= start), len(dates))
        days = list(range(first, len(dates)))
        if sim.mode == "replay":
            days = days[: self.config.simulation.replay_days_per_tick]
        if sim.required_days is not None:
            days = days[: max(0, int(sim.required_days) - int(sim.days_done))]
        return days

    def _advance(self, sim: Any, state: ActiveState, latest: Any, report: SimTick) -> None:
        if sim.status == "paused":
            return
        snapshot_id = self._snapshot_for(sim, state, latest)
        with self.db.read() as conn:
            intake = conn.execute(
                text("SELECT * FROM eval.intake WHERE version_id = :v"), {"v": sim.version_id}
            ).first()
            if intake is None:
                raise SimFailure("VERSION_UNKNOWN", "the simulated version has no intake row")
            manifest = MANIFEST.validate_python(intake.manifest["manifest"])
            components = read_components(conn, manifest)
        protocol = state.protocol.config
        plugin = plugin_for(protocol, manifest)
        data = self.markets.get(snapshot_id, plugin)
        if sim.mode == "replay" and data.source != "synthetic":
            raise SimFailure("REPLAY_NOT_ALLOWED", "replay runs only on a synthetic snapshot")
        days = self._pending_days(sim, data, state)
        if not days:
            return
        settings = dict(sim.settings)
        horizon = int(settings["horizon"])
        start_index = data.index[sim.start_date] if sim.start_date is not None else days[0]
        label_rows = [d - 1 - horizon for d in days if d - 1 - horizon >= start_index]
        rows = sorted(set(days) | set(label_rows))
        output, _ = self.evaluator.compute(
            plugin, manifest, components, snapshot_id, data.market, rows, [],
            self.config.runner.load_cpu_seconds,
        )  # fmt: skip
        if output.result.status != "ok" or output.values is None:
            raise SimFailure(
                "COMPUTE_FAILED",
                f"computation failed: {output.result.status} {output.result.error_code or ''}",
            )
        scores = np.full(data.market.shape, np.nan)
        scores[rows] = int(settings["sign"]) * output.values
        metric_settings = MetricSettings.from_protocol(protocol)
        account = sim
        for day in days:
            account = self._day(account, data, scores, day, start_index, metric_settings, state)
            report.advanced[str(sim.sim_id)] = report.advanced.get(str(sim.sim_id), 0) + 1
            if account.status != "running":
                break
        if account.purpose == "monitoring":
            alert = self._decay_check(account, state)
            if alert is not None:
                report.alerts.append(alert)
        if (
            account.purpose == "incubation"
            and account.status == "running"
            and account.days_done >= int(account.required_days)
        ):
            novelty = self._novelty(account, state, account.kind)
            self._close(account, state, "completed", None, novelty, report)

    def _state(self, conn: Connection, sim: Any) -> tuple[dict[str, int], dict[str, float], float]:
        if sim.last_day is None:
            return {}, {}, float(sim.capital)
        rows = conn.execute(
            text(
                "SELECT instrument, shares, price, adjustment FROM eval.sim_positions "
                "WHERE sim_id = :s AND day = :d"
            ),
            {"s": sim.sim_id, "d": sim.last_day},
        ).all()
        shares = {r.instrument: int(r.shares) for r in rows}
        prices = {r.instrument: float(r.price) for r in rows}
        return shares, prices, float(sim.cash)

    def _day(
        self,
        sim: Any,
        data: SimMarket,
        scores: Array,
        d: int,
        start_index: int,
        metric_settings: MetricSettings,
        state: ActiveState,
    ) -> Any:
        """One trading day of one simulation, written in one transaction."""
        market = data.market
        s = dict(sim.settings)
        k, n, lot = int(s["top_k"]), int(s["dropout"]), int(s["lot_size"])
        buy_cost, sell_cost = float(s["buy_bps"]) / 1e4, float(s["sell_bps"]) / 1e4
        names = market.instruments
        column = {name: j for j, name in enumerate(names)}
        day = market.dates[d]
        now = self.clock.now()
        with self.db.transaction(lock=False) as conn:
            fresh = conn.execute(
                text("SELECT * FROM eval.sim_accounts WHERE sim_id = :s FOR UPDATE"),
                {"s": sim.sim_id},
            ).first()
            if fresh is None or fresh.status not in LIVE or fresh.days_done != sim.days_done:
                return fresh  # Another engine moved it; stop here.
            positions, recorded, cash = self._state(conn, fresh)
            previous = d - 1
            orders: Sequence[Any] = []
            if fresh.last_day is not None:
                orders = conn.execute(
                    text(
                        "SELECT seq, instrument, side, reason FROM eval.sim_orders "
                        "WHERE sim_id = :s AND decided_on = :d ORDER BY seq"
                    ),
                    {"s": fresh.sim_id, "d": fresh.last_day},
                ).all()
            if fresh.status == "waiting":
                conn.execute(
                    text(
                        "UPDATE eval.sim_accounts SET status = 'running', start_date = :d, "
                        "started_at = :at, cash = :c, updated_at = :at WHERE sim_id = :s"
                    ),
                    {"d": day, "at": now, "c": cash, "s": fresh.sim_id},
                )
                self._event(
                    conn, fresh.sim_id, "STARTED", day,
                    {"mode": fresh.mode, "snapshot_id": data.snapshot_id}, now,
                )  # fmt: skip
            # 1. Corporate actions, and data revisions of the last recorded day.
            revised = []
            for name in list(positions):
                j = column.get(name)
                if j is None:
                    continue
                old, new = data.adjustment[previous, j], data.adjustment[d, j]
                if fresh.last_day is not None and math.isfinite(data.close_raw[previous, j]):
                    if not math.isclose(data.close_raw[previous, j], recorded[name], rel_tol=1e-9):
                        revised.append(name)
                if math.isfinite(old) and math.isfinite(new) and old > 0 and new != old:
                    positions[name] = max(0, int(round(positions[name] * new / old)))
                    if positions[name] == 0:
                        del positions[name]
            if revised:
                self._event(
                    conn, fresh.sim_id, "DATA_REVISION", day,
                    {"instruments": cast(JsonValue, sorted(revised)[:50]),
                     "snapshot_id": data.snapshot_id}, now,
                )  # fmt: skip

            def price(name: str) -> float:
                j = column.get(name)
                value = data.close_raw[d, j] if j is not None else math.nan
                return float(value) if math.isfinite(value) else recorded.get(name, math.nan)

            previous_nav = float(fresh.capital)
            if fresh.last_day is not None:
                previous_nav = float(
                    conn.execute(
                        text("SELECT nav FROM eval.sim_nav WHERE sim_id = :s AND day = :d"),
                        {"s": fresh.sim_id, "d": fresh.last_day},
                    ).scalar_one()
                )
            # 2. Fills of the orders decided at d-1: sells, then buys down the ranking.
            fills: list[dict[str, Any]] = []
            pending: list[str] = []
            traded = costs = 0.0
            for order in orders:
                if order.side != "sell" or order.instrument not in positions:
                    continue
                name, j = order.instrument, column.get(order.instrument)
                blocked = None
                if j is None or not market.tradable[d, j]:
                    blocked = "suspended"
                elif market.limit_down[d, j]:
                    blocked = "limit_down"
                elif not math.isfinite(data.close_raw[d, j]):
                    blocked = "no_price"
                if blocked:
                    pending.append(name)
                    fills.append(self._fill(order, "blocked", blocked, 0, None, 0.0, 0.0))
                    continue
                shares = positions.pop(name)
                value = shares * float(data.close_raw[d, j])
                cash += value * (1.0 - sell_cost)
                traded += value
                costs += value * sell_cost
                fills.append(self._fill(order, "filled", None, shares, float(data.close_raw[d, j]),
                                        value, value * sell_cost))  # fmt: skip
            nav_now = cash + sum(shares * price(name) for name, shares in positions.items())
            size = nav_now / k
            for order in orders:
                if order.side != "buy":
                    continue
                if len(positions) >= k or cash <= 0:
                    break
                name, j = order.instrument, column.get(order.instrument)
                if name in positions:
                    continue
                if j is None or not market.tradable[d, j]:
                    fills.append(self._fill(order, "blocked", "suspended", 0, None, 0.0, 0.0))
                    continue
                if market.limit_up[d, j]:
                    fills.append(self._fill(order, "blocked", "limit_up", 0, None, 0.0, 0.0))
                    continue
                close = float(data.close_raw[d, j])
                if not math.isfinite(close) or close <= 0:
                    fills.append(self._fill(order, "blocked", "no_price", 0, None, 0.0, 0.0))
                    continue
                budget = min(size, cash / (1.0 + buy_cost))
                shares = int(budget // (close * lot)) * lot
                if shares <= 0:
                    fills.append(self._fill(order, "skipped", "lot", 0, close, 0.0, 0.0))
                    continue
                value = shares * close
                cash -= value * (1.0 + buy_cost)
                positions[name] = shares
                traded += value
                costs += value * buy_cost
                fills.append(self._fill(order, "filled", None, shares, close, value,
                                        value * buy_cost))  # fmt: skip
            # 3. Decide the orders for d+1 from the values at d.
            ranking = np.flatnonzero(market.eligible[d] & np.isfinite(scores[d])).tolist()
            ranking.sort(key=lambda j: (-scores[d, j], j))
            top = {names[j] for j in ranking[:k]}
            rank_of = {names[j]: r for r, j in enumerate(ranking)}
            outside = [name for name in positions if name not in top and name not in pending]
            outside.sort(key=lambda name: (-rank_of.get(name, len(ranking)), name))
            sells = pending + outside[:n]
            seq = 0
            for name in sells:
                conn.execute(
                    text(
                        "INSERT INTO eval.sim_orders (sim_id, decided_on, seq, instrument, side, "
                        "reason, score) VALUES (:s, :d, :q, :i, 'sell', :r, :sc)"
                    ),
                    {
                        "s": fresh.sim_id,
                        "d": day,
                        "q": seq,
                        "i": name,
                        "r": "pending" if name in pending else "dropout",
                        "sc": _finite(scores[d, column[name]]) if name in column else None,
                    },
                )
                seq += 1
            for j in ranking:
                if names[j] in positions:
                    continue
                conn.execute(
                    text(
                        "INSERT INTO eval.sim_orders (sim_id, decided_on, seq, instrument, side, "
                        "reason, score) VALUES (:s, :d, :q, :i, 'buy', 'entry', :sc)"
                    ),
                    {"s": fresh.sim_id, "d": day, "q": seq, "i": names[j],
                     "sc": _finite(scores[d, j])},
                )  # fmt: skip
                seq += 1
            # 4. Mark to market at the raw close of d.
            complete = bool(np.isfinite(scores[d]).any())
            for name in positions:
                j = column.get(name)
                if j is None or not data.present[d, j] or not math.isfinite(data.close_raw[d, j]):
                    complete = False
            nav = cash + sum(shares * price(name) for name, shares in positions.items())
            first_day = fresh.last_day is None
            number = int(fresh.days_done) + 1
            benchmark = float(market.benchmark_ret[d]) if not first_day else math.nan
            conn.execute(
                text(
                    "INSERT INTO eval.sim_nav (sim_id, day, day_number, nav, cash, gross_return, "
                    "net_return, turnover, costs, holdings, benchmark_return, complete, "
                    "snapshot_id) VALUES (:s, :d, :n, :nav, :cash, :g, :net, :t, :c, :h, :b, "
                    ":complete, :snap)"
                ),
                {
                    "s": fresh.sim_id,
                    "d": day,
                    "n": number,
                    "nav": nav,
                    "cash": cash,
                    "g": None if first_day else (nav + costs) / previous_nav - 1.0,
                    "net": None if first_day else nav / previous_nav - 1.0,
                    "t": None if first_day else traded / (2.0 * previous_nav),
                    "c": costs,
                    "h": len(positions),
                    "b": _finite(benchmark),
                    "complete": complete,
                    "snap": data.snapshot_id,
                },
            )
            for name, shares in sorted(positions.items()):
                j = column[name]
                conn.execute(
                    text(
                        "INSERT INTO eval.sim_positions (sim_id, day, instrument, shares, price, "
                        "value, adjustment) VALUES (:s, :d, :i, :n, :p, :v, :a)"
                    ),
                    {
                        "s": fresh.sim_id,
                        "d": day,
                        "i": name,
                        "n": shares,
                        "p": price(name),
                        "v": shares * price(name),
                        "a": _finite(data.adjustment[d, j]) or 1.0,
                    },
                )
            for seq_out, fill in enumerate(fills):
                conn.execute(
                    text(
                        "INSERT INTO eval.sim_fills (sim_id, day, seq, decided_on, instrument, "
                        "side, status, reason, shares, price, value, cost) VALUES (:s, :d, :q, "
                        ":dec, :i, :side, :st, :r, :n, :p, :v, :c)"
                    ),
                    {"s": fresh.sim_id, "d": day, "q": seq_out, "dec": fresh.last_day, **fill},
                )
            if not complete:
                self._event(conn, fresh.sim_id, "INCOMPLETE_DAY", day, {"day_number": number}, now)
            # 5. The RankIC of the decision day whose label completed today.
            t = d - 1 - int(s["horizon"])
            if t >= start_index:
                series = rank_ic_series(
                    scores, market, market.dates[t], market.dates[d], metric_settings
                )
                conn.execute(
                    text(
                        "INSERT INTO eval.sim_rankic (sim_id, decision_day, computed_on, value) "
                        "VALUES (:s, :t, :d, :v) ON CONFLICT DO NOTHING"
                    ),
                    {"s": fresh.sim_id, "t": market.dates[t], "d": day,
                     "v": _finite(series[0]) if series.size else None},
                )  # fmt: skip
            if number % int(s["checkpoint_days"]) == 0:
                self._event(
                    conn, fresh.sim_id, "CHECKPOINT", day,
                    self._checkpoint(conn, fresh.sim_id, number, nav, float(fresh.capital),
                                     int(s["sign"])),
                    now,
                )  # fmt: skip
            updated = conn.execute(
                text(
                    "UPDATE eval.sim_accounts SET last_day = :d, days_done = :n, cash = :c, "
                    "updated_at = :at WHERE sim_id = :s RETURNING *"
                ),
                {"d": day, "n": number, "c": cash, "at": now, "s": fresh.sim_id},
            ).first()
        return updated

    @staticmethod
    def _fill(
        order: Any,
        status: str,
        reason: str | None,
        shares: int,
        price: float | None,
        value: float,
        cost: float,
    ) -> dict[str, Any]:
        return {
            "i": order.instrument,
            "side": order.side,
            "st": status,
            "r": reason,
            "n": int(shares),
            "p": _finite(price),
            "v": float(value),
            "c": float(cost),
        }

    def _checkpoint(
        self, conn: Connection, sim_id: UUID, number: int, nav: float, capital: float, sign: int
    ) -> dict[str, JsonValue]:
        rankic = [
            r.value
            for r in conn.execute(
                text("SELECT value FROM eval.sim_rankic WHERE sim_id = :s AND value IS NOT NULL"),
                {"s": sim_id},
            ).all()
        ]
        returns = np.array(
            [
                np.nan if r.net_return is None else r.net_return
                for r in conn.execute(
                    text("SELECT net_return FROM eval.sim_nav WHERE sim_id = :s ORDER BY day"),
                    {"s": sim_id},
                ).all()
            ],
            dtype=np.float64,
        )
        return {
            "day_number": number,
            "nav": nav,
            "cumulative_return": nav / capital - 1.0,
            "rankic_mean": float(sign * np.mean(rankic)) if rankic else None,
            "sharpe": sharpe(returns),
        }

    def _event(
        self,
        conn: Connection,
        sim_id: UUID,
        kind: str,
        day: date | None,
        payload: dict[str, JsonValue],
        at: datetime,
    ) -> None:
        conn.execute(
            text(
                "INSERT INTO eval.sim_events (event_id, sim_id, at, day, kind, payload, "
                "request_id) VALUES (:id, :s, :at, :d, :k, CAST(:p AS jsonb), :r)"
            ),
            {
                "id": uuid7(),
                "s": sim_id,
                "at": at,
                "d": day,
                "k": kind,
                "p": canonical_json(payload),
                "r": current()["request_id"],
            },
        )
        self.log.info(
            "sim_event",
            outcome="ok",
            payload={"sim_id": str(sim_id), "kind": kind, "day": None if day is None
                     else day.isoformat()},
        )  # fmt: skip

    def _set_status(
        self, conn: Connection, sim_id: UUID, status: str, at: datetime, error: str | None = None
    ) -> None:
        finished = status in ("completed", "failed", "stopped")
        conn.execute(
            text(
                "UPDATE eval.sim_accounts SET status = :st, error_code = COALESCE(:e, error_code), "
                "updated_at = :at, finished_at = CASE WHEN :fin THEN :at ELSE finished_at END "
                "WHERE sim_id = :s"
            ),
            {"st": status, "e": error, "at": at, "fin": finished, "s": sim_id},
        )

    # Monitoring -------------------------------------------------------------------------

    def _decay_check(self, sim: Any, state: ActiveState) -> str | None:
        """v1 alarm: the rolling s x RankIC_mean stays below the threshold for the
        configured number of consecutive days (Section 10.4)."""
        s = dict(sim.settings)
        window, run = int(s["rolling_days"]), int(s["consecutive_days"])
        below, sign = float(s["rankic_mean_below"]), int(s["sign"])
        with self.db.read() as conn:
            rows = conn.execute(
                text(
                    "SELECT decision_day, value FROM eval.sim_rankic WHERE sim_id = :s "
                    "ORDER BY decision_day"
                ),
                {"s": sim.sim_id},
            ).all()
        values = np.array([np.nan if r.value is None else sign * r.value for r in rows])
        if values.size < window:
            return None
        streak = 0
        for end in range(window, values.size + 1):
            chunk = values[end - window : end]
            chunk = chunk[np.isfinite(chunk)]
            mean = float(chunk.mean()) if chunk.size else math.nan
            streak = streak + 1 if math.isfinite(mean) and mean < below else 0
            if streak >= run:
                at = self.clock.now()
                with self.db.transaction(lock=False) as conn:
                    alert = raise_alert(
                        conn, "decay", f"decay:{sim.sim_id}",
                        {"rule": "rolling_mean_below", "rolling_days": window,
                         "consecutive_days": run, "threshold": below, "rolling_mean": mean,
                         "decision_day": rows[end - 1].decision_day.isoformat(),
                         "forward_days": int(sim.days_done)},
                        at, SERVICE, current()["request_id"], version_id=sim.version_id,
                        sim_id=sim.sim_id, logger=self.logger,
                    )  # fmt: skip
                return None if alert is None else str(alert)
        return None

    # Completion -------------------------------------------------------------------------

    def _novelty(self, sim: Any, state: ActiveState, data_kind: str) -> dict[str, Any]:
        """Correlation on W3 with the library entries of the version's pool (G-NOVELTY).
        Each entry's W3 values are recomputed from its own expression; the candidate's
        come from its holdout run."""
        protocol = state.protocol.config
        with self.db.read() as conn:
            intake: dict[str, Any] = conn.execute(
                text("SELECT manifest FROM eval.intake WHERE version_id = :v"),
                {"v": sim.version_id},
            ).scalar_one()
            manifest = MANIFEST.validate_python(intake["manifest"])
            members = conn.execute(
                text(
                    "SELECT l.version_id, i.manifest FROM eval.library l JOIN eval.intake i "
                    "ON i.version_id = l.version_id WHERE l.pool = :p AND l.status IN "
                    "('seed', 'active') AND l.effective_from IS NOT NULL AND l.version_id <> :v "
                    "ORDER BY l.version_id"
                ),
                {"p": data_kind, "v": sim.version_id},
            ).all()
            member_components = []
            for member in members:
                member_manifest = MANIFEST.validate_python(member.manifest["manifest"])
                member_components.append(
                    (member.version_id, member_manifest, read_components(conn, member_manifest))
                )
            components = read_components(conn, manifest)
        if not members:
            return {"vacuous": True, "max_abs": None, "argmax": None, "members": []}
        w3 = state.epoch.windows["W3"]
        load = self.config.runner.load_cpu_seconds
        snapshot = state.epoch.snapshot_id
        market, first, last, values = self.evaluator.window_values(
            manifest, protocol, snapshot, w3, load, components
        )
        library = {}
        for version_id, member_manifest, member_parts in member_components:
            _, _, _, member_values = self.evaluator.window_values(
                member_manifest, protocol, snapshot, w3, load, member_parts
            )
            sign = (
                1
                if isinstance(member_manifest, StrategyManifest)
                else member_manifest.declared.expected_sign
            )
            library[str(version_id)] = sign * member_values
        scores = np.full(market.shape, np.nan)
        scores[first : last + 1] = values
        sign = 1 if isinstance(manifest, StrategyManifest) else manifest.declared.expected_sign
        evaluation = evaluate_factor(
            scores, market, w3.start, w3.end, sign, MetricSettings.from_protocol(protocol),
            library, library_window_aligned=True,
        )  # fmt: skip
        correlation = evaluation.metrics.library_correlation
        return {
            "vacuous": False,
            "max_abs": correlation.max_abs,
            "argmax": correlation.argmax,
            "members": sorted(library),
        }

    def _fail(self, sim: Any, state: ActiveState, code: str, message: str, report: SimTick) -> None:
        self.log.error(
            "sim_failed",
            outcome="failed",
            error_code=code,
            payload={"sim_id": str(sim.sim_id), "message": message[:500]},
        )
        if sim.purpose == "monitoring":
            now = self.clock.now()
            with self.db.transaction(lock=False) as conn:
                self._set_status(conn, sim.sim_id, "failed", now, code)
                self._event(conn, sim.sim_id, "FAILED", sim.last_day, {"error_code": code}, now)
                raise_alert(
                    conn, "ops", f"sim_failed:{sim.sim_id}", {"error_code": code},
                    now, SERVICE, current()["request_id"], version_id=sim.version_id,
                    sim_id=sim.sim_id, logger=self.logger,
                )  # fmt: skip
            report.failed.append(str(sim.sim_id))
            return
        self._close(sim, state, "failed", code, {"vacuous": True, "members": []}, report)

    def _close(
        self,
        sim: Any,
        state: ActiveState,
        status: str,
        error: str | None,
        novelty: dict[str, Any],
        report: SimTick,
    ) -> None:
        """End an incubation: the sim report, the case with its gates, AcceptanceReview."""
        now = self.clock.now()
        request_id = current()["request_id"]
        with self.db.transaction() as conn:
            self._set_status(conn, sim.sim_id, status, now, error)
            self._event(
                conn, sim.sim_id, "COMPLETED" if status == "completed" else "FAILED",
                sim.last_day, {"days_done": int(sim.days_done), "error_code": error}, now,
            )  # fmt: skip
            account = conn.execute(
                text("SELECT * FROM eval.sim_accounts WHERE sim_id = :s"), {"s": sim.sim_id}
            ).first()
            intake = conn.execute(
                text("SELECT * FROM eval.intake WHERE version_id = :v"), {"v": sim.version_id}
            ).first()
            gates, forward = compute_gates(conn, self.store, state, intake, account, novelty, now)
            raw = {
                "status": "COMPLETED" if status == "completed" else "FAILED",
                "rankic_mean": forward["rankic_mean"],
                "sharpe": forward["sharpe"],
            }
            queue_report(
                conn, "sim", sim.version_id,
                {"raw": raw, "refs": refs(state, self.env.code_version)}, now, request_id,
            )  # fmt: skip
            case_id, code = open_case(conn, state, intake, account, gates, now, SERVICE, request_id)
        report.cases.append(code)
        (report.completed if status == "completed" else report.failed).append(str(sim.sim_id))
        self.log.info(
            "case_opened",
            outcome="ok",
            payload={
                "case_id": str(case_id),
                "short_code": code,
                "failing_gates": [g["name"] for g in gates if not g["passed"]],
            },
        )


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def main() -> None:
    settings = RuntimeSettings(service=SERVICE, zone="eval")
    env = EvalEnvironment.from_env(os.environ, settings)
    config = eval_config(settings.config_dir)
    url = os.environ.get("EVAL_DB_URL", "")
    logger = service_logger(SERVICE, settings, [url])
    engine = SimEngine(Database(url), env, config, logger)
    beat = Path(os.environ.get("QFR_HEARTBEAT_FILE") or "/tmp/heartbeat")
    logger.logger.info("service_started", payload={"phase": 6, "mode": config.simulation.mode})
    while True:
        try:
            engine.tick()
        except Exception:
            logger.logger.exception("sim_loop_failed", outcome="failed")
        heartbeat(beat, engine.clock.now())
        time.sleep(config.simulation.interval_seconds)


if __name__ == "__main__":
    main()
