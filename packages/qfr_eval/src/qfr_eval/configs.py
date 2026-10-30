"""Evaluator configuration state: protocol, policy and quota versions, the epoch, the
data snapshots and the public cards (PLAN Sections 8.2, 9.3, 9.6 and 16.3).

Versions are created as drafts and become immutable once active (the database refuses
any content change). Activation retires the previous active version in the same
transaction. The epoch pins its windows, its embargo check and its full snapshot at
activation; window dates are never inferred from the wall clock during a run.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml
from pydantic import BaseModel, JsonValue
from qfr_core.cards import card_sha256, policy_card, protocol_card, quota_card
from qfr_core.config import (
    CONFIG_FILES,
    EpochConfig,
    PolicyConfig,
    ProtocolConfig,
    QuotaConfig,
    canonical_json,
)
from qfr_core.data.snapshot import SnapshotError, current_snapshot, read_snapshot
from qfr_core.ids import uuid7
from sqlalchemy import text
from sqlalchemy.engine import Connection

ConfigKind = Literal["protocol", "policy", "quotas"]
TABLES: dict[ConfigKind, str] = {
    "protocol": "protocols",
    "policy": "release_policies",
    "quotas": "quotas",
}
MODELS: dict[ConfigKind, type[BaseModel]] = {
    "protocol": ProtocolConfig,
    "policy": PolicyConfig,
    "quotas": QuotaConfig,
}
ID_FIELDS: dict[ConfigKind, str] = {
    "protocol": "protocol_id",
    "policy": "policy_id",
    "quotas": "quota_id",
}
WINDOWS = ("W0", "W1", "W2", "W3")


class EvalError(Exception):
    """A refused evaluator operation with a stable code (admin API answers 4xx)."""

    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(f"{code}: {message}")
        self.status, self.code, self.message, self.details = status, code, message, details


@dataclass(frozen=True)
class ConfigVersion:
    kind: ConfigKind
    id: str
    version: str
    config: dict[str, Any]
    sha256: str
    status: str

    @property
    def ref(self) -> str:
        return f"{self.id}/{self.version}"


@dataclass(frozen=True)
class Window:
    start: date
    end: date


@dataclass(frozen=True)
class ActiveEpoch:
    epoch_id: str
    version: str
    windows: dict[str, Window]
    snapshot_id: str
    embargo_check: dict[str, Any]


@dataclass(frozen=True)
class ActiveState:
    protocol: ConfigVersion
    policy: ConfigVersion
    quotas: ConfigVersion
    epoch: ActiveEpoch

    @property
    def protocol_card_ref(self) -> str:
        return self.protocol.ref

    @property
    def policy_ref(self) -> str:
        return self.policy.ref


def parse_config(kind: ConfigKind, raw_text: str) -> tuple[dict[str, Any], str]:
    """Validate a YAML version; returns the config and the SHA-256 of its canonical JSON."""
    try:
        raw = yaml.safe_load(raw_text)
    except yaml.YAMLError as error:
        raise EvalError(400, "CONFIG_INVALID", f"not YAML: {type(error).__name__}") from None
    if not isinstance(raw, dict):
        raise EvalError(400, "CONFIG_INVALID", "configuration must be a mapping")
    try:
        # A JSON round trip rejects unquoted YAML dates and other non-JSON values.
        config = json.loads(canonical_json(raw))
        MODELS[kind].model_validate(config)
    except (TypeError, ValueError) as error:
        raise EvalError(400, "CONFIG_INVALID", str(error).splitlines()[0]) from None
    return config, hashlib.sha256(canonical_json(config).encode()).hexdigest()


def _event(
    conn: Connection,
    at: datetime,
    principal: str,
    action: str,
    entity_type: str,
    entity_id: str,
    request_id: str,
    payload: dict[str, JsonValue],
) -> None:
    conn.execute(
        text(
            "INSERT INTO eval.events (event_id, at, principal, action, entity_type, entity_id, "
            "request_id, payload) VALUES (:id, :at, :p, :a, :t, :e, :r, CAST(:payload AS jsonb))"
        ),
        {
            "id": uuid7(),
            "at": at,
            "p": principal,
            "a": action,
            "t": entity_type,
            "e": entity_id,
            "r": request_id,
            "payload": canonical_json(payload),
        },
    )


record_event = _event


def create_version(
    conn: Connection,
    kind: ConfigKind,
    raw_text: str,
    principal: str,
    request_id: str,
    at: datetime,
) -> tuple[ConfigVersion, bool]:
    """Insert a draft; an identical repeat is idempotent, a changed one is refused."""
    config, sha = parse_config(kind, raw_text)
    config_id, version = str(config[ID_FIELDS[kind]]), str(config["version"])
    table = TABLES[kind]
    existing = conn.execute(
        text(f"SELECT sha256, status FROM eval.{table} WHERE id = :id AND version = :v"),
        {"id": config_id, "v": version},
    ).first()
    if existing is not None:
        if existing.sha256 != sha:
            raise EvalError(
                409,
                "VERSION_IMMUTABLE",
                f"{kind} {config_id}/{version} exists with different content; "
                "publish a new version",
            )
        return ConfigVersion(kind, config_id, version, config, sha, existing.status), False
    conn.execute(
        text(
            f"INSERT INTO eval.{table} (id, version, yaml, config, sha256, status, created_at, "
            "created_by, request_id) VALUES (:id, :v, :yaml, CAST(:config AS jsonb), :sha, "
            "'draft', :at, :by, :r)"
        ),
        {
            "id": config_id,
            "v": version,
            "yaml": raw_text,
            "config": canonical_json(config),
            "sha": sha,
            "at": at,
            "by": principal,
            "r": request_id,
        },
    )
    _event(
        conn, at, principal, "config_created", table, f"{config_id}/{version}", request_id,
        {"sha256": sha},
    )  # fmt: skip
    return ConfigVersion(kind, config_id, version, config, sha, "draft"), True


def _card_rows(conn: Connection, kind: ConfigKind, version: ConfigVersion, at: datetime) -> None:
    builders = {"protocol": protocol_card, "policy": policy_card, "quotas": quota_card}
    card = builders[kind](version.config)
    conn.execute(
        text(
            "INSERT INTO eval.public_cards (kind, id, version, ref, sha256, content, created_at) "
            "VALUES (:k, :id, :v, :ref, :sha, CAST(:c AS jsonb), :at) ON CONFLICT DO NOTHING"
        ),
        {
            "k": kind,
            "id": version.id,
            "v": version.version,
            "ref": version.ref,
            "sha": card_sha256(card),
            "c": canonical_json(card),
            "at": at,
        },
    )


def activate_version(
    conn: Connection,
    kind: ConfigKind,
    config_id: str,
    version: str,
    principal: str,
    approval_id: UUID | None,
    request_id: str,
    at: datetime,
) -> ConfigVersion:
    table = TABLES[kind]
    row = conn.execute(
        text(
            f"SELECT id, version, config, sha256, status FROM eval.{table} "
            "WHERE id = :id AND version = :v FOR UPDATE"
        ),
        {"id": config_id, "v": version},
    ).first()
    if row is None:
        raise EvalError(404, "VERSION_NOT_FOUND", f"no {kind} {config_id}/{version}")
    target = ConfigVersion(kind, row.id, row.version, dict(row.config), row.sha256, row.status)
    if row.status == "active":
        return target
    if row.status == "retired":
        raise EvalError(409, "VERSION_RETIRED", f"{kind} {config_id}/{version} was retired")
    if kind == "protocol":
        supported = set(target.config.get("supported_kinds", []))
        if not {"factor"} <= supported:
            raise EvalError(400, "CONFIG_INVALID", "the protocol must support factors")
    previous = conn.execute(
        text(f"SELECT id, version FROM eval.{table} WHERE status = 'active' FOR UPDATE")
    ).first()
    if previous is not None:
        conn.execute(
            text(
                f"UPDATE eval.{table} SET status = 'retired', retired_at = :at "
                "WHERE id = :id AND version = :v"
            ),
            {"at": at, "id": previous.id, "v": previous.version},
        )
    conn.execute(
        text(
            f"UPDATE eval.{table} SET status = 'active', activated_at = :at, activated_by = :by, "
            "approval_id = :approval WHERE id = :id AND version = :v"
        ),
        {"at": at, "by": principal, "approval": approval_id, "id": config_id, "v": version},
    )
    _card_rows(conn, kind, target, at)
    _event(
        conn,
        at,
        principal,
        "config_activated",
        table,
        target.ref,
        request_id,
        {
            "sha256": target.sha256,
            "approval_id": str(approval_id) if approval_id else None,
            "retired": f"{previous.id}/{previous.version}" if previous is not None else None,
        },
    )
    return ConfigVersion(kind, target.id, target.version, target.config, target.sha256, "active")


def active_version(conn: Connection, kind: ConfigKind) -> ConfigVersion | None:
    row = conn.execute(
        text(
            f"SELECT id, version, config, sha256, status FROM eval.{TABLES[kind]} "
            "WHERE status = 'active'"
        )
    ).first()
    if row is None:
        return None
    return ConfigVersion(kind, row.id, row.version, dict(row.config), row.sha256, row.status)


def bootstrap_configs(
    conn: Connection, config_dir: Path, principal: str, request_id: str, at: datetime
) -> list[str]:
    """Activate the shipped versions for any kind with no active version (first start)."""
    activated = []
    for kind in ("protocol", "policy", "quotas"):
        if active_version(conn, kind) is not None:
            continue
        raw = (config_dir / CONFIG_FILES[kind]).read_text(encoding="utf-8")
        draft, _ = create_version(conn, kind, raw, principal, request_id, at)
        activate_version(conn, kind, draft.id, draft.version, principal, None, request_id, at)
        activated.append(f"{kind}:{draft.ref}")
    return activated


# Data snapshots ----------------------------------------------------------------------


def register_snapshot(
    conn: Connection, path: Path, principal: str, request_id: str, at: datetime
) -> tuple[str, bool]:
    """Record a verified snapshot in data_snapshots (idempotent on the snapshot id).

    A snapshot already registered is not hashed again: the scheduler calls this on
    every tick, and the snapshot directory is named by its own id.
    """
    exists = conn.execute(
        text("SELECT 1 FROM eval.data_snapshots WHERE snapshot_id = :s"), {"s": path.name}
    ).first()
    if exists is not None:
        return path.name, False
    snapshot = read_snapshot(path)
    manifest = snapshot.manifest
    conn.execute(
        text(
            "INSERT INTO eval.data_snapshots (snapshot_id, zone, manifest, first_date, "
            "last_date, created_at, registered_by, request_id) VALUES (:s, :z, "
            "CAST(:m AS jsonb), :f, :l, :at, :by, :r)"
        ),
        {
            "s": snapshot.snapshot_id,
            "z": manifest.zone,
            "m": manifest.canonical_json(),
            "f": manifest.date_range.start,
            "l": manifest.date_range.end,
            "at": at,
            "by": principal,
            "r": request_id,
        },
    )
    _event(
        conn, at, principal, "snapshot_registered", "data_snapshot", snapshot.snapshot_id,
        request_id, {"zone": manifest.zone, "last_date": manifest.date_range.end.isoformat()},
    )  # fmt: skip
    return snapshot.snapshot_id, True


def register_current_full(
    conn: Connection, full_dir: Path, principal: str, request_id: str, at: datetime
) -> str | None:
    try:
        path = current_snapshot(full_dir)
    except SnapshotError:
        return None
    snapshot_id, _ = register_snapshot(conn, path, principal, request_id, at)
    return snapshot_id


# Epochs ------------------------------------------------------------------------------


def _last_full_month_end(at: date) -> date:
    return date(at.year, at.month, 1) - timedelta(days=1)


def resolve_windows(
    epoch: EpochConfig, calendar: list[date], activation: date
) -> tuple[dict[str, Window], dict[str, Any]]:
    """Resolve W3's end rule on the trading calendar and check the embargoes."""
    windows: dict[str, Window] = {}
    for name in WINDOWS:
        spec = getattr(epoch, name)
        end = spec.end
        if end is None:
            cutoff = _last_full_month_end(activation)
            inside = [d for d in calendar if spec.start <= d <= cutoff]
            if not inside:
                raise EvalError(
                    409,
                    "EPOCH_UNRESOLVED",
                    f"{name} has no trading dates before {cutoff} in the snapshot",
                )
            end = inside[-1]
        windows[name] = Window(spec.start, end)
    first, last = calendar[0], calendar[-1]
    for name, window in windows.items():
        if window.start < first or window.end > last:
            raise EvalError(
                409,
                "EPOCH_OUTSIDE_SNAPSHOT",
                f"{name} {window.start}..{window.end} is outside the snapshot {first}..{last}",
            )
    gaps: dict[str, int] = {}
    for earlier, later in zip(WINDOWS, WINDOWS[1:], strict=False):
        gap = sum(1 for d in calendar if windows[earlier].end < d < windows[later].start)
        gaps[f"{earlier}-{later}"] = gap
    check: dict[str, Any] = {
        "required_trading_days": epoch.embargo_trading_days,
        "gaps_trading_days": gaps,
        "passed": all(g >= epoch.embargo_trading_days for g in gaps.values()),
    }
    return windows, check


def activate_epoch(
    conn: Connection,
    epoch: EpochConfig,
    source_sha256: str,
    snapshot_id: str,
    calendar: list[date],
    protocol_epoch_ref: str,
    principal: str,
    approval_id: UUID | None,
    request_id: str,
    at: datetime,
) -> ActiveEpoch:
    """Pin the windows on the snapshot's calendar. Refuses a short embargo (Section 6.4)."""
    current = active_epoch(conn)
    if current is not None:
        if current.epoch_id == epoch.epoch_id:
            return current
        raise EvalError(
            409, "EPOCH_ACTIVE", f"epoch {current.epoch_id} is active; rollover is Phase 8"
        )
    windows, check = resolve_windows(epoch, calendar, at.date())
    check["protocol_epoch_ref"] = protocol_epoch_ref
    check["protocol_epoch_ref_matches"] = protocol_epoch_ref == epoch.epoch_id
    if not check["passed"]:
        raise EvalError(
            409,
            "EMBARGO_TOO_SHORT",
            f"epoch {epoch.epoch_id} needs {epoch.embargo_trading_days} trading days between "
            f"windows; the snapshot calendar gives {check['gaps_trading_days']}",
            check,
        )
    resolved = epoch.model_dump(mode="json") | {
        name: {"start": w.start.isoformat(), "end": w.end.isoformat()}
        for name, w in windows.items()
    }
    conn.execute(
        text(
            "INSERT INTO eval.epochs (epoch_id, version, config, source_sha256, snapshot_id, "
            "embargo_check, status, started_at, activated_at, activated_by, approval_id, "
            "request_id) VALUES (:e, :v, CAST(:c AS jsonb), :src, :s, CAST(:chk AS jsonb), "
            "'active', :at, :at, :by, :approval, :r)"
        ),
        {
            "e": epoch.epoch_id,
            "v": epoch.version,
            "c": canonical_json(resolved),
            "src": source_sha256,
            "s": snapshot_id,
            "chk": canonical_json(check),
            "at": at,
            "by": principal,
            "approval": approval_id,
            "r": request_id,
        },
    )
    _event(
        conn, at, principal, "epoch_activated", "epoch", epoch.epoch_id, request_id,
        {"snapshot_id": snapshot_id, "embargo_check": check},
    )  # fmt: skip
    for name in ("W1", "W2", "W3"):
        conn.execute(
            text(
                "INSERT INTO eval.burn_meters (epoch_id, window_name, trials, released_values, "
                "queries_used, budget, status, updated_at) VALUES (:e, :w, 0, 0, 0, NULL, "
                "'green', :at) ON CONFLICT DO NOTHING"
            ),
            {"e": epoch.epoch_id, "w": name, "at": at},
        )
    return ActiveEpoch(epoch.epoch_id, epoch.version, windows, snapshot_id, check)


def active_epoch(conn: Connection) -> ActiveEpoch | None:
    row = conn.execute(
        text(
            "SELECT epoch_id, version, config, snapshot_id, embargo_check FROM eval.epochs "
            "WHERE status = 'active'"
        )
    ).first()
    if row is None:
        return None
    windows = resolved_windows(row.config)
    return ActiveEpoch(row.epoch_id, row.version, windows, row.snapshot_id, dict(row.embargo_check))


def resolved_windows(config: dict[str, Any]) -> dict[str, Window]:
    """The windows of a stored epoch (eval.epochs.config holds them resolved)."""
    return {
        name: Window(
            date.fromisoformat(config[name]["start"]), date.fromisoformat(config[name]["end"])
        )
        for name in WINDOWS
    }


def active_state(conn: Connection) -> ActiveState | None:
    protocol = active_version(conn, "protocol")
    policy = active_version(conn, "policy")
    quotas = active_version(conn, "quotas")
    epoch = active_epoch(conn)
    if protocol is None or policy is None or quotas is None or epoch is None:
        return None
    return ActiveState(protocol, policy, quotas, epoch)


def load_epoch_file(path: Path) -> tuple[EpochConfig, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    config = json.loads(canonical_json(raw))
    return (
        EpochConfig.model_validate(config),
        hashlib.sha256(canonical_json(config).encode()).hexdigest(),
    )


def epoch_from_mapping(raw: dict[str, Any]) -> tuple[EpochConfig, str]:
    config = json.loads(canonical_json(raw))
    return (
        EpochConfig.model_validate(config),
        hashlib.sha256(canonical_json(config).encode()).hexdigest(),
    )


def snapshot_calendar(full_dir: Path, snapshot_id: str) -> list[date]:
    snapshot = read_snapshot(full_dir / snapshot_id, verify=False)
    return [d for d in snapshot.calendar().get_column("date").to_list()]
