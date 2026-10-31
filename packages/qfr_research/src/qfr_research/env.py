"""The services one research process shares: configuration, database, clock, logger,
trace writer, registry and feedback clients, the workbench, prices, models and prompts."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from qfr_core.config import public_protocol_section
from qfr_core.data.snapshot import open_research_snapshot
from qfr_core.dsl import DslLimits
from qfr_core.logging import JsonLogger
from qfr_core.workbench import Workbench

from qfr_research.budget import BudgetLedger
from qfr_research.clients import FeedbackClient, RegistryClient
from qfr_research.db import Clock, Database
from qfr_research.dsl_card import DslCard, build_card
from qfr_research.prompts import PromptLibrary
from qfr_research.providers import ModelSource, Planner, PriceTable
from qfr_research.settings import ResearchConfig
from qfr_research.store import TraceWriter

QFR_CORE_VERSION = "0.1.0"


@dataclass
class ResearchEnv:
    config: ResearchConfig
    db: Database
    clock: Clock
    logger: JsonLogger
    registry: RegistryClient
    feedback: FeedbackClient | None
    models: ModelSource
    prompts: PromptLibrary
    research_snapshot_dir: Path | None
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    trace: TraceWriter = field(init=False)
    limits: DslLimits = field(init=False)
    card: DslCard = field(init=False)
    prices: PriceTable = field(init=False)
    planner: Planner = field(init=False)
    ledger: BudgetLedger = field(init=False)
    public_cards: dict[str, Any] = field(init=False)
    _workbench: Workbench | None = field(default=None, init=False)
    _snapshot_id: str | None = field(default=None, init=False)
    fingerprints: dict[str, Any] = field(default_factory=dict, init=False)
    # W0 workbench reports by (canonical expression, sign): the research snapshot is
    # fixed for the env's lifetime, and a draft the engineer checked with
    # workbench.evaluate is checked again by the deterministic checks.
    factor_reports: dict[tuple[str, int], Any] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.trace = TraceWriter(self.logger, self.clock)
        self.limits = DslLimits.from_protocol(public_protocol_section(self.config.root, "dsl"))
        self.card = build_card(self.limits)
        self.prices = PriceTable(self.config.providers)
        self.planner = Planner(self.config.providers, self.config.roles)
        budget = self.config.providers.budget
        self.ledger = BudgetLedger(
            Decimal(str(budget["daily_cap"])), Decimal(str(budget["generation_cap"]))
        )
        self.public_cards = json.loads(
            (self.config.root / "public_cards.json").read_text(encoding="utf-8")
        )

    @property
    def workbench(self) -> Workbench:
        if self._workbench is None:
            if self.research_snapshot_dir is None:
                raise RuntimeError("SNAPSHOT_UNAVAILABLE: no research snapshot is configured")
            self._workbench = Workbench(self.research_snapshot_dir, self.public_cards)
        return self._workbench

    @property
    def snapshot_id(self) -> str:
        if self._workbench is not None:
            return self._workbench.snapshot.snapshot_id
        if self._snapshot_id is None:
            if self.research_snapshot_dir is None:
                raise RuntimeError("SNAPSHOT_UNAVAILABLE: no research snapshot is configured")
            self._snapshot_id = open_research_snapshot(self.research_snapshot_dir).snapshot_id
        return self._snapshot_id

    @property
    def charter_defaults(self) -> dict[str, Any]:
        return dict(self.config.charter_values)
