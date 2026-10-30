"""Bounded operator configuration and exact credential references for service launch.

This module does not connect, generate keys, modify grants or import a QFR service.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from qfr_core.contracts.services import HTTPServerConfiguration, ServiceDatabaseConfiguration

DatabaseService = Literal["research", "registry", "feedback"]
# Bootstrap parser bound is part of qfr-service-launch/1, before reading any policy.
MAX_LAUNCH_JSON_BYTES = 4 * 1024 * 1024


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate configuration key")
        result[key] = value
    return result


def _nonfinite(value: str) -> Any:
    raise ValueError("nonfinite configuration number")


def load_contract[T: BaseModel](path: Path, model: type[T]) -> T:
    with path.open("rb") as stream:
        raw = stream.read(MAX_LAUNCH_JSON_BYTES + 1)
    if len(raw) > MAX_LAUNCH_JSON_BYTES:
        raise ValueError("service configuration exceeds bootstrap bound")
    return model.model_validate(
        json.loads(raw, object_pairs_hook=_unique, parse_constant=_nonfinite)
    )


def database_identity(service: DatabaseService) -> tuple[str, str]:
    return {
        "research": ("research_rw", "research_db"),
        "registry": ("registry_app", "registry_db"),
        "feedback": ("feedback_ro", "eval_db"),
    }[service]


def database_arguments(
    config: ServiceDatabaseConfiguration, environment: Mapping[str, str], service: DatabaseService
) -> dict[str, Any]:
    secret = environment.get(config.password_ref.removeprefix("env:"))
    if secret is None or not secret or "\x00" in secret or len(secret.encode()) > 4096:
        raise ValueError("required database credential is missing or invalid")
    user, database = database_identity(service)
    return dict(
        host=config.host,
        port=config.port,
        user=user,
        dbname=database,
        password=secret,
        autocommit=True,
        connect_timeout=config.connect_timeout_seconds,
        options=f"-c statement_timeout={1000 * config.connect_timeout_seconds}",
    )


def server_arguments(config: HTTPServerConfiguration) -> dict[str, Any]:
    return config.model_dump(exclude={"revision"})
