"""The CNY budget ledger (P4.9, PLAN Section 11.7).

Three caps apply to every LLM call: the generation cap, the daily cap (the program's
charter value and the deployment-wide value from providers.yaml, per UTC day) and the
job cap from the brief. Before a call the ledger checks the call's estimate against the
smallest remaining amount and turns that remainder into a PydanticAI token limit, so a
run cannot spend past it by more than one bounded request; after the call it records
the priced usage. The ledger is insert-only.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from qfr_core.ids import uuid7
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_research.providers import MILLION, PriceQuote, TokenUsage
from qfr_research.store import Ctx

Scope = Literal["generation", "daily", "job"]


class BudgetExceeded(RuntimeError):
    def __init__(self, scope: Scope, spent: Decimal, cap: Decimal, needed: Decimal) -> None:
        super().__init__(
            f"{scope} budget: spent {spent} of {cap} CNY, the next call needs {needed}"
        )
        self.scope, self.spent, self.cap, self.needed = scope, spent, cap, needed


@dataclass(frozen=True)
class Caps:
    generation: Decimal
    program_daily: Decimal
    global_daily: Decimal
    job: Decimal


@dataclass(frozen=True)
class Remaining:
    scope: Scope
    amount: Decimal
    spent: Decimal
    cap: Decimal


class BudgetLedger:
    def __init__(self, global_daily_cap: Decimal, generation_cap: Decimal) -> None:
        self.global_daily_cap, self.generation_cap = global_daily_cap, generation_cap

    def caps(self, conn: Connection, ctx: Ctx) -> Caps:
        row = conn.execute(
            text(
                "SELECT j.budget, p.charter FROM research_jobs j "
                "LEFT JOIN programs p ON p.program_id = j.program_id WHERE j.job_id = :j"
            ),
            {"j": ctx.job_id},
        ).one()
        charter = row.charter or {}
        budget = charter.get("budget", {}) if isinstance(charter, dict) else {}
        generation = min(self.generation_cap, Decimal(str(budget.get("generation", "Infinity"))))
        daily = Decimal(str(budget.get("daily", self.global_daily_cap)))
        return Caps(generation, daily, self.global_daily_cap, Decimal(str(row.budget["max_cost"])))

    def spent(self, conn: Connection, ctx: Ctx, at: datetime) -> dict[str, Decimal]:
        day = datetime.combine(at.date(), time(0), tzinfo=at.tzinfo)
        row = conn.execute(
            text(
                "SELECT coalesce(sum(cost_cny) FILTER (WHERE generation_id = :g), 0) AS gen, "
                "coalesce(sum(cost_cny) FILTER (WHERE program_id = :p AND at >= :d0 "
                "AND at < :d1), 0) AS prog_day, "
                "coalesce(sum(cost_cny) FILTER (WHERE at >= :d0 AND at < :d1), 0) AS day, "
                "coalesce(sum(cost_cny) FILTER (WHERE job_id = :j), 0) AS job "
                "FROM budget_ledger WHERE (at >= :d0 AND at < :d1) OR job_id = :j"
            ),
            {
                "g": ctx.generation_id,
                "p": ctx.program_id,
                "j": ctx.job_id,
                "d0": day,
                "d1": day + timedelta(days=1),
            },
        ).one()
        return {
            "generation": Decimal(row.gen),
            "program_daily": Decimal(row.prog_day),
            "global_daily": Decimal(row.day),
            "job": Decimal(row.job),
        }

    def remaining(self, conn: Connection, ctx: Ctx, at: datetime) -> Remaining:
        caps, spent = self.caps(conn, ctx), self.spent(conn, ctx, at)
        options: list[Remaining] = [
            Remaining("job", caps.job - spent["job"], spent["job"], caps.job),
            Remaining(
                "daily",
                caps.global_daily - spent["global_daily"],
                spent["global_daily"],
                caps.global_daily,
            ),
            Remaining(
                "daily",
                caps.program_daily - spent["program_daily"],
                spent["program_daily"],
                caps.program_daily,
            ),
        ]
        if ctx.generation_id is not None:
            options.append(
                Remaining(
                    "generation",
                    caps.generation - spent["generation"],
                    spent["generation"],
                    caps.generation,
                )
            )
        return min(options, key=lambda r: r.amount)

    def admit(
        self,
        conn: Connection,
        ctx: Ctx,
        at: datetime,
        quote: PriceQuote,
        prompt_tokens: int,
        max_tokens: int,
        request_bound_tokens: int,
    ) -> int:
        """Check the estimate; return the run's total-token limit under the remainder.

        A run is stopped by PydanticAI once its tokens pass the limit, which can happen
        one request late, so the limit leaves room for one request of at most
        request_bound_tokens at the dearest rate.
        """
        left = self.remaining(conn, ctx, at)
        estimate = quote.estimate(prompt_tokens, max_tokens)
        dearest = max(quote.in_miss, quote.out, quote.cache_write)
        if estimate > left.amount or dearest <= 0:
            if dearest <= 0 and estimate <= left.amount:
                return 10**12
            raise BudgetExceeded(left.scope, left.spent, left.cap, estimate)
        limit = int(left.amount * MILLION / dearest) - request_bound_tokens
        if limit < prompt_tokens + max_tokens:
            raise BudgetExceeded(left.scope, left.spent, left.cap, estimate)
        return limit

    def record(
        self,
        conn: Connection,
        ctx: Ctx,
        at: datetime,
        *,
        run_id: UUID,
        role: str,
        quote: PriceQuote,
        usage: TokenUsage,
    ) -> Decimal:
        cost = quote.cost(usage)
        conn.execute(
            text(
                "INSERT INTO budget_ledger (entry_id, at, job_id, program_id, generation_id, "
                "task_id, run_id, role, provider, model, tokens_in, tokens_out, tokens_cached, "
                "price_period, cost_cny) VALUES (:e, :at, :j, :p, :g, :t, :r, :role, :prov, :m, "
                ":ti, :to, :tc, :pp, :c)"
            ),
            {
                "e": uuid7(),
                "at": at,
                "j": ctx.job_id,
                "p": ctx.program_id,
                "g": ctx.generation_id,
                "t": ctx.task_id,
                "r": run_id,
                "role": role,
                "prov": quote.ref.provider,
                "m": quote.ref.model_id,
                "ti": usage.input_tokens,
                "to": usage.output_tokens,
                "tc": usage.cache_read_tokens,
                "pp": quote.period,
                "c": cost,
            },
        )
        if ctx.job_id is not None:
            conn.execute(
                text("UPDATE research_jobs SET cost_cny = cost_cny + :c WHERE job_id = :j"),
                {"c": cost, "j": ctx.job_id},
            )
        if ctx.generation_id is not None:
            conn.execute(
                text("UPDATE generations SET cost_cny = cost_cny + :c WHERE generation_id = :g"),
                {"c": cost, "g": ctx.generation_id},
            )
        return cost

    def exhausted(self, conn: Connection, ctx: Ctx, at: datetime) -> Scope | None:
        left = self.remaining(conn, ctx, at)
        return left.scope if left.amount <= 0 else None
