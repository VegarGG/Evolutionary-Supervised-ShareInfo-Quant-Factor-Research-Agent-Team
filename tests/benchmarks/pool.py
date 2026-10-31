"""The scripted LLM's expression pool for BM-PLANTED and BM-NULL (PLAN Section 18.3).

300 qfr-dsl/1 expressions: variants of the planted signals A1 (short-term reversal,
-Pct($close,5)) and A2 (volume-shock continuation, Clip(Sign($ret)*($volume/Mean(
$volume,20)-1),-3,3)) at several windows, plus many noise expressions. The pool is test
data for the benchmarks; the product ships no factor. Each entry knows its family and
window, so the scripted engineer can mutate a variant one window step towards or away
from the planted form, the way a targeted revision would.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from qfr_core.config import public_protocol_section
from qfr_core.dsl import DslLimits, canonicalize, parse, to_string, validate

A1 = "-Pct($close,5)"
A2 = "Clip(Sign($ret)*($volume/Mean($volume,20)-1),-3,3)"
PLANTED_WINDOW = {"A1": 5, "A2": 20}
SIZE = 300

# Variants span the archive's descriptors: plain, rank-normalized, smoothed (lower
# turnover), volatility-scaled (range_volatility), volume-conditioned (price_volume) and
# range-based forms, at several windows.
A1_TEMPLATES = (
    "-Pct($close,{w})",
    "-Pct($vwap,{w})",
    "-Delta($close,{w})/Ref($close,{w})",
    "Rank(-Pct($close,{w}))",
    "-Sum($ret,{w})",
    "-Pct($close,{w})/Std($ret,20)",
    "-Pct($close,{w})*Rank($volume/Mean($volume,20))",
    "EMA(-Pct($close,{w}),5)",
    "-Pct($close,{w})*($amount/Mean($amount,20))",
    "-(($high+$low)/2/Ref($close,{w})-1)",
    "-TsZ($close,{w})",
)
A1_WINDOWS = (2, 3, 5, 10, 20, 40)
A2_TEMPLATES = (
    "Clip(Sign($ret)*($volume/Mean($volume,{w})-1),-3,3)",
    "Sign($ret)*($volume/Mean($volume,{w})-1)",
    "Sign($ret)*Rank($volume/Mean($volume,{w}))",
    "Clip(Sign(Pct($close,1))*($volume/Mean($volume,{w})-1),-3,3)",
    "Sign($ret)*($amount/Mean($amount,{w})-1)",
    "EMA(Clip(Sign($ret)*($volume/Mean($volume,{w})-1),-3,3),5)",
)
A2_WINDOWS = (5, 10, 20, 40, 60)
NOISE_TEMPLATES = (
    "Std(${f},{w})",
    "Skew(${f},{w})",
    "TsZ(${f},{w})",
    "Slope(${f},{w})",
    "Mean(${f},{w})/Mean(${f},120)-1",
    "Corr(${f},$volume,{w})",
    "Max(${f},{w})/Min(${f},{w})-1",
    "Kurt(${f},{w})",
)
NOISE_FIELDS = ("high", "low", "open", "amount", "adv20")
NOISE_WINDOWS = (5, 10, 20, 40, 60, 120)  # the pool stops filling at 300


@dataclass(frozen=True)
class Entry:
    expression: str  # canonical
    family: str  # A1, A2 or noise
    template: int
    window: int


def limits() -> DslLimits:
    return DslLimits.from_protocol(public_protocol_section(Path("configs"), "dsl"))


def canonical(expression: str) -> str:
    return to_string(canonicalize(parse(expression)))


@lru_cache(maxsize=1)
def pool() -> tuple[Entry, ...]:
    """The 300 entries, in a fixed order; every one validates under the DSL limits."""
    dsl = limits()
    entries: list[Entry] = []
    seen: set[str] = set()

    def add(text: str, family: str, template: int, window: int) -> None:
        check = validate(text, dsl)
        if not check.ok or check.analysis is None or check.analysis.canonical in seen:
            return
        seen.add(check.analysis.canonical)
        entries.append(Entry(check.analysis.canonical, family, template, window))

    for t, template in enumerate(A1_TEMPLATES):
        for w in A1_WINDOWS:
            add(template.format(w=w), "A1", t, w)
    for t, template in enumerate(A2_TEMPLATES):
        for w in A2_WINDOWS:
            add(template.format(w=w), "A2", t, w)
    for w in NOISE_WINDOWS:
        for t, template in enumerate(NOISE_TEMPLATES):
            for f in NOISE_FIELDS:
                if len(entries) < SIZE:
                    add(template.format(f=f, w=w), "noise", t, w)
    if len(entries) != SIZE:
        raise RuntimeError(f"the benchmark pool has {len(entries)} entries, not {SIZE}")
    return tuple(entries)


@lru_cache(maxsize=1)
def index() -> dict[str, Entry]:
    return {e.expression: e for e in pool()}


def variant(family: str, template: int, window: int) -> Entry | None:
    for entry in pool():
        if entry.family == family and entry.template == template and entry.window == window:
            return entry
    return None


def towards_planted(entry: Entry) -> Entry:
    """One window step towards the planted window, or the planted template once there."""
    windows = A1_WINDOWS if entry.family == "A1" else A2_WINDOWS
    target = PLANTED_WINDOW[entry.family]
    i, goal = windows.index(entry.window), windows.index(target)
    if i != goal:
        found = variant(entry.family, entry.template, windows[i + (1 if goal > i else -1)])
        if found is not None:
            return found
    return variant(entry.family, 0, target) or entry
