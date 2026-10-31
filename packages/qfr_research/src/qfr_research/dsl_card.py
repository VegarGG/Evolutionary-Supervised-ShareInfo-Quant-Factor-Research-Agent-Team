"""The DSL reference card for prompts (P4.6, PLAN Section 11.5).

Generated from the operator registry in qfr_core.dsl (the single source of truth) and the
protocol's public DSL limits, never written by hand. Its version is the SHA-256 of the
text, recorded in every engineer step's inputs so a trace names the card it saw.
"""

import hashlib
from dataclasses import dataclass

from qfr_core.dsl import DslLimits
from qfr_core.dsl.catalog import (
    CONSTANT_DECIMALS,
    CONSTANT_MAX,
    CONSTANT_MIN,
    FIELD_COLUMNS,
    NEUTRALIZE_FIELD,
    OPERATORS,
    SIGNED_POWER_EXPONENTS,
    OpSpec,
)
from qfr_core.dsl.explain import ARITHMETIC_MEANINGS, FIELD_MEANINGS, OPERATOR_MEANINGS

KIND_TITLES = {
    "ts": "Time-series operators (per instrument, over the last d trading days)",
    "cs": "Cross-sectional operators (across instruments on one day)",
    "elementwise": "Element-wise operators",
}
# Two examples that exercise the grammar; they are syntax illustrations, not suggestions.
EXAMPLES = ("Rank(Mean($close, 5) / Mean($close, 20) - 1)", "TsZ($volume, 10) * Sign(Delta($close, 5))")


@dataclass(frozen=True)
class DslCard:
    version: str
    text: str


def _signature(spec: OpSpec) -> str:
    names = {"series": "x", "operand": "x", "window": "d", "const": "c"}
    args = [names[p] for p in spec.params]
    if spec.params == ("series", "series", "window"):
        args = ["x", "y", "d"]
    if spec.name in ("Max2", "Min2"):
        args = ["x", "y"]
    if spec.name == "If":
        args = ["cond", "x", "y"]
    if spec.name == "Clip":
        args = ["x", "lo", "hi"]
    return f"{spec.name}({', '.join(args)})"


def build_card(limits: DslLimits) -> DslCard:
    lines = ["# qfr-dsl/1 reference card", "", "## Fields"]
    for name in FIELD_COLUMNS:
        lines.append(f"- ${name}: {FIELD_MEANINGS.get(name, name)}")
    for kind, title in KIND_TITLES.items():
        lines += ["", f"## {title}"]
        for spec in OPERATORS.values():
            if spec.kind != kind:
                continue
            extra = f" (d >= {spec.min_window})" if spec.kind == "ts" else ""
            lines.append(f"- {_signature(spec)}{extra}: {OPERATOR_MEANINGS.get(spec.name, '')}")
    lines += ["", "## Arithmetic"]
    lines += [f"- {op}: {meaning}" for op, meaning in ARITHMETIC_MEANINGS.items()]
    lines += [
        "",
        "## Constraints (the evaluator applies the same limits)",
        f"- Windows d must be one of: {', '.join(str(w) for w in limits.windows)}",
        f"- At most {limits.max_nodes} nodes, depth {limits.max_depth}, "
        f"{limits.max_fields} distinct fields, {limits.max_constants} constants",
        f"- Maximum lookback {limits.max_lookback_days} trading days; "
        f"Corr/Cov nesting at most {limits.max_corr_cov_nesting}",
        f"- Constants lie in [{CONSTANT_MIN:g}, {CONSTANT_MAX:g}] with at most "
        f"{CONSTANT_DECIMALS} decimals; SignedPower exponents: "
        f"{', '.join(f'{e:g}' for e in SIGNED_POWER_EXPONENTS)}",
        f"- Neutralize reads ${NEUTRALIZE_FIELD} implicitly",
        "- No future data: every operator looks only at days on or before t",
        "",
        "## Syntax examples",
    ]
    lines += [f"- {example}" for example in EXAMPLES]
    text = "\n".join(lines) + "\n"
    return DslCard(hashlib.sha256(text.encode()).hexdigest(), text)
