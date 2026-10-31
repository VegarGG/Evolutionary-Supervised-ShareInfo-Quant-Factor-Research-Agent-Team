"""Market data adapters (PLAN Section 6.1, P8.6).

An adapter turns one market's raw data into a canonical snapshot (SnapshotData plus its
SnapshotSource). Two are defined:

  - CN A-shares (the v1 source, investment_data releases): CnAdapter wraps qfr_eval.ingest.cn.
  - US equities: the interface only. A usable US source must be point in time, which no
    free source is, so UsEquitiesAdapter states what a vendor feed must provide
    (VendorFeed and US_VENDOR_REQUIREMENTS) and refuses to build until one is configured.

Building US data also needs changes outside the adapter, listed in US_PANEL_CHANGES: the
canonical panel's universe flags and price-limit rules are A-share specific today.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Literal, Protocol, runtime_checkable

import polars as pl
from qfr_core.data.snapshot import SnapshotData, SnapshotSource

from qfr_eval.ingest.cn import ingest_cn
from qfr_eval.ingest.config import CnIngestConfig


@dataclass(frozen=True)
class MarketConventions:
    """What the evaluator's trading rules assume about a market."""

    market: Literal["cn", "us"]
    currency: str
    timezone: str
    settlement: str
    lot_size: int
    price_limits: str
    short_selling: str
    benchmark: str


CN_CONVENTIONS: Final = MarketConventions(
    market="cn",
    currency="CNY",
    timezone="Asia/Shanghai",
    settlement="T+1",
    lot_size=100,
    price_limits="main board 10%, STAR and ChiNext 20%",
    short_selling="restricted to margin-eligible names; strategies may model it with a "
    "borrow cost (strategy_rules.long_short)",
    benchmark="SH000300",
)
US_CONVENTIONS: Final = MarketConventions(
    market="us",
    currency="USD",
    timezone="America/New_York",
    settlement="T+1 (since 2024-05-28)",
    lot_size=1,
    price_limits="none (market-wide circuit breakers and LULD halts only)",
    short_selling="allowed subject to locate and borrow cost",
    benchmark="a total-return index from the vendor, else equal weight of the universe",
)


@runtime_checkable
class MarketAdapter(Protocol):
    """Builds one canonical snapshot from a market's raw data."""

    conventions: MarketConventions

    def build(self, raw_dir: Path) -> tuple[SnapshotData, SnapshotSource]: ...


class CnAdapter:
    """China A-shares from an investment_data release (verified, then read)."""

    conventions = CN_CONVENTIONS

    def __init__(
        self,
        config: CnIngestConfig,
        *,
        archive: Path | None = None,
        manifest: Path | None = None,
        sha256: str | None = None,
        release_tag: str | None = None,
    ) -> None:
        self.config = config
        self.archive, self.manifest, self.sha256 = archive, manifest, sha256
        self.release_tag = release_tag

    def build(self, raw_dir: Path) -> tuple[SnapshotData, SnapshotSource]:
        return ingest_cn(
            self.config, raw_dir, archive=self.archive, manifest=self.manifest,
            sha256=self.sha256, release_tag=self.release_tag,
        )  # fmt: skip


@runtime_checkable
class VendorFeed(Protocol):
    """What a point-in-time US equities vendor must deliver. Every frame is as known at
    the time, never restated with hindsight."""

    name: str

    def calendar(self) -> Sequence[date]:
        """Exchange trading days (NYSE), ascending."""
        ...

    def constituents(self, universe: str) -> pl.DataFrame:
        """Index membership as inclusive intervals: instrument, start, end. Delisted and
        removed names included."""
        ...

    def bars(self, instruments: Sequence[str]) -> pl.DataFrame:
        """Daily rows: date, instrument, open, high, low, close, volume, amount, plus
        factor, the cumulative split and dividend adjustment with close / factor the
        traded price. Full history for delisted names."""
        ...

    def identifiers(self) -> pl.DataFrame:
        """Permanent instrument id against ticker and CUSIP over time, so ticker reuse
        and changes never merge two companies."""
        ...

    def industry(self, scheme: str) -> pl.DataFrame:
        """Point-in-time classification (GICS or similar): instrument, start, end, industry."""
        ...


US_VENDOR_REQUIREMENTS: Final = (
    "point-in-time index constituents with dates, including removed names",
    "full price history for delisted companies (no survivorship bias)",
    "split and dividend adjustment factors, so raw = adjusted / factor",
    "permanent instrument ids across ticker changes and reuse",
    "the NYSE trading calendar, holidays and early closes",
    "point-in-time industry classification if industry neutrality is wanted",
    "a license that allows local storage and research use",
)
US_PANEL_CHANGES: Final = (
    "the panel's universe flags (in_csi300, in_csi500) generalized to the market's universes",
    "price limits off (limit_up and limit_down always false) instead of A-share board rules",
    "the raw price check range (0.5 to 5,000) set per market",
    "lot size 1 in the protocol's simulation section",
    "a protocol per market (costs, universe, benchmark) with its own epoch file",
)


class AdapterUnavailable(RuntimeError):
    """The adapter has no data source configured."""


class UsEquitiesAdapter:
    """US equities: the interface, not yet an implementation. It needs a VendorFeed (see
    US_VENDOR_REQUIREMENTS) and the panel changes in US_PANEL_CHANGES."""

    conventions = US_CONVENTIONS

    def __init__(self, vendor: VendorFeed | None = None) -> None:
        self.vendor = vendor

    def build(self, raw_dir: Path) -> tuple[SnapshotData, SnapshotSource]:
        if self.vendor is None:
            raise AdapterUnavailable(
                "US equities need a point-in-time vendor feed; none is configured. "
                "Requirements: " + "; ".join(US_VENDOR_REQUIREMENTS)
            )
        raise AdapterUnavailable(
            f"vendor {self.vendor.name!r} is configured, but the canonical panel is still "
            "A-share specific. Needed first: " + "; ".join(US_PANEL_CHANGES)
        )
