"""TopK-dropout portfolio rules shared by the backtester and the sim-engine (PLAN 7.8, P8.2).

v1: a long-only book of k names. On each decision day the eligible names with a score are
ranked (best first, ties by ascending column); up to n holdings outside the top k are
sold, worst first, on top of any sell still pending; buy candidates are the ranked names
not held, taken in order until the book holds k names again.

Phase 8 rules (qfr-strategy/2), each optional:
  - long-short: a second book shorts the k worst-ranked names with the same dropout,
    never a name in the long top k. Entering a short sells and covering buys, so a short
    entry is blocked by a suspension or a limit-down close and a cover by a suspension or
    a limit-up close. Both books are sized at NAV / k a name (gross 2, net 0), and the
    protocol's annual borrow cost is charged daily on the short book's value.
  - position cap: entries are sized at min(NAV / k, cap x NAV), and a holding whose
    weight drifts above the cap by more than TRIM_BAND of it is cut back to the cap.
  - industry cap: a book holds at most max(1, floor(cap x k)) names of one industry, so
    its top k is built by walking down the ranking and skipping full industries, and
    names without an industry are left out.
  - industry neutralization (applied to the scores, not here): see neutralize().
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
from numpy.typing import NDArray

from qfr_core.data.industry import NO_INDUSTRY

Array = NDArray[np.float64]
TRIM_BAND: Final = 0.10
BORROW_DAYS: Final = 252


@dataclass(frozen=True)
class PortfolioRules:
    top_k: int
    dropout: int
    long_only: bool = True
    max_position_weight: float | None = None
    max_industry_weight: float | None = None
    borrow_bps: float = 0.0  # annual, on the short book's value

    @property
    def industry_slots(self) -> int | None:
        if self.max_industry_weight is None:
            return None
        return max(1, math.floor(self.max_industry_weight * self.top_k + 1e-9))

    @property
    def needs_industry(self) -> bool:
        return self.max_industry_weight is not None

    def entry_size(self, nav: float) -> float:
        size = nav / self.top_k
        if self.max_position_weight is not None:
            size = min(size, self.max_position_weight * nav)
        return size

    def over_cap(self, value: float, nav: float) -> bool:
        cap = self.max_position_weight
        return cap is not None and nav > 0 and abs(value) > cap * nav * (1.0 + TRIM_BAND)

    def daily_borrow(self, short_value: float) -> float:
        """The day's borrow cost on a short book worth short_value (negative)."""
        return abs(short_value) * self.borrow_bps / 10_000.0 / BORROW_DAYS


@dataclass(frozen=True)
class Decision:
    """Orders decided at t for execution at t+1, as column indices."""

    sells: list[int]  # long holdings to close, pending ones first
    buys: list[int]  # long entry candidates, best first
    covers: list[int] = field(default_factory=list)  # short holdings to close
    shorts: list[int] = field(default_factory=list)  # short entry candidates, worst first
    trims: list[int] = field(default_factory=list)  # holdings above the position cap


def neutralize(scores: Array, codes: NDArray[np.int64]) -> Array:
    """Demean each day's scores within each industry. Names without an industry drop out
    (NaN), so an industry-neutral book only holds classified names."""
    out = np.full(scores.shape, np.nan)
    valid = np.isfinite(scores) & (codes != NO_INDUSTRY)
    if not valid.any():
        return out
    width = int(codes.max()) + 1
    for t in np.flatnonzero(valid.any(axis=1)):
        row = valid[t]
        groups = codes[t, row]
        values = scores[t, row]
        sums = np.bincount(groups, weights=values, minlength=width)
        counts = np.bincount(groups, minlength=width)
        out[t, row] = values - sums[groups] / counts[groups]
    return out


def capped(
    ranking: Sequence[int], k: int, industry: NDArray[np.int64] | None, slots: int | None
) -> list[int]:
    """The first k names of the ranking, at most `slots` from one industry."""
    if slots is None or industry is None:
        return list(ranking[:k])
    taken: dict[int, int] = {}
    out: list[int] = []
    for j in ranking:
        code = int(industry[j])
        if code == NO_INDUSTRY or taken.get(code, 0) >= slots:
            continue
        taken[code] = taken.get(code, 0) + 1
        out.append(j)
        if len(out) == k:
            break
    return out


def _exits(
    held: Iterable[int], top: set[int], pending: Sequence[int], order: Mapping[int, int], n: int
) -> list[int]:
    """Pending exits, then up to n holdings outside the top, worst ranked first."""
    waiting = set(pending)
    outside = [j for j in held if j not in top and j not in waiting]
    outside.sort(key=lambda j: (-order.get(j, len(order)), j))
    return list(pending) + outside[:n]


def decide(
    scores: Array,
    eligible: NDArray[np.bool_],
    industry: NDArray[np.int64] | None,
    longs: Mapping[int, float],
    shorts: Mapping[int, float],
    pending_sells: Sequence[int],
    pending_covers: Sequence[int],
    nav: float,
    rules: PortfolioRules,
) -> Decision:
    """One decision day. longs and shorts map held columns to their value (shorts
    negative); scores, eligible and industry are the day's rows."""
    k, n, slots = rules.top_k, rules.dropout, rules.industry_slots
    names = np.flatnonzero(eligible & np.isfinite(scores)).tolist()
    ranking = sorted(names, key=lambda j: (-scores[j], j))
    top = set(capped(ranking, k, industry, slots))
    rank_of = {j: r for r, j in enumerate(ranking)}
    sells = _exits(longs, top, pending_sells, rank_of, n)
    buys = [j for j in ranking if j not in longs and j not in shorts]
    if slots is not None and industry is not None:
        buys = [j for j in buys if industry[j] != NO_INDUSTRY]
    covers: list[int] = []
    short_entries: list[int] = []
    if not rules.long_only:
        worst = sorted((j for j in names if j not in top), key=lambda j: (scores[j], j))
        short_top = set(capped(worst, k, industry, slots))
        short_rank = {j: r for r, j in enumerate(worst)}
        covers = _exits(shorts, short_top, pending_covers, short_rank, n)
        short_entries = [j for j in worst if j not in shorts and j not in longs]
        if slots is not None and industry is not None:
            short_entries = [j for j in short_entries if industry[j] != NO_INDUSTRY]
    leaving = set(sells) | set(covers)
    trims = [
        j
        for j, value in sorted({**longs, **shorts}.items())
        if j not in leaving and rules.over_cap(value, nav)
    ]
    return Decision(sells, buys, covers, short_entries, trims)


def industry_full(
    j: int, book: Iterable[int], industry: NDArray[np.int64] | None, slots: int | None
) -> bool:
    """Whether adding j would put more than `slots` names of its industry in the book."""
    if slots is None or industry is None:
        return False
    code = int(industry[j])
    if code == NO_INDUSTRY:
        return True
    return sum(1 for h in book if int(industry[h]) == code) >= slots
