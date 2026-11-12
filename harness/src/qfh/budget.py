"""Atomic reservations shared by every request in a local experiment campaign."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field


class BudgetRefused(RuntimeError):
    """Admission failed before a provider request was dispatched."""


class BudgetPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    total_micro_cny: int = Field(gt=0)
    carry_micro_cny: int = Field(ge=0)
    carry_requests: int = Field(ge=0)
    carry_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_micro_cny: int = Field(gt=0)
    input_micro_cny_per_token: int = Field(gt=0)
    output_micro_cny_per_token: int = Field(gt=0)
    provider_context_tokens: int = Field(gt=0)
    provider_max_output_tokens: int = Field(gt=0)
    concurrency: int = Field(ge=1, le=500)
    max_requests_per_step: int = Field(ge=1)

    @property
    def reservation(self) -> int:
        # Reserve provider maxima, not the requested cap: compatibility layers
        # can raise max_tokens. This also covers every unreported completion.
        return (
            self.provider_context_tokens * self.input_micro_cny_per_token
            + self.provider_max_output_tokens * self.output_micro_cny_per_token
        )


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    input_uncached: int = Field(ge=0)
    input_cached: int = Field(ge=0)
    input_cache_write: int = Field(ge=0)
    output: int = Field(ge=0)

    @property
    def input_total(self) -> int:
        return self.input_uncached + self.input_cached + self.input_cache_write


def admission_open(now: datetime) -> bool:
    """Owner-authorized windows, deliberately narrower than weekend tariff hours."""
    if now.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    hour = now.astimezone(ZoneInfo("Asia/Shanghai")).hour
    return 12 <= hour < 14 or 18 <= hour < 24


class Ledger:
    """One host-owned SQLite ledger; never share its files across host/VM kernels."""

    def __init__(self, path: Path, policy: BudgetPolicy):
        self.path, self.policy = path, policy
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, body TEXT)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS calls ("
                "id TEXT PRIMARY KEY, step TEXT NOT NULL, started TEXT NOT NULL, "
                "finished TEXT, state TEXT NOT NULL, reserved INTEGER NOT NULL, "
                "charged INTEGER, usage TEXT, detail TEXT)"
            )
            saved = db.execute("SELECT body FROM config WHERE id=1").fetchone()
            body = policy.model_dump_json()
            if saved and saved[0] != body:
                raise ValueError("budget policy changed; explicit reconciliation required")
            db.execute("INSERT OR IGNORE INTO config VALUES (1, ?)", (body,))

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def reserve(self, request_id: str, step: str, now: datetime) -> None:
        if not admission_open(now):
            raise BudgetRefused("outside authorized Beijing admission window")
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM calls WHERE id=?", (request_id,)).fetchone():
                raise BudgetRefused("request id already used; never redispatch")
            spent, pending = db.execute(
                "SELECT COALESCE(SUM(COALESCE(charged,reserved)),0), "
                "COALESCE(SUM(state='pending'),0) FROM calls"
            ).fetchone()
            count = db.execute("SELECT COUNT(*) FROM calls WHERE step=?", (step,)).fetchone()[0]
            if pending >= self.policy.concurrency:
                raise BudgetRefused("concurrency limit")
            if count >= self.policy.max_requests_per_step:
                raise BudgetRefused("step request allowance exhausted, including retries")
            new = spent + self.policy.reservation
            if new > self.policy.package_micro_cny:
                raise BudgetRefused("work-package budget exhausted or reserved")
            if new + self.policy.carry_micro_cny > self.policy.total_micro_cny:
                raise BudgetRefused("original cumulative budget exhausted or reserved")
            db.execute(
                "INSERT INTO calls (id,step,started,state,reserved) VALUES (?,?,?,?,?)",
                (request_id, step, now.isoformat(), "pending", self.policy.reservation),
            )

    def unknown(self, request_id: str, reason: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE calls SET state='unknown',detail=?,finished=? "
                "WHERE id=? AND state='pending'",
                (reason, datetime.now(UTC).isoformat(), request_id),
            )

    def settle(self, request_id: str, usage: Usage) -> None:
        charge = (
            usage.input_total * self.policy.input_micro_cny_per_token
            + usage.output * self.policy.output_micro_cny_per_token
        )
        body = usage.model_dump_json()
        with self.transaction() as db:
            row = db.execute(
                "SELECT usage,reserved FROM calls WHERE id=?", (request_id,)
            ).fetchone()
            if row is None:
                raise ValueError("settlement without reservation")
            if row[0] is not None:
                if row[0] != body:
                    raise ValueError("conflicting settlement")
                return
            if charge > row[1]:
                raise ValueError("provider usage exceeds reserved maxima; retain reservation")
            db.execute(
                "UPDATE calls SET state='settled',charged=?,usage=?,finished=? WHERE id=?",
                (charge, body, datetime.now(UTC).isoformat(), request_id),
            )

    def snapshot(self) -> dict:
        with self.transaction() as db:
            db.row_factory = sqlite3.Row
            calls = [dict(row) for row in db.execute("SELECT * FROM calls ORDER BY started")]
        settled = sum(c["charged"] or 0 for c in calls)
        reserved = sum(c["reserved"] for c in calls if c["charged"] is None)
        return {
            "carry_micro_cny": self.policy.carry_micro_cny,
            "new_settled_micro_cny": settled,
            "unresolved_micro_cny": reserved,
            "cumulative_micro_cny": self.policy.carry_micro_cny + settled,
            "remaining_unreserved_micro_cny": self.policy.total_micro_cny
            - self.policy.carry_micro_cny
            - settled
            - reserved,
            "invoice_verified": False,
            "calls": [
                {**c, "usage": json.loads(c["usage"]) if c["usage"] else None} for c in calls
            ],
        }
