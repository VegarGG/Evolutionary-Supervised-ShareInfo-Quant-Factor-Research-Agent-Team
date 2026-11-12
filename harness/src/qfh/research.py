"""Bounded research admission, roles and trace; DSH owns every model/tool loop.

No evaluator, publication, account or arbitrary code execution capability exists
here. Draft validation checks provenance and completeness, never investment merit.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import sqlite3
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from qfh.budget import BudgetPolicy, BudgetRefused, Ledger, admission_open
from qfh.data_gateway import DataGuard, DataPolicy, dispatch
from qfh.evidence import EvidenceStore, Query, canonical

Role = Literal["supervisor", "researcher", "reviewer"]
WorkerRole = Literal["researcher", "reviewer"]


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Literal["deepseek"]
    model: str
    reasoning_effort: Literal["low", "high", "max"]


class ResearchPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    budget_config: str
    data_config: str
    max_trials: int = Field(ge=1, le=10)
    max_requests_per_trial: int = Field(ge=1, le=100)
    role_request_limits: dict[Role, int]
    roles: dict[Role, Route]
    max_output_tokens: int = Field(ge=1)
    max_task_chars: int = Field(ge=1)
    max_tool_result_chars: int = Field(ge=1)
    sample_seconds: float = Field(gt=0)
    request_timeout_seconds: int = Field(ge=1)
    max_body_bytes: int = Field(ge=1)
    allowed_provider: Literal["baostock"]
    query: Query
    descriptive_lookbacks: list[int]
    authority: str = Field(min_length=20)

    @model_validator(mode="after")
    def validate_roles(self):
        names = {"supervisor", "researcher", "reviewer"}
        if set(self.roles) != names or set(self.role_request_limits) != names:
            raise ValueError("one supervisor and exactly two worker roles required")
        if any(
            not 1 <= n <= self.max_requests_per_trial for n in self.role_request_limits.values()
        ):
            raise ValueError("invalid role request limit")
        if len({r.model for r in self.roles.values()}) != 1:
            raise ValueError("mixed-model routing remains a later work package")
        if any(n < 1 for n in self.descriptive_lookbacks):
            raise ValueError("lookbacks must be positive")
        return self


class WorkerReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=10, max_length=8000)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)
    findings: list[str] = Field(min_length=1, max_length=8)
    proposed_formula: str | None = None
    recommended_changes: list[str] = Field(max_length=8)
    limitations: list[str] = Field(min_length=1, max_length=8)


def parse_worker_report(result, max_chars):
    """Accept one JSON object, optionally fenced, without repairing its contents."""
    if result.get("stopReason") != "completed":
        raise ValueError("worker did not complete normally")
    text = "".join(b.get("text", "") for b in result.get("output", []) if b.get("type") == "text")
    if len(text) > max_chars:
        raise ValueError("worker report exceeds the configured result limit")
    text = text.strip()
    encoding = "bare_json"
    if text.startswith("```"):
        match = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", text, re.DOTALL)
        if match is None:
            raise ValueError("expected one JSON fence without surrounding prose")
        text, encoding = match[1], "json_fence"
    return WorkerReport.model_validate_json(text), encoding


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker: WorkerRole
    adopted: bool
    reason: str = Field(min_length=10, max_length=4000)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=200)
    hypothesis: str = Field(min_length=10, max_length=8000)
    formula: str = Field(min_length=3, max_length=4000)
    signal_time: Literal["close_t"]
    execution_time: Literal["next_trading_day_close"]
    evidence_ids: list[str] = Field(min_length=1, max_length=8)
    decisions: list[Decision] = Field(min_length=2, max_length=2)
    limitations: list[str] = Field(min_length=1, max_length=12)
    next_steps: list[str] = Field(min_length=1, max_length=8)


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["scope", "data", "metrics", "begin_worker", "finish_worker", "draft"]
    session_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,200}$")
    selected_provider: Literal["baostock", "ifind", "rqdata"] = "baostock"
    args: dict = Field(default_factory=dict)


class Research:
    def __init__(self, config: Path, private: Path):
        self.config_path = config
        self.policy = ResearchPolicy.model_validate(yaml.safe_load(config.read_text()))
        self.private = private
        self.root = private / "research"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "research.sqlite3"
        budget = yaml.safe_load((config.parent / self.policy.budget_config).read_text())
        if any(route.model != budget["model"] for route in self.policy.roles.values()):
            raise ValueError(
                "role model differs from the priced and authorized budget configuration"
            )
        self.ledger = Ledger(
            private / "campaign/spend.sqlite3", BudgetPolicy.model_validate(budget["budget"])
        )
        self.data_policy = DataPolicy.model_validate(
            yaml.safe_load((config.parent / self.policy.data_config).read_text())
        )
        self.data_root = private / "data"
        self.data = DataGuard(self.data_root / "data-usage.sqlite3", self.data_policy)
        self.store = EvidenceStore(self.data_root / "evidence")
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY, body TEXT)")
            body = self.policy.model_dump_json()
            saved = db.execute("SELECT body FROM policy WHERE id=1").fetchone()
            if saved and saved[0] != body:
                raise ValueError("research policy changed; explicit reconciliation required")
            db.execute("INSERT OR IGNORE INTO policy VALUES (1,?)", (body,))
            db.execute(
                "CREATE TABLE IF NOT EXISTS trials "
                "(id TEXT PRIMARY KEY, at TEXT, provider TEXT, draft TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS members (session_id TEXT PRIMARY KEY, trial_id TEXT, "
                "role TEXT, state TEXT, task TEXT, result TEXT, UNIQUE(trial_id,role))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS events "
                "(seq INTEGER PRIMARY KEY, at TEXT, beijing TEXT, "
                "principal TEXT, kind TEXT, body TEXT)"
            )
            for action in ("UPDATE", "DELETE"):
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS events_no_{action.lower()} BEFORE {action} "
                    "ON events BEGIN SELECT RAISE(ABORT,'research events are append only'); END"
                )

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def event(db, principal, kind, body):
        now = datetime.now(UTC)
        db.execute(
            "INSERT INTO events (at,beijing,principal,kind,body) VALUES (?,?,?,?,?)",
            (
                now.isoformat(),
                now.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
                principal,
                kind,
                json.dumps(body, ensure_ascii=False, sort_keys=True),
            ),
        )

    def admit(self, session_id: str) -> str:
        if not admission_open(datetime.now(UTC)):
            raise BudgetRefused(
                "outside authorized Beijing admission window; resume in a permitted window"
            )
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", session_id):
            raise BudgetRefused("DSH request must identify its owning session")
        with self.db() as db:
            member = db.execute(
                "SELECT * FROM members WHERE session_id=?", (session_id,)
            ).fetchone()
            if member is None:
                if (
                    db.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
                    >= self.policy.max_trials
                ):
                    raise BudgetRefused(
                        "small trial allowance exhausted; do not reset campaign state"
                    )
                db.execute(
                    "INSERT INTO trials (id,at) VALUES (?,?)",
                    (session_id, datetime.now(UTC).isoformat()),
                )
                db.execute(
                    "INSERT INTO members VALUES (?,?,?,'active',NULL,NULL)",
                    (session_id, session_id, "supervisor"),
                )
                self.event(
                    db,
                    session_id,
                    "trial_started",
                    {
                        "policy_sha256": hashlib.sha256(
                            self.policy.model_dump_json().encode()
                        ).hexdigest(),
                        "roles": self.policy.model_dump()["roles"],
                    },
                )
                member = db.execute(
                    "SELECT * FROM members WHERE session_id=?", (session_id,)
                ).fetchone()
            if member["state"] in ("completed", "failed"):
                raise BudgetRefused("worker already finished; no paid replay")
            step = f"research:{member['trial_id']}:{member['role']}"
            self.ledger.grant_step(
                step,
                member["trial_id"],
                self.policy.role_request_limits[member["role"]],
                self.policy.max_requests_per_trial,
                self.policy.authority,
            )
        return step

    def member(self, session_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM members WHERE session_id=?", (session_id,)).fetchone()
            if not row:
                raise ValueError("research session has not been admitted")
            return dict(row)

    def scope(self, session_id, selected_provider="baostock"):
        member = self.member(session_id)
        with self.db() as db:
            trial = db.execute("SELECT * FROM trials WHERE id=?", (member["trial_id"],)).fetchone()
            provider = trial["provider"] or selected_provider
            if provider != self.policy.allowed_provider:
                raise ValueError(
                    "this small interactive trial permits BaoStock only; select it in Research data"
                )
            if trial["provider"] is None:
                db.execute("UPDATE trials SET provider=? WHERE id=?", (provider, trial["id"]))
                self.event(db, session_id, "source_pinned", {"provider": provider})
            workers = [
                dict(r)
                for r in db.execute(
                    "SELECT session_id,role,state FROM members "
                    "WHERE trial_id=? AND role!='supervisor'",
                    (trial["id"],),
                )
            ]
        self.data.pin(session_id, provider)
        snapshot = self.ledger.snapshot()
        return {
            "trial_id": trial["id"],
            "role": member["role"],
            "provider": provider,
            "query": self.policy.query.model_dump(mode="json"),
            "workers": workers,
            "draft_recorded": trial["draft"] is not None,
            "window_open": admission_open(datetime.now(UTC)),
            "admission_windows_beijing": ["12:00-14:00", "18:00-24:00"],
            "remaining_cny": snapshot["remaining_unreserved_micro_cny"] / 1_000_000,
            "usage_basis": "owner-reported official baseline + conservative subsequent estimates",
            "max_requests_per_trial": self.policy.max_requests_per_trial,
            "scope_limit": "Historical unadjusted closes; not a vintage archive. "
            "No current context, backtest, evaluation, publication, reports or news in this trial.",
            "worker_output_schema": WorkerReport.model_json_schema(),
            "draft_schema": Draft.model_json_schema(),
        }

    def check_citations(self, session_id, ids):
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("unique, granted evidence ids required")
        for ident in ids:
            if not self.data.can_read(session_id, ident):
                raise ValueError("citation was not granted to this agent")
            self.store.get(ident)  # Verify content hash, not just row membership.

    def begin_worker(self, session_id, role, task):
        member = self.member(session_id)
        if member["role"] != "supervisor" or role not in ("researcher", "reviewer"):
            raise ValueError(
                "only the supervisor can start the two named workers; no recursive delegation"
            )
        if not isinstance(task, str) or not 10 <= len(task) <= self.policy.max_task_chars:
            raise ValueError("worker task length outside policy")
        scope = self.scope(session_id)
        if scope["draft_recorded"]:
            raise ValueError("this trial already has an immutable draft; start a new small trial")
        child_id = "qfh-" + uuid.uuid4().hex
        with self.db() as db:
            if db.execute(
                "SELECT 1 FROM members WHERE trial_id=? AND role=?", (member["trial_id"], role)
            ).fetchone():
                raise ValueError(
                    "worker already started; inspect its result, never replay automatically"
                )
            db.execute(
                "INSERT INTO members VALUES (?,?,?,'active',?,NULL)",
                (child_id, member["trial_id"], role, task),
            )
            self.event(
                db, session_id, "worker_started", {"role": role, "child_id": child_id, "task": task}
            )
        self.data.pin(child_id, scope["provider"])
        prompt = {
            "role": role,
            "task": task,
            "scope": {k: scope[k] for k in ("provider", "query", "scope_limit")},
            "instruction": "Use market_daily_bars to inspect the allowed real evidence yourself. "
            "Use research_metrics for arithmetic. Return ONLY one JSON object matching the schema. "
            "Separate observations from hypotheses; disclose sample limits; cite evidence ids. "
            "Do not delegate or submit a draft. No claims of alpha or gate passage.",
            "required_output_schema": WorkerReport.model_json_schema(),
        }
        return {
            "child_id": child_id,
            "role": role,
            "prompt": json.dumps(prompt, ensure_ascii=False),
            "route": self.policy.roles[role].model_dump(),
        }

    def finish_worker(self, session_id, child_id, result):
        parent, child = self.member(session_id), self.member(child_id)
        if (
            parent["role"] != "supervisor"
            or parent["trial_id"] != child["trial_id"]
            or child["role"] == "supervisor"
        ):
            raise ValueError("worker does not belong to this supervisor")
        if child["state"] != "active":
            raise ValueError("worker settlement already recorded")
        report, error, encoding = None, None, None
        try:
            report, encoding = parse_worker_report(result, self.policy.max_tool_result_chars)
            self.check_citations(child_id, report.evidence_ids)
        except (ValueError, TypeError) as exc:
            error = type(exc).__name__
        with self.db() as db:
            updated = db.execute(
                "UPDATE members SET state=?,result=? WHERE session_id=? AND state='active'",
                (
                    "failed" if error else "completed",
                    json.dumps(result, ensure_ascii=False),
                    child_id,
                ),
            )
            if updated.rowcount != 1:
                raise ValueError("worker settlement already recorded")
            self.event(
                db,
                session_id,
                "worker_finished",
                {
                    "child_id": child_id,
                    "role": child["role"],
                    "result": result,
                    "report_format": encoding,
                    "validation_error": error,
                },
            )
        if error:
            with self.db() as db:
                operations = Counter(
                    body["op"]
                    + (":" + body["args"].get("kind", "") if body["op"] == "data" else "")
                    for row in db.execute(
                        "SELECT body FROM events WHERE principal=? AND kind='tool_result'",
                        (child_id,),
                    )
                    for body in [json.loads(row["body"])]
                )
            raise ValueError(
                "worker report failed validation; raw result retained and no automatic replay. "
                "Completed worker operations: "
                + json.dumps(dict(operations), sort_keys=True)
                + ". Report rejection does not mean no data or arithmetic was performed."
            )
        for ident in report.evidence_ids:
            self.data.grant(session_id, ident)
        return {"contribution_id": child_id, "role": child["role"], "report": report.model_dump()}

    def record_draft(self, session_id, body):
        member = self.member(session_id)
        if member["role"] != "supervisor":
            raise ValueError("only the supervisor records a research draft")
        draft = Draft.model_validate(body)
        if {d.worker for d in draft.decisions} != {"researcher", "reviewer"}:
            raise ValueError("record an adoption/rejection decision for each worker")
        self.check_citations(session_id, draft.evidence_ids)
        with self.db() as db:
            workers = list(
                db.execute(
                    "SELECT role,state FROM members WHERE trial_id=? AND role!='supervisor'",
                    (member["trial_id"],),
                )
            )
            if len(workers) != 2 or any(w["state"] != "completed" for w in workers):
                raise ValueError("both workers must complete with valid, cited reports")
            if db.execute("SELECT draft FROM trials WHERE id=?", (member["trial_id"],)).fetchone()[
                0
            ]:
                raise ValueError("draft is immutable; start a new trial to revise")
            canonical_draft = draft.model_dump(mode="json")
            digest = hashlib.sha256(canonical(canonical_draft)).hexdigest()
            db.execute(
                "UPDATE trials SET draft=? WHERE id=?",
                (json.dumps(canonical_draft), member["trial_id"]),
            )
            self.event(
                db,
                session_id,
                "draft_recorded",
                {
                    "sha256": digest,
                    "draft": canonical_draft,
                    "validation": "provenance/schema only; no evaluation or publication",
                },
            )
        return {
            "status": "draft_recorded",
            "draft_sha256": digest,
            "draft": canonical_draft,
            "evaluation": "not run",
            "publication": "not published",
        }

    def metrics(self, session_id, evidence_id):
        self.check_citations(session_id, [evidence_id])
        record = self.store.get(evidence_id)
        if record.get("query") != self.policy.query.model_dump(mode="json"):
            raise ValueError("evidence lies outside this trial's permitted sample")
        rows = sorted(record["content"], key=lambda r: r["date"])
        prices = [Decimal(str(r["close"])) for r in rows]
        if len(prices) < 2:
            raise ValueError("at least two observations required")
        return {
            "evidence_id": evidence_id,
            "observations": len(rows),
            "first_date": rows[0]["date"],
            "last_date": rows[-1]["date"],
            "unadjusted_sample_return": str(prices[-1] / prices[0] - 1),
            "last_n_observation_returns": {
                str(n): str(prices[-1] / prices[-n - 1] - 1)
                for n in self.policy.descriptive_lookbacks
                if n < len(prices)
            },
            "minimum_close": str(min(prices)),
            "maximum_close": str(max(prices)),
            "interpretation": "Descriptive arithmetic only, no strategy backtest or gate metric.",
        }

    def operate(self, request: Operation):
        args = request.args
        try:
            scope = self.scope(request.session_id, request.selected_provider)
            if request.op == "scope":
                result = scope
            elif request.op == "begin_worker":
                result = self.begin_worker(request.session_id, args["role"], args["task"])
            elif request.op == "finish_worker":
                result = self.finish_worker(request.session_id, args["child_id"], args["result"])
            elif request.op == "draft":
                result = self.record_draft(request.session_id, args)
            elif request.op == "metrics":
                result = self.metrics(request.session_id, args["evidence_id"])
            else:
                kind = args.get("kind")
                if kind not in ("bars", "read"):
                    raise ValueError("only daily closes and granted evidence reads are enabled")
                if kind == "bars" and Query.model_validate(args["query"]) != self.policy.query:
                    raise ValueError(
                        "query must match the single permitted stock/date sample in research_scope"
                    )
                data_request = {
                    **args,
                    "provider": scope["provider"],
                    "run_id": request.session_id,
                    "credentials": {},
                }
                result = dispatch(
                    data_request,
                    self.data_policy,
                    self.data_root,
                    cache_only=(self.private / "OFFLINE_ONLY").exists(),
                )
            if len(json.dumps(result, ensure_ascii=False)) > self.policy.max_tool_result_chars:
                raise ValueError("tool result exceeds the configured result limit")
            with self.db() as db:
                self.event(
                    db,
                    request.session_id,
                    "tool_result",
                    {"op": request.op, "args": args, "result": result},
                )
            return result
        except Exception as exc:
            with self.db() as db:
                self.event(
                    db,
                    request.session_id,
                    "tool_failure",
                    {
                        "op": request.op,
                        "args": args,
                        "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                    },
                )
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--private", type=Path, required=True)
    args = parser.parse_args()
    try:
        request = Operation.model_validate_json(sys.stdin.readline(262144))
        result = Research(args.config, args.private).operate(request)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except (ValueError, BudgetRefused) as exc:
        # No credentials are accepted by this BaoStock-only research surface.
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__}))


if __name__ == "__main__":
    main()
