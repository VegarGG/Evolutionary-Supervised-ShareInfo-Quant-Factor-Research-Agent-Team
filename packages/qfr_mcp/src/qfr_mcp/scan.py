"""The owner-only scan (PLAN Section 9.6, test MCP-03).

A brief or steering note is free text that reaches research prompts. Before the front
door forwards one, it compares every decimal number in the text with the owner-only
values of each referenced version (official records, gate values, library and
simulation numbers from eval-admin-api) at full precision, written to the text's own
number of decimals, and at the release policy's precision for that metric. A match
rejects the text and is logged without the value. Only the verdict reaches research.
Signs are ignored, so writing a value negated does not hide it.
"""

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from qfr_core.research_api import BriefScan

NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d+\.\d+|\.\d+)(%?)")
# Keys whose numbers are public (protocol thresholds) or are not measurements.
SKIP_KEYS = frozenset({"threshold", "version", "protocol_version", "seed", "step"})
STEP_CLASSES = (
    ("sharpe", "sharpe"),
    ("rankic", "rankic"),
    ("turnover", "shares"),
    ("hit_ratio", "shares"),
    ("share", "shares"),
    ("correlation", "correlations"),
    ("monotonicity", "correlations"),
)


class OwnerValueInText(ValueError):
    def __init__(self, matches: int, version_ids: list[str]) -> None:
        super().__init__(
            "OWNER_ONLY_VALUE: the text contains a number that matches an owner-only value of "
            f"referenced version(s) {', '.join(version_ids)}. Remove owner-grade numbers from "
            "briefs and steering notes; refer to versions by id instead."
        )
        self.matches, self.version_ids = matches, version_ids


@dataclass(frozen=True)
class Written:
    value: Decimal
    decimals: int


def numbers(text: str) -> list[Written]:
    found = []
    for match in NUMBER.finditer(text):
        raw = match.group(0)
        percent = raw.endswith("%")
        digits = raw.rstrip("%")
        decimals = len(digits.split(".")[1])
        value = Decimal(digits)
        if percent:
            value, decimals = value / 100, decimals + 2
        found.append(Written(value, decimals))
    return found


def step_for(key: str, rounding: dict[str, Any]) -> Decimal | None:
    name = key.lower()
    if name.endswith("_ir") or name == "ir":
        return Decimal(str(rounding["ir"]))
    for fragment, cls in STEP_CLASSES:
        if fragment in name and cls in rounding:
            return Decimal(str(rounding[cls]))
    return None


def owner_values(evidence: Any, key: str = "") -> Iterator[tuple[str, float]]:
    """Every non-integral number of an owner evidence document, with its key."""
    if isinstance(evidence, dict):
        for k, v in evidence.items():
            if k not in SKIP_KEYS:
                yield from owner_values(v, str(k))
    elif isinstance(evidence, list):
        for item in evidence:
            yield from owner_values(item, key)
    elif isinstance(evidence, float) and math.isfinite(evidence) and not evidence.is_integer():
        yield key, evidence


def _quantize(value: float, step: Decimal) -> Decimal:
    units = (Decimal(repr(value)) / step).to_integral_value(rounding=ROUND_HALF_UP)
    return units * step


def matches(text: str, evidence: dict[str, Any], rounding: dict[str, Any]) -> tuple[int, int]:
    """(number of matching numbers in the text, number of owner values compared)."""
    written = numbers(text)
    values = list(owner_values(evidence))
    hits = 0
    for number in written:
        if number.decimals < 2 or number.value == 0:
            continue
        for key, value in values:
            exact = Decimal(repr(value)).quantize(
                Decimal(1).scaleb(-number.decimals), rounding=ROUND_HALF_UP
            )
            step = step_for(key, rounding)
            released = None if step is None else _quantize(value, step)
            # A sign change does not hide a value.
            target = abs(number.value)
            if abs(exact) == target or (released is not None and abs(released) == target):
                hits += 1
                break
    return hits, len(values)


def text_of_brief(brief: dict[str, Any]) -> str:
    seeds = brief.get("seeds") or {}
    parts = [
        str(brief.get("title", "")),
        str(brief.get("objective", "")),
        str(seeds.get("notes", "")),
    ]
    for seed in seeds.get("expressions") or []:
        parts += [str(seed.get("name", "")), str(seed.get("expression", "")),
                  str(seed.get("rationale", ""))]  # fmt: skip
    return "\n".join(parts)


def verdict(
    text: str,
    evidence: dict[str, dict[str, Any]],
    rounding: dict[str, Any],
    referenced: list[UUID],
) -> BriefScan:
    total_hits, compared, hit_versions = 0, 0, []
    for version_id, document in evidence.items():
        hits, count = matches(text, document, rounding)
        compared += count
        if hits:
            total_hits += hits
            hit_versions.append(version_id)
    if total_hits:
        raise OwnerValueInText(total_hits, sorted(hit_versions))
    return BriefScan(
        status="passed",
        scanner="qfr-mcp",
        referenced_version_ids=referenced,
        numbers_in_text=len(numbers(text)),
        values_compared=compared,
    )
