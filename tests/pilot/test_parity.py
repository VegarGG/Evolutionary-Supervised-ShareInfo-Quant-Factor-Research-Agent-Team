import json
import os
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from qfr_core.data_layer.pilot import PilotConfig, import_pilot
from qfr_core.dsl.language import DSLConfig
from qfr_core.dsl.operators import evaluate
from qfr_core.pilot.baseline import P0Config, p0_history
from qfr_core.pilot.features import PilotFeatureConfig, enrich_p0, price_features
from qfr_core.pilot.parity import assert_parity


@pytest.fixture(scope="module")
def sources():
    root = os.environ.get("QFR_PILOT_ROOT")
    oracle = os.environ.get("QFR_PILOT_ORACLE_ROOT")
    if not root or not oracle:
        pytest.skip(
            "Real licensed packages and isolated frozen replay required: "
            "QFR_PILOT_ROOT, QFR_PILOT_ORACLE_ROOT"
        )
    config = PilotConfig.model_validate_json(Path("configs/data/pilot_import.json").read_bytes())
    source = import_pilot(
        Path(root) / "P1_English_Delivery_20261022", Path("fixtures/pilot"), config
    )
    tables = {table.name: table.frame for table in source.tables}
    expected = pl.read_csv(
        Path(oracle) / "P1/replay/captured_panel.csv.gz",
        try_parse_dates=True,
        infer_schema_length=None,
    )
    receipt = json.loads((Path(oracle) / "P1/replay/run_receipt.json").read_text())
    assert receipt["status"] == "passed" and len(receipt["business_csvs_byte_identical"]) == 24
    assert receipt["new_model_fits"] == receipt["new_provider_requests"] == 0
    features = PilotFeatureConfig.model_validate_json(
        Path("configs/pilot/stage1_features.json").read_bytes()
    )
    return tables, expected, features, config, Path(root)


@pytest.fixture(scope="module")
def enriched(sources):
    tables, _, features, _, _ = sources
    return enrich_p0(tables["features"], tables["prices_daily"], features)


@pytest.fixture(scope="module")
def history(enriched):
    return p0_history(
        enriched, P0Config.model_validate_json(Path("configs/pilot/p0_scoring.json").read_bytes())
    )


@pytest.mark.pilot
def test_pil_01_all_weekly_v4_features_match_frozen_oracle(sources):
    tables, expected, features, tolerance, _ = sources
    actual = price_features(
        tables["features"], tables["prices_daily"], tables["universe"]["code"].to_list(), features
    )
    columns = [
        prefix + name for name in features.expressions() for prefix in ("v4_raw_", "v4_p_")
    ] + ["v4_price_date", "v4_ready"]
    assert (
        assert_parity(
            actual,
            expected,
            keys=["date", "code"],
            columns=columns,
            atol=tolerance.feature_parity_atol,
            rtol=tolerance.feature_parity_rtol,
        )
        == actual.height * 14
    )


@pytest.mark.pilot
def test_pil_01_legacy_enrichment_features_match_frozen_oracle(sources, enriched):
    _, expected, _, tolerance, _ = sources
    columns = [
        "beta_market",
        "beta_size",
        "style_state",
        "style_raw",
        "p_style",
        "ma_gap",
        "relative4",
    ]
    assert_parity(
        enriched,
        expected,
        keys=["date", "code"],
        columns=columns,
        atol=tolerance.feature_parity_atol,
        rtol=tolerance.feature_parity_rtol,
    )


@pytest.mark.pilot
@pytest.mark.parametrize("cycle", ["weekly", "monthly", "quarterly"])
def test_pil_02_p0_scores_ranks_membership_exact(sources, history, cycle):
    *_, root = sources
    for kind, actual in [("signals", history.signals[cycle]), ("ranking", history.rankings[cycle])]:
        reference = pl.read_csv(
            root / f"P0_English_Delivery_20261022/reference_outputs/p60/{cycle}_{kind}.csv",
            try_parse_dates=True,
        )
        assert actual.columns == reference.columns
        assert_parity(
            actual, reference, keys=["date", "code"], columns=reference.columns, atol=0, rtol=0
        )


@pytest.mark.pilot
def test_pil_02_quarterly_review_actions_exact(sources, history):
    *_, root = sources
    reference = pl.read_csv(
        root / "P0_English_Delivery_20261022/reference_outputs/p60/quarterly_review_actions.csv",
        try_parse_dates=True,
    )
    assert_parity(
        history.review_actions,
        reference,
        keys=["date", "removed"],
        columns=reference.columns,
        atol=0,
        rtol=0,
    )


@pytest.mark.pilot
def test_p0_scores_survive_canonical_json_and_jsonb_key_reordering(enriched, history):
    from polars.testing import assert_frame_equal

    value = json.loads(Path("configs/pilot/p0_scoring.json").read_bytes())
    for field in ("monthly_fundamental_internal", "monthly_market_internal"):
        # JSONB uses length/byte ordering; canonical JSON sorts lexically.
        value[field] = dict(sorted(value[field].items(), key=lambda item: (len(item[0]), item[0])))
    for reordered in (value, json.loads(json.dumps(value, sort_keys=True))):
        actual = p0_history(enriched, P0Config.model_validate(reordered))
        for cycle in history.signals:
            assert_frame_equal(actual.signals[cycle], history.signals[cycle], check_exact=True)


@pytest.mark.pilot
def test_six_v4_dsl_expressions_equal_polars(sources):
    tables, _, features, tolerance, _ = sources
    panel = tables["features"].select("code", "date")
    codes = tables["universe"]["code"].to_list()
    prices = tables["prices_daily"].filter(pl.col("code").is_in(codes))
    actual = price_features(panel, prices, codes, features)
    dsl = DSLConfig.load(Path("configs/dsl/pilot_industry_v1.json"))
    for name, expression in features.expressions().items():
        for prefix, expr in [("v4_raw_", expression), ("v4_p_", f"Rank({expression})")]:
            daily = evaluate(expr, prices.rename({"code": "instrument"}), dsl).rename(
                {"instrument": "code", "value": prefix + name, "date": "price_date"}
            )
            aligned = panel.sort("code", "date").join_asof(
                daily.sort("code", "price_date"),
                left_on="date",
                right_on="price_date",
                by="code",
                strategy="backward",
                check_sortedness=False,
            )
            assert_parity(
                aligned,
                actual,
                keys=["date", "code"],
                columns=[prefix + name],
                atol=tolerance.feature_parity_atol,
                rtol=tolerance.feature_parity_rtol,
            )


@pytest.mark.pilot
def test_pilot_feature_prefix_and_nontrading_asof(sources):
    tables, _, features, tolerance, _ = sources
    cutoff = date(2023, 12, 29)
    panel = tables["features"].select("date", "code")
    codes = tables["universe"]["code"].to_list()
    full = price_features(panel, tables["prices_daily"], codes, features)
    prefix = price_features(
        panel.filter(pl.col("date") <= cutoff),
        tables["prices_daily"].filter(pl.col("date") <= cutoff),
        codes,
        features,
    )
    assert_parity(
        prefix,
        full.filter(pl.col("date") <= cutoff),
        keys=["date", "code"],
        columns=prefix.columns,
        atol=tolerance.feature_parity_atol,
        rtol=tolerance.feature_parity_rtol,
    )
    weekend = pl.DataFrame({"code": codes, "date": [date(2023, 12, 31)] * len(codes)})
    result = price_features(weekend, tables["prices_daily"], codes, features)
    assert result["v4_price_date"].unique().to_list() == [cutoff]


def test_parity_failure_names_first_differing_cell():
    actual = pl.DataFrame({"code": ["A"], "score": [1.0]})
    with pytest.raises(
        AssertionError, match="first differing cell.*column=score.*actual=1.0 expected=2.0"
    ):
        assert_parity(
            actual,
            actual.with_columns(pl.lit(2.0).alias("score")),
            keys=["code"],
            columns=["score"],
            atol=0,
            rtol=0,
        )
