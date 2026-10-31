"""Build-time, whitelist-only public protocol and policy cards. Nothing is activated here."""

import json
from pathlib import Path

import yaml

root = Path("configs")
protocol = yaml.safe_load((root / "protocols/cn_csi300_daily_v1.yaml").read_text())
policy = yaml.safe_load((root / "release_policies/default_v1.yaml").read_text())
public = {
    key: protocol[key]
    for key in (
        "protocol_id",
        "version",
        "universe",
        "eligibility",
        "label",
        "preprocessing",
        "quantiles",
        "costs",
        "reference_strategy",
        "strategy_bounds",
        "dsl",
        # The research workbench computes the same W0 fingerprints as the evaluator.
        "fingerprint",
    )
}
public["gates"] = {
    key: protocol["gates"][key] for key in ("w1_factor", "w1_strategy", "w2_factor", "w2_strategy")
}
(root / "public_cards.json").write_text(
    json.dumps({"protocol": public, "policy": policy}, indent=2, sort_keys=True) + "\n"
)
