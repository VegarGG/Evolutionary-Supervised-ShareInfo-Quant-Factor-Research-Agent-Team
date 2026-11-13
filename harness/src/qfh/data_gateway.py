"""One active data vendor per run, with durable query caps and exact-result reuse."""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
import sqlite3
import sys
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from qfh.evidence import EvidenceStore, Query, canonical
from qfh.ricequant import DataUnavailable, RiceQuantTools

IFIND_BASE = "https://quantapi.51ifind.com/api/v1/"


class DataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["ifind", "rqdata", "baostock"]
    kind: Literal["bars", "announcements", "report_summaries", "news", "read"]
    run_id: str = Field(min_length=1, max_length=200)
    query: Query | None = None
    credentials: dict[str, str] = Field(default_factory=dict)
    fiscal_year: str | None = None
    evidence_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    offset: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=20, ge=1, le=20, strict=True)

    @model_validator(mode="after")
    def required_arguments(self):
        if self.kind == "read" and self.evidence_id is None:
            raise ValueError("read requires an evidence id")
        if self.provider == "baostock" and self.credentials:
            raise ValueError("BaoStock uses anonymous access only")
        if self.kind != "read" and (
            self.query is None or (self.provider != "baostock" and not self.credentials)
        ):
            raise ValueError("source fetch requires a query and stored credential")
        return self


class DataAllowance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_business_requests: int = Field(ge=0)
    max_auth_requests: int = Field(ge=0)
    max_estimated_cells: int = Field(ge=1)
    max_calendar_days: int | None = Field(default=None, ge=1, le=61)
    max_symbols: int | None = Field(default=None, ge=1, le=5)


class DataPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_business_requests: int = Field(ge=0)
    max_auth_requests: int = Field(ge=0)
    max_calendar_days: int = Field(ge=1, le=61)
    max_symbols: int = Field(ge=1, le=5)
    max_estimated_cells: int = Field(ge=1)
    max_response_bytes: int = Field(ge=1024)
    timeout_seconds: int = Field(ge=1, le=60)
    allowed_kinds: list[str]
    research_cutoff: datetime
    provider_allowances: dict[Literal["ifind", "rqdata", "baostock"], DataAllowance] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_cutoff(self):
        if self.research_cutoff.tzinfo is None:
            raise ValueError("research cutoff must include a timezone")
        if set(self.allowed_kinds) - {"bars", "announcements", "report_summaries", "news"}:
            raise ValueError("unsupported operation in data policy")
        return self


class DataGuard:
    def __init__(self, path: Path, policy: DataPolicy):
        self.path, self.policy = path, policy
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, provider TEXT)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS evidence_grants ("
                "run_id TEXT, evidence_id TEXT, PRIMARY KEY(run_id,evidence_id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS requests ("
                "id INTEGER PRIMARY KEY, cache_key TEXT, provider TEXT, kind TEXT, "
                "estimated_cells INTEGER, at TEXT, result_id TEXT, outcome TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS policy_history ("
                "sha256 TEXT PRIMARY KEY, at TEXT NOT NULL, body TEXT NOT NULL)"
            )
            body = policy.model_dump_json()
            db.execute(
                "INSERT OR IGNORE INTO policy_history VALUES (?,?,?)",
                (hashlib.sha256(body.encode()).hexdigest(), datetime.now(UTC).isoformat(), body),
            )

    @contextlib.contextmanager
    def db(self):
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

    def pin(self, run_id: str, provider: str):
        if provider not in ("ifind", "rqdata", "baostock"):
            raise ValueError("select exactly one supported data provider")
        with self.db() as db:
            row = db.execute("SELECT provider FROM runs WHERE id=?", (run_id,)).fetchone()
            if row and row[0] != provider:
                raise ValueError("this run is pinned to another data source")
            db.execute("INSERT OR IGNORE INTO runs VALUES (?,?)", (run_id, provider))

    def reserve(
        self, key: str, provider: str, kind: str, cells: int
    ) -> tuple[int | None, str | None]:
        with self.db() as db:
            prior = db.execute(
                "SELECT result_id FROM requests WHERE cache_key=?", (key,)
            ).fetchone()
            if prior:
                if prior[0]:
                    return None, prior[0]
                raise DataUnavailable(
                    "previous request has no verified result; no automatic replay"
                )
            auth = kind == "auth"
            count = db.execute(
                "SELECT COUNT(*) FROM requests WHERE provider=? AND (kind='auth')=?",
                (provider, auth),
            ).fetchone()[0]
            allowance = self.policy.provider_allowances.get(provider, self.policy)
            limit = allowance.max_auth_requests if auth else allowance.max_business_requests
            used = db.execute(
                "SELECT COALESCE(SUM(estimated_cells),0) FROM requests WHERE provider=?",
                (provider,),
            ).fetchone()[0]
            if count >= limit or used + cells > allowance.max_estimated_cells:
                raise DataUnavailable("local data allowance exhausted; no provider request sent")
            cursor = db.execute(
                "INSERT INTO requests "
                "(cache_key,provider,kind,estimated_cells,at,outcome) VALUES (?,?,?,?,?,?)",
                (key, provider, kind, cells, datetime.now(UTC).isoformat(), "reserved"),
            )
            return cursor.lastrowid, None

    def record(self, request_id: int, outcome: str, result_id: str | None = None):
        with self.db() as db:
            db.execute(
                "UPDATE requests SET outcome=?,result_id=? WHERE id=? AND outcome='reserved'",
                (outcome, result_id, request_id),
            )

    def grant(self, run_id: str, evidence_id: str):
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO evidence_grants VALUES (?,?)", (run_id, evidence_id))

    def can_read(self, run_id: str, evidence_id: str) -> bool:
        with self.db() as db:
            return (
                db.execute(
                    "SELECT 1 FROM evidence_grants WHERE run_id=? AND evidence_id=?",
                    (run_id, evidence_id),
                ).fetchone()
                is not None
            )


class IfindClient:
    """Small HTTP adapter based on ORS's verified protocol, without token rotation/retries."""

    def __init__(self, credentials: dict, guard: DataGuard, client=None):
        self.credentials, self.guard = credentials, guard
        self.client = client

    def _post(self, endpoint: str, payload: dict, headers: dict) -> dict:
        if endpoint not in {"get_access_token", "cmd_history_quotation", "report_query"}:
            raise ValueError("iFind endpoint not allowed")
        client = self.client or httpx.Client(
            timeout=self.guard.policy.timeout_seconds, trust_env=False, follow_redirects=False
        )
        try:
            with client.stream(
                "POST",
                IFIND_BASE + endpoint,
                json=payload,
                headers={"Content-Type": "application/json", "ifindlang": "cn", **headers},
            ) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > self.guard.policy.max_response_bytes:
                        raise DataUnavailable("iFind response exceeds local byte limit")
            body = json.loads(content)
            if not isinstance(body, dict):
                raise DataUnavailable("iFind response must be an object")
            code = body.get("errorcode")
            if type(code) is not int or code != 0:
                # Provider errmsg can echo request data; expose codes only.
                safe_code = code if type(code) is int else "invalid"
                raise DataUnavailable(
                    f"iFind business error {safe_code}; no automatic retry or rotation"
                )
            return body
        except (httpx.HTTPError, ValueError) as exc:
            raise DataUnavailable(f"iFind {type(exc).__name__}; outcome retained") from None
        finally:
            if self.client is None:
                client.close()

    def token(self) -> str:
        if self.credentials.get("access_token"):
            return self.credentials["access_token"]
        refresh = self.credentials.get("refresh_token")
        if not refresh:
            raise DataUnavailable("enter iFind credentials through DSH Settings")
        key = "auth:" + hashlib.sha256(refresh.encode()).hexdigest()
        request_id, _ = self.guard.reserve(key, "ifind", "auth", 0)
        try:
            body = self._post("get_access_token", {}, {"refresh_token": refresh})
            token = body.get("data", {}).get("access_token")
            if not isinstance(token, str) or not token:
                raise DataUnavailable("iFind token response invalid")
            self.guard.record(request_id, "success")
            return token
        except Exception:
            self.guard.record(request_id, "failed_or_unknown")
            raise

    def daily_close(self, query: Query) -> tuple[list[dict], int | None]:
        code = query.symbols[0].replace(".XSHE", ".SZ").replace(".XSHG", ".SH")
        body = self._post(
            "cmd_history_quotation",
            {
                "codes": code,
                "indicators": "close",
                "startdate": query.start.isoformat(),
                "enddate": query.end.isoformat(),
                "functionpara": {"CPS": "no", "Fill": "Blank"},
            },
            {"access_token": self.token()},
        )
        tables = body.get("tables")
        if not isinstance(tables, list) or len(tables) != 1 or tables[0].get("thscode") != code:
            raise DataUnavailable("iFind quote response does not identify the requested stock")
        times, values = tables[0].get("time"), (tables[0].get("table") or {}).get("close")
        if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
            raise DataUnavailable("iFind time/value arrays differ")
        rows = []
        seen = set()
        for raw_day, value in zip(times, values, strict=True):
            day = date.fromisoformat(str(raw_day)[:10])
            if day in seen or not query.start <= day <= query.end:
                raise DataUnavailable("iFind duplicate or out-of-range date")
            seen.add(day)
            if value is not None:
                try:
                    number = Decimal(str(value))
                    if not number.is_finite() or number <= 0:
                        raise InvalidOperation
                    value = float(number)
                except (InvalidOperation, ValueError, OverflowError):
                    raise DataUnavailable("iFind close must be finite and positive") from None
            rows.append({"symbol": query.symbols[0], "date": day.isoformat(), "close": value})
        volume = body.get("dataVol", body.get("dataCount"))
        return rows, volume if type(volume) is int and volume >= 0 else None


def evidence_page(
    store: EvidenceStore, evidence_id: str, cutoff: datetime, offset: int = 0, limit: int = 20
) -> dict:
    if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 20:
        raise ValueError("evidence pagination requires offset >= 0 and limit 1..20")
    record = store.get(evidence_id)
    if record.get("research_cutoff") != cutoff.isoformat():
        raise ValueError("evidence belongs to another research cutoff")
    content = record.pop("content")
    return {
        **record,
        "evidence_id": evidence_id,
        "row_count": len(content),
        "content": content[offset : offset + limit],
    }


def dispatch(
    request: dict,
    policy: DataPolicy,
    root: Path,
    ifind_client=None,
    rq_client=None,
    baostock_fetch=None,
    cache_only=False,
) -> dict:
    try:
        request = DataRequest.model_validate(request).model_dump(exclude_none=True)
    except ValidationError:
        # ValidationError text can include raw credential values; never forward it.
        raise ValueError("invalid data request shape") from None
    provider, kind = request["provider"], request["kind"]
    guard = DataGuard(root / "data-usage.sqlite3", policy)
    guard.pin(request["run_id"], provider)
    store = EvidenceStore(root / "evidence")
    if kind == "read":
        evidence_id = request["evidence_id"]
        if not guard.can_read(request["run_id"], evidence_id):
            raise DataUnavailable("evidence has not been granted to this session")
        return evidence_page(
            store,
            evidence_id,
            policy.research_cutoff,
            request.get("offset", 0),
            request.get("limit", 20),
        )
    credentials = request["credentials"]
    query = Query.model_validate(request["query"])
    days = (query.end - query.start).days + 1
    allowance = policy.provider_allowances.get(provider)
    max_days = (allowance.max_calendar_days if allowance else None) or policy.max_calendar_days
    max_symbols = (allowance.max_symbols if allowance else None) or policy.max_symbols
    if days > max_days or len(query.symbols) > max_symbols:
        raise ValueError("query exceeds configured symbol/date allowance")
    if kind not in policy.allowed_kinds:
        raise ValueError("source operation is not enabled in this bounded pilot")
    if (
        datetime.fromisoformat(query.end.isoformat() + "T23:59:59.999999+08:00")
        > policy.research_cutoff
    ):
        raise ValueError("query exceeds research cutoff")
    if provider in ("ifind", "baostock") and (kind != "bars" or len(query.symbols) != 1):
        raise DataUnavailable(f"{provider} pilot supports one-stock daily close only")
    if provider != "baostock" and (not isinstance(credentials, dict) or not credentials):
        raise DataUnavailable("enter credentials through DSH Settings")
    key = hashlib.sha256(
        canonical(
            {
                "provider": provider,
                "kind": kind,
                "query": query.model_dump(mode="json"),
                "cutoff": policy.research_cutoff.isoformat(),
                "account": hashlib.sha256(canonical(credentials)).hexdigest(),
                "adapter": "qfh-baostock/3" if provider == "baostock" else "qfh-data/1",
                "fiscal_year": request.get("fiscal_year"),
            }
        )
    ).hexdigest()
    request_id, cached = guard.reserve(key, provider, kind, days * len(query.symbols))
    if cached:
        result = evidence_page(store, cached, policy.research_cutoff)
        guard.grant(request["run_id"], cached)
        return {**result, "cache_reused": True}
    try:
        if cache_only:
            raise DataUnavailable(
                "offline smoke requires preloaded evidence; provider access disabled"
            )
        if provider in ("ifind", "baostock"):
            metadata = {}
            if provider == "ifind":
                rows, volume = IfindClient(credentials, guard, ifind_client).daily_close(query)
                metadata["reported_data_volume"] = volume
            else:
                from qfh.baostock_source import daily_close

                rows, transport = (baostock_fetch or daily_close)(query, policy, guard, key)
                metadata["transport"] = transport
            record = {
                "provider": provider,
                "kind": kind,
                "query": query.model_dump(mode="json"),
                "retrieved_at": datetime.now(UTC).isoformat(),
                "content": rows,
                "research_cutoff": policy.research_cutoff.isoformat(),
                "adjustment": "none",
                **metadata,
                "timing_limit": "Current download of historical daily data; not a vintage archive.",
            }
            evidence_id = store.put(record)
        else:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                rq = rq_client or importlib.import_module("rqdatac")
                if rq_client is None:
                    auth_key = "rq-auth:" + hashlib.sha256(canonical(credentials)).hexdigest()
                    auth_id, _ = guard.reserve(auth_key, "rqdata", "auth", 0)
                    try:
                        rq.init("license", credentials["license"])
                        guard.record(auth_id, "success")
                    except Exception as exc:
                        guard.record(auth_id, "failed_or_unknown")
                        raise DataUnavailable(
                            f"RQData authentication: {type(exc).__name__}"
                        ) from None
                    if kind == "news":
                        importlib.import_module("rqdatac_news")
                source = RiceQuantTools(rq, store, policy.research_cutoff, price_fields=["close"])
                result = source.fetch(kind, query, request.get("fiscal_year"))
            evidence_id = result["evidence_id"]
        guard.record(request_id, "success", evidence_id)
        guard.grant(request["run_id"], evidence_id)
        return {**evidence_page(store, evidence_id, policy.research_cutoff), "cache_reused": False}
    except Exception:
        guard.record(request_id, "failed_or_unknown")
        raise


def main():
    # Native DSH plugin sends credentials on stdin, never argv, config or model tools.
    import argparse

    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        request = json.loads(sys.stdin.readline(65536))
        policy = DataPolicy.model_validate(yaml.safe_load(args.policy.read_text()))
        result = dispatch(request, policy, args.root)
        print(json.dumps({"ok": True, "result": result}))
    except (DataUnavailable, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__}))


if __name__ == "__main__":
    main()
