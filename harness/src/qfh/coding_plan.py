"""Bounded prepaid GLM usage in the existing campaign ledger; no metered fallback."""

import hashlib
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
        native = store["refs"].get("ZAI_CODING_CN_API_KEY")
        if native is not None:
            if (
                not isinstance(native, str)
                or not native.strip()
                or any(c in native for c in "\r\n")
            ):
                raise ValueError()
            return native.strip()
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
            "Save a valid Zhipu Coding Plan key in DSH Models; "
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
    endpoint: Literal[
        "https://open.bigmodel.cn/api/anthropic/v1/messages",
        "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions",
    ]
    transport: Literal["anthropic", "openai-completions"] = "anthropic"
    authority: str = Field(min_length=20)
    eligibility_authority: str = Field(min_length=20)
    starts_at: datetime
    ends_at: datetime
    max_requests: int = Field(ge=1, le=100)
    max_microcredits: int = Field(gt=0)
    # Operator route amendment only; the original saved budget policy is immutable.
    cash_package_micro_cny: int | None = Field(default=None, gt=0)
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
        if (self.transport == "openai-completions") != self.endpoint.endswith("chat/completions"):
            raise ValueError("transport must match the approved Coding Plan endpoint")
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
        if coding.cash_package_micro_cny is not None and not (
            self.policy.package_micro_cny
            <= coding.cash_package_micro_cny
            <= self.policy.total_micro_cny
        ):
            raise ValueError("package amendment must stay within the original cumulative ceiling")

    def reserve(self, request_id, step, now, *, output_tokens=None):
        policy = self.coding
        output = policy.maximum_output_tokens if output_tokens is None else output_tokens
        if type(output) is not int or not 0 < output <= policy.maximum_output_tokens:
            raise BudgetRefused("invalid requested output bound")
        cash_reservation = (
            policy.maximum_input_tokens * self.policy.input_micro_cny_per_token
            + output * self.policy.output_micro_cny_per_token
        )
        quota_reservation = (
            policy.maximum_input_tokens * policy.input_microcredits_per_token
            + output * policy.output_microcredits_per_token
        )
        if not policy.admission_open(now):
            raise BudgetRefused("outside the authorized GLM Coding Plan window")
        detail = {
            "funding": policy.funding,
            "route_id": policy.id,
            "model": policy.model,
            "endpoint": policy.endpoint,
            "quota_reserved_microcredits": quota_reservation,
            "maximum_output_tokens": output,
            "quota_settled_upper_microcredits": None,
            "cache_tokens_reported": None,
            "cash_package_micro_cny": policy.cash_package_micro_cny
            if policy.cash_package_micro_cny is not None
            else self.policy.package_micro_cny,
            "cash_basis": "Existing Coding Plan subscription; no metered fallback. "
            "The shared cash ledger still debits its conservative exposure allowance, "
            "not an assertion of incremental billing or allocated subscription purchase cost.",
        }

        def check(db):
            rows = db.execute("SELECT detail,state FROM calls").fetchall()
            own = [(coding_detail({"detail": d}), state) for d, state in rows]
            # Protocol repairs must not reset the original subscription allowance.
            own = [(d, s) for d, s in own if d.get("funding") == "coding_plan"]
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
            if used + quota_reservation > policy.max_microcredits:
                raise BudgetRefused("GLM subscription quota allowance exhausted or reserved")

        self._reserve(
            request_id,
            step,
            now,
            cash_reservation,
            detail=json.dumps(detail),
            check=check,
            package_allowance=policy.cash_package_micro_cny,
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
            row = db.execute(
                "SELECT usage,detail,reserved FROM calls WHERE id=?", (request_id,)
            ).fetchone()
            if row is None:
                raise ValueError("subscription settlement without reservation")
            detail = coding_detail({"detail": row[1]})
            if (
                usage.output
                > detail.get("maximum_output_tokens", self.coding.maximum_output_tokens)
                or cash_upper > row[2]
            ):
                raise ValueError("usage exceeds the request reservation")
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

    def review_auth_rejection(self, wire, *, authority):
        """Operator-only review of a complete 401; retain BOTH full reservations.

        A reviewed authentication rejection permits a separately granted repair
        attempt, but is never represented as settled usage or zero cost. Timeouts,
        partial streams and other failures remain blocking unknowns.
        """
        if len(authority.strip()) < 20:
            raise ValueError("explicit repair authority is required")
        raw = {
            name: (wire / name).read_bytes()
            for name in ("http.json", "request.json", "response.sse")
        }
        http = json.loads(raw["http.json"])
        response = json.loads(raw["response.sse"])
        if (
            http.get("status") != 401
            or http.get("endpoint") != self.coding.endpoint
            or http.get("request_sha256") != hashlib.sha256(raw["request.json"]).hexdigest()
            or set(response) != {"error"}
            or response["error"].get("type") != "401"
        ):
            raise ValueError("not a complete recorded authentication rejection")
        with self.transaction() as db:
            row = db.execute(
                "SELECT state,step,usage,charged,detail FROM calls WHERE id=?", (wire.name,)
            ).fetchone()
            if row is None or row[0] != "unknown" or row[1] != http.get("step"):
                raise ValueError("review requires the matching unknown request")
            detail = coding_detail({"detail": row[4]})
            if row[2] is not None or row[3] is not None or detail.get("route_id") != self.coding.id:
                raise ValueError("review cannot change settled usage or another route")
            detail["authentication_review"] = {
                "at": datetime.now(UTC).isoformat(),
                "authority": authority,
                "evidence_sha256": {
                    name: hashlib.sha256(value).hexdigest() for name, value in raw.items()
                },
                "previous_state": "unknown",
                "billing_status": "unverified; full cash and subscription reservations retained",
            }
            db.execute(
                "UPDATE calls SET state='rejected_reserved',detail=? "
                "WHERE id=? AND state='unknown'",
                (json.dumps(detail), wire.name),
            )
