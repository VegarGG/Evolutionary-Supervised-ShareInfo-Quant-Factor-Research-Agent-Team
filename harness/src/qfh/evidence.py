"""Immutable research evidence, bounded source requests and checked factor proposals."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[str] = Field(min_length=1, max_length=5)
    start: date
    end: date

    @model_validator(mode="after")
    def bounded(self):
        import re

        if any(not re.fullmatch(r"\d{6}\.(XSHE|XSHG)", s) for s in self.symbols):
            raise ValueError("use RiceQuant mainland stock identifiers")
        if not 0 <= (self.end - self.start).days <= 60:
            raise ValueError("request one bounded range of at most 61 calendar days")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("duplicate symbols")
        return self


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["ricequant", "diagnostic_fixture"]
    kind: Literal["bars", "report_summaries", "announcements", "news", "diagnostic"]
    request: dict
    retrieved_at: datetime
    research_cutoff: datetime
    content: list[dict]
    timing_limit: str
    synthetic: bool = False


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factor_name: str = Field(min_length=1, max_length=160)
    definition: str = Field(min_length=1, max_length=3000)
    availability_rule: str = Field(min_length=1, max_length=1600)
    normalization: str = Field(min_length=1, max_length=1600)
    claims: list[Claim] = Field(min_length=1, max_length=12)
    changes: list[str] = Field(max_length=12)
    unresolved: list[str] = Field(max_length=12)
    peer_contribution_ids: list[str] = Field(max_length=12)
    first_signal_date: date | None
    first_execution_date: date | None
    computed_ratio: float | None


class EvidenceStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def put(self, value: dict) -> str:
        raw = canonical(value)
        digest = hashlib.sha256(raw).hexdigest()
        path = self.root / f"{digest}.json"
        try:
            with path.open("xb") as f:
                f.write(raw)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ValueError("immutable evidence collision") from None
        return digest

    def get(self, digest: str) -> dict:
        import re

        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid evidence id")
        raw = (self.root / f"{digest}.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("evidence hash mismatch")
        return json.loads(raw)
