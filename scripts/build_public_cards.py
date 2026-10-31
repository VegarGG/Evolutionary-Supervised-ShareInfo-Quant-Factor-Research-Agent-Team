"""Build-time, whitelist-only public protocol and policy cards. Nothing is activated here.

The evaluator builds the same cards from the active versions (qfr_core.cards).
"""

import json
from pathlib import Path

import yaml
from qfr_core.cards import build_cards

root = Path("configs")
protocol = yaml.safe_load((root / "protocols/cn_csi300_daily_v1.yaml").read_text())
policy = yaml.safe_load((root / "release_policies/default_v1.yaml").read_text())
quotas = yaml.safe_load((root / "quotas/default_v1.yaml").read_text())
(root / "public_cards.json").write_text(
    json.dumps(build_cards(protocol, policy, quotas), indent=2, sort_keys=True) + "\n"
)
