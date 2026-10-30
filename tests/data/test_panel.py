"""The dense canonical panel (PLAN 6.3) and ingest sanity checks (PLAN 6.2)."""

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest
from qfr_core.data.panel import (
    PANEL_SCHEMA,
    PanelError,
    build_panel,
    equal_weight_benchmark,
    sanity_checks,
)
from qfr_core.dsl import compile_expression
from qfr_core.eligibility import Eligibility
from qfr_core.operators import evaluate

from tests.dsl_strategies import LIMITS

CAL = [date(2020, 8, 17) + timedelta(days=i) for i in range(14) if (i % 7) < 5]


def obs(instrument, rows):
    """rows: (calendar index, close, volume, factor) with derived OHLC and amount."""
    return pl.DataFrame(
        {
            "date": [CAL[i] for i, *_ in rows],
            "instrument": instrument,
            "open": [c for _, c, _, _ in rows],
            "high": [c for _, c, _, _ in rows],
            "low": [c for _, c, _, _ in rows],
            "close": [c for _, c, _, _ in rows],
            "volume": [v for _, _, v, _ in rows],
            "amount": [c * v for _, c, v, _ in rows],
            "factor": [f for *_, f in rows],
        },
        schema_overrides={"volume": pl.Float64, "factor": pl.Float64, "close": pl.Float64},
    )


MEMBERS = pl.DataFrame(
    {
        "universe": ["csi300", "csi300", "csi500"],
        "instrument": ["SH600000", "SH600000", "SZ300001"],
        "start": [date(2020, 8, 15), date(2020, 8, 25), CAL[0]],
        "end": [date(2020, 8, 19), date(2030, 1, 1), CAL[-1]],
    }
)


def panel():
    main = obs(
        "SH600000",
        [
            (0, 10.0, 100, 1.0),
            (1, 11.0, 100, 1.0),  # +10%: limit-up.
            # Day 2 is missing: suspended.
            (3, 9.9, 0, 1.0),  # Zero volume: suspended.
            (4, 10.89, 100, 1.0),  # -1% on the last traded close, 11.0 (9.9 is ignored).
            (5, 10.8, 100, 2.0),  # 2-for-1 split: raw 5.4 against the ex-rights 5.445.
            (6, 9.72, 100, 2.0),  # Raw 4.86 = round(5.4 * 0.9): limit-down.
        ],
    )
    chinext = obs(
        "SZ300001",
        [(i, 10.0 * 1.1 ** min(i, 6), 50, 1.0) for i in range(len(CAL))],
    )
    return build_panel(pl.concat([main, chinext]), CAL, MEMBERS)


def rows(frame, instrument):
    return frame.filter(pl.col("instrument") == instrument).sort("date")


def test_schema_order_and_types():
    assert dict(panel().schema) == PANEL_SCHEMA


def test_dense_rows_suspensions_and_returns():
    p = rows(panel(), "SH600000")
    assert p.height == 7  # Calendar days 0..6, including the missing day 2.
    assert p["is_suspended"].to_list() == [False, False, True, True, False, False, False]
    assert p["close"].to_list()[2:4] == [None, None]
    assert p["volume"].to_list()[3] is None
    ret = p["ret_1d"].to_list()
    assert ret[0] is None
    assert ret[1] == pytest.approx(0.1)
    assert ret[4] == pytest.approx(10.89 / 11.0 - 1)  # Against the last traded close.
    assert ret[5] == pytest.approx(10.8 / 10.89 - 1)
    assert ret[6] == pytest.approx(-0.1)
    assert p["listed_days"].to_list() == list(range(7))
    assert p["factor"].to_list()[2] == 1.0  # Carried across the missing day.
    assert p["close_raw"].to_list()[5] == pytest.approx(5.4)


def test_limit_flags_use_board_rules_and_the_ex_rights_reference():
    p = rows(panel(), "SH600000")
    assert p["limit_up"].to_list() == [False, True, False, False, False, False, False]
    # On the split day the raw close halves (10.89 -> 5.4). Against the previous raw
    # close that would be a -50% limit-down; against the ex-rights reference
    # 10.89 / 2.0 = 5.445 it is a -0.8% move, so no flag is set.
    assert p["limit_down"].to_list() == [False, False, False, False, False, False, True]


def test_chinext_limit_switches_to_twenty_percent_on_2020_08_24():
    c = rows(panel(), "SZ300001")
    flags = dict(zip(c["date"].to_list(), c["limit_up"].to_list(), strict=True))
    # +10% every day up to calendar index 6: a limit move before 2020-08-24 only.
    assert flags[date(2020, 8, 18)] is True
    assert flags[date(2020, 8, 21)] is True
    assert flags[date(2020, 8, 24)] is False
    assert flags[date(2020, 8, 25)] is False


def test_point_in_time_membership_with_re_entry():
    p = rows(panel(), "SH600000")
    # In from 08-15 to 08-19, out, back from 08-25.
    assert p["in_csi300"].to_list() == [True, True, True, False, False, False, True]
    assert not any(p["in_csi500"].to_list())
    assert all(rows(panel(), "SZ300001")["in_csi500"].to_list())


def test_vwap_falls_back_to_the_typical_price():
    p = rows(panel(), "SH600000")
    assert p["vwap"].to_list()[0] == pytest.approx(10.0)


def test_adv20_is_the_dsl_mean_of_amount():
    rng = np.random.default_rng(0)
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(60)]
    frames = []
    for k in range(3):
        close = 10 * np.cumprod(1 + rng.normal(0, 0.01, 50))
        volume = np.where(rng.random(50) < 0.1, 0.0, rng.lognormal(10, 0.3, 50))
        frames.append(
            pl.DataFrame(
                {
                    "date": days[k * 3 : k * 3 + 50],
                    "instrument": f"SH60000{k}",
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": volume,
                    "amount": close * volume,
                    "factor": 1.0,
                }
            )
        )
    members = pl.DataFrame(
        {"universe": ["csi300"], "instrument": ["SH600000"], "start": [days[0]], "end": [days[-1]]}
    )
    p = build_panel(pl.concat(frames), days, members)
    eligibility = Eligibility(
        universe="csi300", listed_days_min=0, exclude_suspended=True, cross_section_min=2
    )
    expected = evaluate(p, compile_expression("Mean($amount,20)", LIMITS).tree, eligibility)
    assert p["adv20"].to_list() == pytest.approx(expected.to_list(), nan_ok=True)
    assert p["adv20"].null_count() > 0


def test_building_on_a_prefix_gives_the_prefix_of_the_panel():
    full = panel()
    cut = CAL[4]
    main = obs(
        "SH600000",
        [(0, 10.0, 100, 1.0), (1, 11.0, 100, 1.0), (3, 9.9, 0, 1.0), (4, 10.89, 100, 1.0)],
    )
    chinext = obs("SZ300001", [(i, 10.0 * 1.1**i, 50, 1.0) for i in range(5)])
    part = build_panel(pl.concat([main, chinext]), [d for d in CAL if d <= cut], MEMBERS)
    assert part.equals(full.filter(pl.col("date") <= cut))


def test_rejects_duplicates_and_dates_outside_the_calendar():
    bad = obs("SH600000", [(0, 10.0, 100, 1.0), (0, 10.0, 100, 1.0)])
    with pytest.raises(PanelError, match="duplicate"):
        build_panel(bad, CAL, MEMBERS)
    outside = obs("SH600000", [(0, 10.0, 100, 1.0)]).with_columns(
        pl.lit(date(2020, 8, 22)).alias("date")
    )
    with pytest.raises(PanelError, match="outside the trading calendar"):
        build_panel(outside, CAL, MEMBERS)
    with pytest.raises(PanelError, match="required columns"):
        build_panel(obs("SH600000", [(0, 10.0, 100, 1.0)]).drop("factor"), CAL, MEMBERS)


def test_sanity_checks_raise_on_errors_and_count_flags():
    good = panel()
    checks = sanity_checks(good)
    assert checks["suspended_rows"] == 2
    assert checks["limit_up_rows"] == 5 and checks["limit_down_rows"] == 1
    assert checks["corporate_action_flags"] == 0
    # A main-board jump above 25% after the first five days is flagged, not an error.
    jump = pl.when(pl.col("listed_days") == 6).then(0.3).otherwise(pl.col("ret_1d"))
    flagged = sanity_checks(good.with_columns(jump.alias("ret_1d")))
    assert flagged["corporate_action_flags"] == 1  # SZ300001 is ChiNext: not counted.
    assert flagged["corporate_action_sample"] == [["SH600000", "2020-08-25"]]
    negative = pl.when(pl.col("listed_days") == 1).then(-1.0).otherwise(pl.col("close"))
    with pytest.raises(PanelError, match="non-positive"):
        sanity_checks(good.with_columns(negative.alias("close")))
    with pytest.raises(PanelError, match="negative volumes"):
        sanity_checks(good.with_columns(pl.lit(-1.0).alias("volume")))
    with pytest.raises(PanelError, match="raw closes"):
        sanity_checks(good.with_columns((pl.col("close_raw") * 1e5).alias("close_raw")))


def test_equal_weight_benchmark_uses_traded_members():
    bench = equal_weight_benchmark(panel())
    values = dict(zip(bench["date"].to_list(), bench["benchmark_ret"].to_list(), strict=True))
    assert values[CAL[1]] == pytest.approx(0.1)
    assert values[CAL[2]] is None  # The only member is suspended.
