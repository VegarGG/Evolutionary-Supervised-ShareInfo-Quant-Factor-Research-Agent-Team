"""qfr-strategy/2 manifests, job specs and pool imports (PLAN 7.8, P8.2)."""

import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from qfr_core.composite import strategy_canonical_hash, strategy_diff
from qfr_core.config import ProtocolConfig
from qfr_core.contracts import StrategyManifest, StrategyRules, StrategySpec
from qfr_core.ids import uuid7
from qfr_core.pool_import import (
    ValidEntry,
    entry_digest,
    qfr_core_version,
    strategy_seed_manifest,
    validate_entries,
)
from qfr_research.packager import strategy_implementation

from tests.registry_rig import LIMITS, strategy_manifest
from tests.test_pool_import import FACTOR, REVERSAL, STRATEGY, ids

PROTOCOL = Path("configs/protocols/cn_csi300_daily_v1.yaml")


def v2(components, **portfolio):
    manifest = strategy_manifest(components)
    manifest["implementation"] = {
        "language": "qfr-strategy/2",
        "components": manifest["implementation"]["components"],
        "combination": "zscore_weighted_sum",
        "neutralize": portfolio.pop("neutralize", "industry"),
        "portfolio": {
            "type": "topk_dropout",
            "top_k": 50,
            "dropout": 5,
            "rebalance": "daily",
            "long_only": True,
            "max_position_weight": None,
            "max_industry_weight": None,
        }
        | portfolio,
    }
    return manifest


def test_a_v2_manifest_parses_and_hashes_apart_from_v1():
    component = str(uuid7())
    plain = StrategyManifest.model_validate(strategy_manifest([(component, 1, 1.0)]))
    neutral = StrategyManifest.model_validate(v2([(component, 1, 1.0)]))
    long_short = StrategyManifest.model_validate(
        v2([(component, 1, 1.0)], neutralize="none", long_only=False)
    )
    hashes = {strategy_canonical_hash(m.implementation) for m in (plain, neutral, long_short)}
    assert len(hashes) == 3
    edits = strategy_diff(plain.implementation, long_short.implementation)
    ops = {(e["op"], e.get("field")) for e in edits}
    assert ("language_changed", None) in ops and ("portfolio_changed", "long_only") in ops
    assert ("neutralize_changed", None) not in ops  # none on both sides
    edits = strategy_diff(neutral.implementation, long_short.implementation)
    assert {"op": "neutralize_changed", "from": "industry", "to": "none"} in edits


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"neutralize": "none"}, "at least one Phase 8 rule"),
        ({"max_position_weight": 0.0125}, "decimals"),
        ({"max_position_weight": 0.5}, "less than or equal"),
        ({"max_industry_weight": 0.01}, "greater than or equal"),
    ],
)
def test_v2_manifests_refuse_empty_or_malformed_rules(change, message):
    with pytest.raises(ValidationError, match=message):
        StrategyManifest.model_validate(v2([(str(uuid7()), 1, 1.0)], **change))


def test_job_specs_carry_rules_that_fit_the_portfolio():
    spec = StrategySpec(top_k=40, dropout=4, max_components=3, rules=StrategyRules(long_short=True))
    assert spec.rules is not None and spec.rules.portfolio(40, 4).long_only is False
    with pytest.raises(ValidationError, match="at least one"):
        StrategyRules()
    with pytest.raises(ValidationError, match="less than or equal"):
        StrategySpec(
            top_k=40, dropout=4, max_components=3, rules=StrategyRules(max_position_weight=0.9)
        )


def test_the_packager_emits_v2_only_with_rules():
    payload = {
        "components": [{"version_id": str(uuid7()), "sign": 1, "weight": 1.0}],
        "portfolio": {"top_k": 30, "dropout": 3},
    }
    assert strategy_implementation(payload)["language"] == "qfr-strategy/1"
    rules = {"long_short": True, "neutralize": "industry", "max_industry_weight": 0.3}
    implementation = strategy_implementation(payload | {"rules": rules})
    assert implementation["language"] == "qfr-strategy/2"
    assert implementation["neutralize"] == "industry"
    assert implementation["portfolio"]["long_only"] is False
    assert implementation["portfolio"]["max_industry_weight"] == 0.3


def test_pool_imports_accept_rules_and_keep_v1_digests():
    ruled = copy.deepcopy(STRATEGY) | {"name": "trend_and_reversal_ls"}
    ruled["strategy"]["rules"] = {"long_short": True, "max_position_weight": 0.05}
    results = validate_entries([FACTOR, REVERSAL, STRATEGY, ruled], LIMITS)
    plain, with_rules = results[2], results[3]
    assert isinstance(plain, ValidEntry) and isinstance(with_rules, ValidEntry)
    components = {"ma_cross_20_60": uuid7(), "reversal_5": uuid7()}
    assert entry_digest(plain.entry, components) != entry_digest(with_rules.entry, components)
    manifest = strategy_seed_manifest(
        with_rules.entry, components, ids(), None, None, qfr_core_version()
    )
    implementation = manifest.implementation
    assert implementation.language == "qfr-strategy/2"
    assert implementation.portfolio.long_only is False
    assert implementation.portfolio.max_position_weight == 0.05
    bad = copy.deepcopy(STRATEGY)
    bad["strategy"]["rules"] = {}
    assert not isinstance(validate_entries([FACTOR, REVERSAL, bad], LIMITS)[2], ValidEntry)


def test_the_protocol_bounds_the_rules():
    raw = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    ProtocolConfig.model_validate(raw)
    assert raw["strategy_rules"]["long_short"]["borrow_bps_annual"] == 800
    broken = raw | {"strategy_rules": raw["strategy_rules"] | {"max_position_weight": [0.2, 0.1]}}
    with pytest.raises(ValidationError, match="cap ranges"):
        ProtocolConfig.model_validate(broken)
