"""Bounded prepaid GLM usage in the existing campaign ledger; no metered fallback."""

import json
from datetime import UTC, datetime
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from qfh.budget import BudgetRefused, Ledger, Usage


def read_coding_credential(private):
    """Operator-only read of the exact native DSH reference; never use env fallbacks."""
    path = private / "research-ui-home/.credentials.yaml"
    try:
        if path.stat().st_mode & 0o077:
            raise ValueError()
        store = yaml.safe_load(path.read_text())
        if store["version"] != 1:
            raise ValueError()
        raw = store["refs"]["QFH_GLM_CODING_CREDENTIAL"]
        credential = json.loads(raw)
        if (
            credential["platform"] != "bigmodel-cn"
            or credential["plan"] != "coding"
            or credential["model"] != "glm-5.3-flash"
            or not isinstance(credential["api_key"], str)
            or not credential["api_key"].strip()
            or any(c in credential["api_key"] for c in "\r\n")
        ):
            raise ValueError()
        return credential["api_key"].strip()
    except Exception:
        raise ValueError(
            "Save a valid Zhipu Coding Plan key in DSH Research models; "
            "the credential file must be owner-only"
        ) from None


class CodingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    provider: Literal["glm_coding"]
    funding: Literal["coding_plan"]
    platform: Literal["bigmodel-cn"]
    subscription_tier: Literal["Pro"]
    model: Literal["glm-5.3-flash"]
    endpoint: Literal["https://open.bigmodel.cn/api/anthropic/v1/messages"]
    authority: str = Field(min_length=20)
    eligibility_authority: str = Field(min_length=20)
    starts_at: datetime
    ends_at: datetime
    max_requests: int = Field(ge=1, le=100)
    max_microcredits: int = Field(gt=0)
    input_microcredits_per_token: int = Field(gt=0)
    output_microcredits_per_token: int = Field(gt=0)
    maximum_input_tokens: int = Field(gt=0)
    maximum_output_tokens: int = Field(gt=0)
    concurrency: Literal[1]
    pricing_source: str
    pricing_verified_on: str
    reasoning_effort: Literal["low", "high", "max"]

    @model_validator(mode="after")
    def bounded_window(self):
        if not self.starts_at.tzinfo or not self.ends_at.tzinfo or self.ends_at <= self.starts_at:
            raise ValueError("a finite timezone-aware subscription admission window is required")
        if self.reservation > self.max_microcredits:
            raise ValueError("subscription allowance cannot cover one reserved request")
        return self

    @property
    def reservation(self):
        return (
            self.maximum_input_tokens * self.input_microcredits_per_token
            + self.maximum_output_tokens * self.output_microcredits_per_token
        )

    def admission_open(self, now):
        return now.tzinfo is not None and self.starts_at <= now < self.ends_at


def coding_detail(call):
    try:
        value = json.loads(call.get("detail") or "null")
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) and value.get("funding") == "coding_plan" else {}


def parse_coding_usage(events):
    """Anthropic-compatible cumulative usage; absent cache counters stay unreported."""
    values, final, complete = {}, False, False
    for event in events:
        if event.get("type") == "message_start":
            values.update(event["message"].get("usage", {}))
        elif event.get("type") == "message_delta":
            values.update(event.get("usage", {}))
            final = "output_tokens" in event.get("usage", {})
        elif event.get("type") == "message_stop":
            complete = True
    if not complete or not final or "input_tokens" not in values:
        raise ValueError("incomplete subscription usage; quota reservation retained")
    if values.get("server_tool_use"):
        raise ValueError("unapproved provider tool usage")
    known = all(k in values for k in ("cache_read_input_tokens", "cache_creation_input_tokens"))
    return (
        Usage(
            input_uncached=values["input_tokens"],
            input_cached=values.get("cache_read_input_tokens", 0),
            input_cache_write=values.get("cache_creation_input_tokens", 0),
            output=values["output_tokens"],
        ),
        {"cache_tokens_reported": known, "usage_semantics": "Anthropic Messages compatible"},
    )


class CodingLedger(Ledger):
    """Same cash ledger/tables/history; subscription quota is retained in call detail."""

    def __init__(self, cash_ledger, coding):
        self.path, self.policy, self.coding = cash_ledger.path, cash_ledger.policy, coding
        if (
            coding.maximum_input_tokens > self.policy.provider_context_tokens
            or coding.maximum_output_tokens > self.policy.provider_max_output_tokens
        ):
            raise ValueError("GLM token maxima exceed the shared cash reservation bounds")

    def reserve(self, request_id, step, now):
        policy = self.coding
        if not policy.admission_open(now):
            raise BudgetRefused("outside the authorized GLM Coding Plan window")
        detail = {
            "funding": policy.funding,
            "route_id": policy.id,
            "model": policy.model,
            "endpoint": policy.endpoint,
            "quota_reserved_microcredits": policy.reservation,
            "quota_settled_upper_microcredits": None,
            "cache_tokens_reported": None,
            "cash_basis": "Existing Coding Plan subscription; no metered fallback. "
            "The shared cash ledger still debits its conservative exposure allowance, "
            "not an assertion of incremental billing or allocated subscription purchase cost.",
        }

        def check(db):
            rows = db.execute("SELECT detail,state FROM calls").fetchall()
            own = [(coding_detail({"detail": d}), state) for d, state in rows]
            own = [(d, s) for d, s in own if d.get("route_id") == policy.id]
            if len(own) >= policy.max_requests:
                raise BudgetRefused("GLM route request allowance exhausted")
            if any(s == "unknown" for _, s in own):
                raise BudgetRefused("GLM usage is unknown; inspect before continuing")
            if sum(s == "pending" for _, s in own) >= policy.concurrency:
                raise BudgetRefused("GLM concurrency limit")
            used = sum(
                d["quota_settled_upper_microcredits"]
                if d["quota_settled_upper_microcredits"] is not None
                else d["quota_reserved_microcredits"]
                for d, _ in own
            )
            if used + policy.reservation > policy.max_microcredits:
                raise BudgetRefused("GLM subscription quota allowance exhausted or reserved")

        self._reserve(
            request_id, step, now, self.policy.reservation, detail=json.dumps(detail), check=check
        )

    def settle(self, request_id, usage, *, metadata=None):
        if (
            usage.input_total > self.coding.maximum_input_tokens
            or usage.output > self.coding.maximum_output_tokens
        ):
            raise ValueError("subscription usage exceeds reserved token maxima")
        upper = (
            usage.input_total * self.coding.input_microcredits_per_token
            + usage.output * self.coding.output_microcredits_per_token
        )
        cash_upper = (
            usage.input_total * self.policy.input_micro_cny_per_token
            + usage.output * self.policy.output_micro_cny_per_token
        )
        with self.transaction() as db:
            row = db.execute("SELECT usage,detail FROM calls WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise ValueError("subscription settlement without reservation")
            detail = coding_detail({"detail": row[1]})
            if detail.get("route_id") != self.coding.id:
                raise ValueError("subscription route differs from reservation")
            body = usage.model_dump_json()
            if row[0] is not None:
                if row[0] != body:
                    raise ValueError("conflicting subscription settlement")
                return
            if upper > detail["quota_reserved_microcredits"]:
                raise ValueError("subscription usage exceeds quota reservation")
            detail.update(metadata or {})
            detail["quota_settled_upper_microcredits"] = upper
            db.execute(
                "UPDATE calls SET state='settled',charged=?,usage=?,detail=?,finished=? WHERE id=?",
                (cash_upper, body, json.dumps(detail), datetime.now(UTC).isoformat(), request_id),
            )

    def unknown(self, request_id, reason):
        with self.transaction() as db:
            row = db.execute("SELECT detail FROM calls WHERE id=?", (request_id,)).fetchone()
            detail = coding_detail({"detail": row[0]}) if row else {}
            if detail.get("route_id") != self.coding.id:
                raise ValueError("unknown subscription reservation")
            detail["error_type"] = reason
            db.execute(
                "UPDATE calls SET state='unknown',detail=?,finished=? "
                "WHERE id=? AND state='pending'",
                (json.dumps(detail), datetime.now(UTC).isoformat(), request_id),
            )
