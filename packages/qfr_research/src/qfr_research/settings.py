"""Research-zone configuration: service parameters, providers, roles and the charter.

Every tunable comes from configs/research/*.yaml (PLAN Section 20). Provider keys are
read from the environment of research-worker only, by the variable name that
providers.yaml names, and never stored, logged or traced.
"""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from qfr_core.config import (
    CharterConfig,
    ProvidersConfig,
    RolesConfig,
    RuntimeSettings,
    load_config,
    logging_config,
)
from qfr_core.logging import JsonLogger

IslandKey = Literal["I1", "I2", "I3", "I4", "I5", "I6"]
ISLANDS: tuple[IslandKey, ...] = ("I1", "I2", "I3", "I4", "I5", "I6")
Role = Literal["supervisor", "hypothesis", "engineer", "critic", "analyst", "interp_review"]
ROLES: tuple[Role, ...] = (
    "supervisor",
    "hypothesis",
    "engineer",
    "critic",
    "analyst",
    "interp_review",
)


class ApiSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    bind: str
    port: int = Field(gt=0, le=65535)
    list_default: int = Field(gt=0)
    list_max: int = Field(gt=0)
    wait_max_seconds: int = Field(gt=0)
    wait_poll_seconds: float = Field(gt=0)


class WorkerSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tick_seconds: float = Field(gt=0)
    lease_seconds: int = Field(gt=0)
    max_attempts: int = Field(ge=1)
    retry_backoff_seconds: list[int]
    probe_daily_utc: str
    heartbeat_seconds: float = Field(gt=0)
    after_batch_margin_seconds: int = Field(ge=0)


class FeedbackSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    page_limit: int = Field(gt=0, le=2000)
    report_types_interpreted: list[str]


class AnalystSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reports_per_run: int = Field(gt=0)
    interpretation_review_seed: int


class TimelineSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    first_reports: str
    first_deliverable: str


class EstimateSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    chars_per_token: float = Field(gt=0)


class ServiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str
    api: ApiSection
    worker: WorkerSection
    feedback: FeedbackSection
    analyst: AnalystSection
    islands: dict[IslandKey, str]
    island_keywords: dict[str, list[IslandKey]]
    timeline: dict[Literal["w1_pass", "w2_pass", "advanced", "incubated"], TimelineSection]
    estimate: EstimateSection


@dataclass(frozen=True)
class ResearchConfig:
    """Everything the research zone reads from configs/, validated once."""

    root: Path
    service: ServiceConfig
    charter: CharterConfig
    charter_values: dict[str, object]
    providers: ProvidersConfig
    roles: RolesConfig
    digests: dict[str, str]

    @classmethod
    def load(cls, root: Path) -> "ResearchConfig":
        kinds: tuple[Literal["charter", "providers", "roles"], ...] = (
            "charter",
            "providers",
            "roles",
        )
        docs = {kind: load_config(kind, root) for kind in kinds}
        service_doc = load_config("research", root)
        return cls(
            root=root,
            service=ServiceConfig.model_validate(service_doc.values),
            charter=CharterConfig.model_validate(docs["charter"].values),
            charter_values=dict(docs["charter"].values),
            providers=ProvidersConfig.model_validate(docs["providers"].values),
            roles=RolesConfig.model_validate(docs["roles"].values),
            digests={k: d.sha256 for k, d in docs.items()} | {"research": service_doc.sha256},
        )

    def request(self, key: str) -> object:
        return self.providers.request[key]


def prompts_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(env.get("QFR_PROMPTS_DIR") or "prompts")


def research_logger(
    service: str, settings: RuntimeSettings, secrets: list[str] | None = None
) -> JsonLogger:
    config = logging_config(settings.config_dir)
    if settings.log_level:
        config = config.model_copy(update={"level": settings.log_level})
    return JsonLogger(
        service, "research", settings.log_dir, config, stdout=sys.stderr, secrets=secrets or []
    )


def read_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
