"""One validated, redacted JSON line sent to stdout and service-owned files."""

import hashlib
import json
import logging
import os
import re
import sys
import threading
import traceback
from collections.abc import MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

import structlog

from qfr_core.config import LoggingConfig, canonical_json
from qfr_core.contracts import LogLine
from qfr_core.correlation import current

PROVIDER_ENV = frozenset({"DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "ZHIPU_API_KEY"})


def assert_provider_boundary(service: str) -> None:
    if service != "research-worker" and PROVIDER_ENV.intersection(os.environ):
        raise RuntimeError("BND-07: provider environment is forbidden in this service")


class Redactor:
    def __init__(self, config: LoggingConfig, secrets: list[str] | None = None) -> None:
        self.field_pattern = re.compile(config.sensitive_field_pattern)
        self.value_patterns = [re.compile(p) for p in config.secret_value_patterns]
        self.excluded = set(config.excluded_text_fields)
        self.secrets = sorted((s for s in (secrets or []) if s), key=len, reverse=True)

    def scrub(self, value: Any) -> Any:
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                safe_key = self.scrub(str(key))
                if self.field_pattern.search(str(key)):
                    cleaned[safe_key] = "[REDACTED]"
                elif key in self.excluded:
                    encoded = str(item).encode()
                    cleaned[safe_key] = {
                        "sha256": hashlib.sha256(encoded).hexdigest(),
                        "bytes": len(encoded),
                    }
                else:
                    cleaned[safe_key] = self.scrub(item)
            return cleaned
        if isinstance(value, (list, tuple)):
            return [self.scrub(v) for v in value]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[REDACTED]")
            for pattern in self.value_patterns:
                value = pattern.sub("[REDACTED]", value)
            return value
        return value

    def __call__(self, _: Any, __: str, event: MutableMapping[str, Any]) -> dict[str, Any]:
        return dict(self.scrub(event))


class DailyFileSink:
    def __init__(self, directory: Path, rotate_bytes: int) -> None:
        self.directory = directory
        self.rotate_bytes = rotate_bytes
        self.lock = threading.Lock()
        directory.mkdir(parents=True, exist_ok=True)

    def write(self, line: str) -> None:
        data = (line + "\n").encode()
        day = json.loads(line)["ts"][:10]
        with self.lock:
            part = 0
            while True:
                suffix = "" if part == 0 else f".part{part}"
                path = self.directory / f"{day}{suffix}.jsonl"
                if not path.exists() or path.stat().st_size + len(data) <= self.rotate_bytes:
                    break
                part += 1
            # O_APPEND and a single write prevent thread/process interleaving within a line.
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)


class JsonLogger:
    def __init__(
        self,
        service: str,
        zone: str,
        directory: Path,
        config: LoggingConfig,
        stdout: TextIO | None = None,
        secrets: list[str] | None = None,
    ) -> None:
        assert_provider_boundary(service)
        if not re.fullmatch(r"[a-z][a-z0-9-]*", service):
            raise ValueError("invalid service name")
        self.service = service
        self.zone = zone
        self.config = config
        self.stdout = stdout if stdout is not None else sys.stdout
        self.sink = DailyFileSink(directory / service, config.rotate_bytes)
        secret_field = re.compile(config.sensitive_field_pattern)
        environment_secrets = [
            value
            for key, value in os.environ.items()
            if secret_field.search(key) or key.endswith(("_DB_URL", "_MIGRATION_URL"))
        ]
        self.redactor = Redactor(config, environment_secrets + (secrets or []))
        self.logger = structlog.wrap_logger(
            self,
            processors=[self._shape, self.redactor, self._render],
            wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, config.level)),
        )

    def _shape(self, _: Any, method: str, event: MutableMapping[str, Any]) -> dict[str, Any]:
        event = current() | dict(event)
        event.setdefault("request_id", str(uuid4()))
        event.update(
            ts=datetime.now(UTC).isoformat(timespec="microseconds"),
            level=method.upper().replace("WARN", "WARNING") if method == "warn" else method.upper(),
            service=self.service,
            zone=self.zone,
        )
        if event.pop("exc_info", False):
            event["stack"] = traceback.format_exc()
            event.setdefault("error_type", type(sys.exception()).__name__)
        return event

    def _render(self, _: Any, __: str, event: MutableMapping[str, Any]) -> str:
        validated = LogLine.model_validate(event)
        return canonical_json(validated.model_dump(mode="json", exclude_none=True))

    def msg(self, line: str) -> None:
        self.sink.write(line)
        self.stdout.write(line + "\n")
        self.stdout.flush()

    debug = info = warning = error = critical = exception = msg


class StdlibBridge(logging.Handler):
    def __init__(self, target: JsonLogger) -> None:
        super().__init__()
        self.target = target

    def emit(self, record: logging.LogRecord) -> None:
        fields: dict[str, Any] = {
            "payload": {"logger": record.name, "message": record.getMessage()}
        }
        if record.exc_info:
            fields["stack"] = "".join(traceback.format_exception(*record.exc_info))
            fields["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        method = getattr(self.target.logger, record.levelname.lower())
        method("stdlib_log", **fields)
