"""Atomic reservations shared by every request in a local experiment campaign."""

from __future__ import annotations

import hashlib
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
            db.execute(
                "CREATE TABLE IF NOT EXISTS step_grants ("
                "step TEXT PRIMARY KEY, group_id TEXT NOT NULL, max_requests INTEGER NOT NULL, "
                "group_max_requests INTEGER NOT NULL, authority TEXT NOT NULL, at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS billing_baselines ("
                "id INTEGER PRIMARY KEY, at TEXT NOT NULL, actual INTEGER NOT NULL, "
                "covered_calls TEXT NOT NULL, calls_sha256 TEXT NOT NULL, authority TEXT NOT NULL)"
            )
            for table in ("step_grants", "billing_baselines"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} "
                        f"BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'budget authority is append only'); END"
                    )
            saved = db.execute("SELECT body FROM config WHERE id=1").fetchone()
            body = policy.model_dump_json()
            if saved and saved[0] != body:
                raise ValueError("budget policy changed; explicit reconciliation required")
            db.execute("INSERT OR IGNORE INTO config VALUES (1, ?)", (body,))

    def reconcile_official_total(self, actual: int, expected_calls_sha256: str, authority: str):
        """Record an owner-reported official cumulative bill, keeping every old call.

        All current calls must have known usage. The caller freezes the covered-id
        digest first, so an intervening dispatch cannot be silently folded in.
        Reconciliation includes the historical carry; it is not an extra budget.
        """
        if actual < 0 or not authority.strip():
            raise ValueError("invalid official billing baseline")
        with self.transaction() as db:
            rows = db.execute("SELECT id,charged FROM calls ORDER BY id").fetchall()
            if any(row[1] is None for row in rows):
                raise ValueError("reconcile unknown charges before recording an official baseline")
            covered = json.dumps([r[0] for r in rows], separators=(",", ":"))
            digest = hashlib.sha256(covered.encode()).hexdigest()
            if digest != expected_calls_sha256:
                raise ValueError("call history changed since billing observation")
            prior = db.execute(
                "SELECT actual,calls_sha256,authority FROM billing_baselines "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if prior == (actual, digest, authority):
                return
            db.execute(
                "INSERT INTO billing_baselines (at,actual,covered_calls,calls_sha256,authority) "
                "VALUES (?,?,?,?,?)",
                (datetime.now(UTC).isoformat(), actual, covered, digest, authority),
            )

    def _effective_total(self, db) -> int:
        baseline = db.execute(
            "SELECT actual,covered_calls FROM billing_baselines ORDER BY id DESC LIMIT 1"
        ).fetchone()
        covered = set(json.loads(baseline[1])) if baseline else set()
        return (baseline[0] if baseline else self.policy.carry_micro_cny) + sum(
            charged if charged is not None else reserved
            for ident, charged, reserved in db.execute("SELECT id,charged,reserved FROM calls")
            if ident not in covered
        )

    def grant_step(
        self, step: str, group_id: str, max_requests: int, group_max_requests: int, authority: str
    ) -> None:
        """An explicit, immutable host grant for a bounded tool conversation.

        This does not modify the saved policy, original cap, carry, prices or any
        call. Old ungranted diagnostic steps retain their one-request allowance.
        The host calls this before a new step's first wire request, never a model.
        """
        if not (
            step and group_id and authority.strip() and 1 <= max_requests <= group_max_requests
        ):
            raise ValueError("invalid conversation grant")
        expected = (group_id, max_requests, group_max_requests, authority)
        with self.transaction() as db:
            saved = db.execute(
                "SELECT group_id,max_requests,group_max_requests,authority "
                "FROM step_grants WHERE step=?",
                (step,),
            ).fetchone()
            if saved:
                if saved != expected:
                    raise ValueError("conversation grant is immutable")
                return
            if db.execute("SELECT 1 FROM calls WHERE step=?", (step,)).fetchone():
                raise ValueError("cannot expand an already used step")
            other = db.execute(
                "SELECT group_max_requests FROM step_grants WHERE group_id=?", (group_id,)
            ).fetchone()
            if other and other[0] != group_max_requests:
                raise ValueError("inconsistent group allowance")
            db.execute(
                "INSERT INTO step_grants VALUES (?,?,?,?,?,?)",
                (step, *expected, datetime.now(UTC).isoformat()),
            )

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
        self._reserve(request_id, step, now, self.policy.reservation)

    def _reserve(
        self, request_id, step, now, reservation, *, detail=None, check=None, package_allowance=None
    ):
        """Shared atomic cash/concurrency/request checks for trusted funding adapters."""
        package = self.policy.package_micro_cny if package_allowance is None else package_allowance
        if (
            type(package) is not int
            or not self.policy.package_micro_cny <= package <= self.policy.total_micro_cny
        ):
            raise ValueError("package amendment must stay within the original cumulative ceiling")
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
            grant = db.execute(
                "SELECT group_id,max_requests,group_max_requests FROM step_grants WHERE step=?",
                (step,),
            ).fetchone()
            limit = grant[1] if grant else self.policy.max_requests_per_step
            if count >= limit:
                raise BudgetRefused("step request allowance exhausted, including retries")
            if grant:
                group_count = db.execute(
                    "SELECT COUNT(*) FROM calls c JOIN step_grants g ON c.step=g.step "
                    "WHERE g.group_id=?",
                    (grant[0],),
                ).fetchone()[0]
                if group_count >= grant[2]:
                    raise BudgetRefused("research trial request allowance exhausted")
                if db.execute(
                    "SELECT 1 FROM calls c JOIN step_grants g ON c.step=g.step "
                    "WHERE g.group_id=? AND c.state='unknown'",
                    (grant[0],),
                ).fetchone():
                    raise BudgetRefused(
                        "research trial has an unknown charge; reconcile before continuing"
                    )
            if check:
                check(db)
            new = spent + reservation
            if new > package:
                raise BudgetRefused("work-package budget exhausted or reserved")
            if self._effective_total(db) + reservation > self.policy.total_micro_cny:
                raise BudgetRefused("original cumulative budget exhausted or reserved")
            db.execute(
                "INSERT INTO calls (id,step,started,state,reserved,detail) VALUES (?,?,?,?,?,?)",
                (request_id, step, now.isoformat(), "pending", reservation, detail),
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
            baseline_row = db.execute(
                "SELECT * FROM billing_baselines ORDER BY id DESC LIMIT 1"
            ).fetchone()
            baseline = dict(baseline_row) if baseline_row else None
            effective = self._effective_total(db)
        settled = sum(c["charged"] or 0 for c in calls)
        reserved = sum(c["reserved"] for c in calls if c["charged"] is None)
        return {
            "carry_micro_cny": self.policy.carry_micro_cny,
            "new_settled_micro_cny": settled,
            "unresolved_micro_cny": reserved,
            "cumulative_micro_cny": effective - reserved,
            "conservative_unreconciled_cumulative_micro_cny": self.policy.carry_micro_cny + settled,
            "remaining_unreserved_micro_cny": self.policy.total_micro_cny - effective,
            "invoice_verified": False,
            "billing_baseline": {k: v for k, v in baseline.items() if k != "covered_calls"}
            if baseline
            else None,
            "calls": [
                {**c, "usage": json.loads(c["usage"]) if c["usage"] else None} for c in calls
            ],
        }
