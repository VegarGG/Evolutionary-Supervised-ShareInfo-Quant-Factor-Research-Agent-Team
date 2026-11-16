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


class ReservedConnectionTimeout(BaseModel):
    """Operator-authorized fresh experiment; never settlement of the old call."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    call_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    groups: list[str] = Field(min_length=1, max_length=2)
    authority: str = Field(min_length=20)

    @model_validator(mode="after")
    def unique_groups(self):
        if len(set(self.groups)) != len(self.groups) or any(not g for g in self.groups):
            raise ValueError("fresh experiment groups must be nonempty and unique")
        return self


def call_fingerprint(call):
    return hashlib.sha256(
        json.dumps(call, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class CodingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    provider: Literal["glm_coding"]
    funding: Literal["coding_plan"]
    platform: Literal["bigmodel-cn"]
    subscription_tier: Literal["Pro"]
    model: Literal["glm-5.3-flash", "glm-5.3"]
    endpoint: Literal[
        "https://open.bigmodel.cn/api/anthropic/v1/messages",
        "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions",
    ]
    transport: Literal["anthropic", "openai-completions"] = "anthropic"
    authority: str = Field(min_length=20)
    eligibility_authority: str = Field(min_length=20)
    starts_at: datetime
    ends_at: datetime | None
    admission_mode: Literal["window", "until_stopped"] = "window"
    # A finite operator work-package cap, checked against ALL historical GLM calls.
    # A route amendment may extend a pilot; it cannot reset usage or cash/credit limits.
    max_requests: int = Field(ge=1, le=1000)
    max_microcredits: int = Field(gt=0)
    # Operator route amendment only; the original saved budget policy is immutable.
    cash_package_micro_cny: int | None = Field(default=None, gt=0)
    cash_input_micro_cny_per_token: int | None = Field(default=None, gt=0)
    cash_output_micro_cny_per_token: int | None = Field(default=None, gt=0)
    input_microcredits_per_token: int = Field(gt=0)
    output_microcredits_per_token: int = Field(gt=0)
    maximum_input_tokens: int = Field(gt=0)
    maximum_output_tokens: int = Field(gt=0)
    concurrency: Literal[1]
    pricing_source: str
    pricing_verified_on: str
    reasoning_effort: Literal["low", "high", "max"]
    reserved_connection_timeouts: list[ReservedConnectionTimeout] = Field(
        default_factory=list, max_length=1
    )

    @model_validator(mode="after")
    def bounded_window(self):
        if self.model == "glm-5.3" and (
            self.cash_input_micro_cny_per_token is None
            or self.cash_output_micro_cny_per_token is None
        ):
            raise ValueError("GLM 5.3 requires an explicit model-specific cash exposure policy")
        if (self.transport == "openai-completions") != self.endpoint.endswith("chat/completions"):
            raise ValueError("transport must match the approved Coding Plan endpoint")
        if not self.starts_at.tzinfo:
            raise ValueError("timezone-aware subscription start is required")
        if self.admission_mode == "window":
            if self.ends_at is None or not self.ends_at.tzinfo or self.ends_at <= self.starts_at:
                raise ValueError(
                    "a finite timezone-aware subscription admission window is required"
                )
        elif self.ends_at is not None:
            raise ValueError("until_stopped admission must not carry a clock expiry")
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
        return (
            now.tzinfo is not None
            and self.starts_at <= now
            and (self.ends_at is None or now < self.ends_at)
        )


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

    @property
    def cash_input_rate(self):
        return self.coding.cash_input_micro_cny_per_token or self.policy.input_micro_cny_per_token

    @property
    def cash_output_rate(self):
        return self.coding.cash_output_micro_cny_per_token or self.policy.output_micro_cny_per_token

    def verify_reserved_timeout(self, call):
        """Keep the exact unknown row and both reserves; check pre-HTTP evidence."""
        matches = [
            item
            for item in self.coding.reserved_connection_timeouts
            if item.request_id == call["id"]
        ]
        if len(matches) != 1 or call_fingerprint(call) != matches[0].call_sha256:
            raise BudgetRefused("unknown usage has no matching owner retry authority")
        item = matches[0]
        detail = coding_detail(call)
        wire = self.path.parent / "wire" / call["id"]
        if (
            call["state"] != "unknown"
            or call["finished"] is None
            or call["usage"] is not None
            or call["charged"] is not None
            or call["reserved"] <= 0
            or detail.get("error_type") != "ConnectTimeout"
            or detail.get("model") != self.coding.model
            or detail.get("endpoint") != self.coding.endpoint
            or detail.get("quota_settled_upper_microcredits") is not None
            or detail.get("quota_reserved_microcredits", 0) <= 0
            or not wire.is_dir()
            or {p.name for p in wire.iterdir()} != {"request.json"}
        ):
            raise BudgetRefused("owner retry requires a fully reserved pre-HTTP connection timeout")
        raw = (wire / "request.json").read_bytes()
        if (
            hashlib.sha256(raw).hexdigest() != item.request_sha256
            or json.loads(raw).get("model") != self.coding.model
        ):
            raise BudgetRefused("reserved timeout request evidence changed")
        return item

    def reserve(self, request_id, step, now, *, output_tokens=None):
        policy = self.coding
        output = policy.maximum_output_tokens if output_tokens is None else output_tokens
        if type(output) is not int or not 0 < output <= policy.maximum_output_tokens:
            raise BudgetRefused("invalid requested output bound")
        cash_reservation = (
            policy.maximum_input_tokens * self.cash_input_rate + output * self.cash_output_rate
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
            "cash_input_micro_cny_per_token": self.cash_input_rate,
            "cash_output_micro_cny_per_token": self.cash_output_rate,
            "carried_unknown_ids": [
                item.request_id for item in policy.reserved_connection_timeouts
            ],
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
            group = db.execute("SELECT group_id FROM step_grants WHERE step=?", (step,)).fetchone()
            if policy.reserved_connection_timeouts and (
                not group
                or any(group[0] not in item.groups for item in policy.reserved_connection_timeouts)
            ):
                raise BudgetRefused("owner retry is restricted to the named fresh experiments")
            cursor = db.execute("SELECT * FROM calls WHERE state='unknown'")
            names = [column[0] for column in cursor.description]
            for row in cursor.fetchall():
                call = dict(zip(names, row, strict=True))
                if call["usage"] is not None:
                    call["usage"] = json.loads(call["usage"])
                item = self.verify_reserved_timeout(call)
                old = db.execute(
                    "SELECT group_id FROM step_grants WHERE step=?", (call["step"],)
                ).fetchone()
                if not group or group[0] not in item.groups or old and old[0] == group[0]:
                    raise BudgetRefused("unknown request cannot be replayed in its old experiment")
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
            provider="glm_coding",
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
        cash_upper = usage.input_total * self.cash_input_rate + usage.output * self.cash_output_rate
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
