"""Deterministic plain-language explanation of a canonical expression (qfr.dsl.validate).

No LLM writes it: the text is assembled from the operator glossary and the static
analysis, so the same expression always gets the same explanation.
"""

from pydantic import BaseModel, ConfigDict

from qfr_core.dsl.analysis import DslAnalysis
from qfr_core.dsl.ast import BinOp, Call, Compare, Neg, Node, Window, walk
from qfr_core.dsl.catalog import FIELD_COLUMNS, NEUTRALIZE_FIELD, OPERATORS

FIELD_MEANINGS: dict[str, str] = {
    "open": "adjusted open price",
    "high": "adjusted high price",
    "low": "adjusted low price",
    "close": "adjusted close price",
    "vwap": "adjusted volume-weighted average price",
    "volume": "traded volume",
    "amount": "traded amount",
    "ret": "one-day return to the close",
    "adv20": "20-day average traded amount",
    "close_raw": "unadjusted close price",
}

OPERATOR_MEANINGS: dict[str, str] = {
    "Ref": "the value d trading days earlier",
    "Delta": "the change over d trading days",
    "Pct": "the percentage change over d trading days",
    "Mean": "the rolling mean over d days",
    "Sum": "the rolling sum over d days",
    "Std": "the rolling standard deviation over d days",
    "Var": "the rolling variance over d days",
    "Min": "the rolling minimum over d days",
    "Max": "the rolling maximum over d days",
    "Med": "the rolling median over d days",
    "EMA": "the exponential moving average with span d",
    "WMA": "the linearly weighted moving average over d days",
    "TsRank": "today's rank within the last d days",
    "TsZ": "today's z-score within the last d days",
    "ArgMax": "the number of days since the d-day maximum",
    "ArgMin": "the number of days since the d-day minimum",
    "Corr": "the rolling correlation of two series over d days",
    "Cov": "the rolling covariance of two series over d days",
    "Slope": "the slope of a regression on time over d days",
    "Rsq": "the R-squared of a regression on time over d days",
    "Resi": "today's residual from a regression on time over d days",
    "Skew": "the rolling skewness over d days",
    "Kurt": "the rolling excess kurtosis over d days",
    "Rank": "the cross-sectional rank on each day",
    "Zscore": "the cross-sectional z-score on each day",
    "Demean": "the value minus the cross-sectional mean on each day",
    "Scale": "the value scaled so absolute values sum to one on each day",
    "Neutralize": f"the residual after removing the cross-sectional effect of {NEUTRALIZE_FIELD}",
    "Abs": "the absolute value",
    "Sign": "the sign (-1, 0 or 1)",
    "Log": "the natural logarithm",
    "Sqrt": "the square root",
    "SignedPower": "the signed power",
    "Clip": "the value clipped to a range",
    "Max2": "the larger of two values",
    "Min2": "the smaller of two values",
    "If": "a choice between two values by a condition",
}

ARITHMETIC_MEANINGS: dict[str, str] = {
    "+": "addition",
    "-": "subtraction",
    "*": "multiplication",
    "/": "division",
}


class OperatorUse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    meaning: str
    windows: list[int]


class Explanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    summary: str
    fields: dict[str, str]
    operators: list[OperatorUse]


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def explain(tree: Node, analysis: DslAnalysis) -> Explanation:
    """Explain a canonical tree in fixed sentences. Every list is sorted."""
    windows: dict[str, set[int]] = {}
    arithmetic: set[str] = set()
    comparisons = False
    negation = False
    for node in walk(tree):
        if isinstance(node, Call):
            used = windows.setdefault(node.name, set())
            used.update(a.days for a in node.args if isinstance(a, Window))
        elif isinstance(node, BinOp):
            arithmetic.add(node.op)
        elif isinstance(node, Compare):
            comparisons = True
        elif isinstance(node, Neg):
            negation = True
    operators = [
        OperatorUse(name=name, meaning=OPERATOR_MEANINGS[name], windows=sorted(windows[name]))
        for name in sorted(windows)
    ]
    fields = {name: FIELD_MEANINGS[name] for name in analysis.fields if name in FIELD_COLUMNS}
    parts = [f"Uses {_join([f'${name} ({meaning})' for name, meaning in fields.items()])}."]
    if operators:
        described = []
        for use in operators:
            spec = OPERATORS[use.name]
            label = use.name
            if use.windows:
                days = "/".join(str(d) for d in use.windows)
                label += f" over {days} days" if spec.kind == "ts" else ""
            described.append(f"{label} ({use.meaning})")
        parts.append(f"Applies {_join(described)}.")
    extras = [ARITHMETIC_MEANINGS[op] for op in sorted(arithmetic)]
    if comparisons:
        extras.append("comparisons")
    if negation:
        extras.append("negation")
    if extras:
        parts.append(f"Combines terms with {_join(extras)}.")
    parts.append(
        f"Reads {analysis.max_lookback_days} trading days of history before the decision "
        "day. The value is known at close t and the protocol trades it at close t+1."
    )
    parts.append(
        f"Size: {analysis.nodes} nodes, depth {analysis.depth}, complexity {analysis.complexity}."
    )
    return Explanation(summary=" ".join(parts), fields=fields, operators=operators)
