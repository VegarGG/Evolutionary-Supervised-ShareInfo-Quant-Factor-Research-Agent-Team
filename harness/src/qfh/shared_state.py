"""Standalone research board: immutable versions, attributed findings and review decisions.

This is research state, not a factor pool or evaluator. Principals are supplied by
the trusted host, never by model output. Citation checks establish provenance and
exact excerpts, not the truth of the interpretation.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from qfh.evidence import canonical

Hash = str


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BoardPolicy(Record):
    max_events: int = Field(ge=4, le=10000)
    max_findings: int = Field(ge=1)
    max_versions: int = Field(ge=2)
    max_text_length: int = Field(ge=100)


class CandidateDefinition(Record):
    name: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    input_units: str = Field(min_length=1)
    availability_rule: str = Field(min_length=1)
    signal_rule: str = Field(min_length=1)
    execution_rule: str = Field(min_length=1)
    universe: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)


class Citation(Record):
    evidence_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]+$")
    quote: str = Field(min_length=1)


class Finding(Record):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    topic: Literal["timing", "units", "normalization", "coverage", "interpretation"]
    statement: str = Field(min_length=1)
    status: Literal["supported", "hypothesis"]
    citations: list[Citation]
    contradicts: list[str]

    @model_validator(mode="after")
    def support(self):
        if self.status == "supported" and not self.citations:
            raise ValueError("supported findings require source excerpts")
        return self


class Review(Record):
    findings: list[Finding]


class Decision(Record):
    finding_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    disposition: Literal["adopt", "reject", "defer"]
    reason: str = Field(min_length=1)


class Revision(Record):
    parent_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    definition: CandidateDefinition
    decisions: list[Decision]
    citations: list[Citation] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    unresolved: list[str]


class Episode(Record):
    episode_id: str = Field(pattern=r"^[a-z0-9-]{1,100}$")
    category: Literal["diagnostic", "open_ended"]
    synthetic_evidence: bool
    actors: dict[str, Literal["author", "reviewer", "supervisor"]]
    sources: dict[str, str] = Field(min_length=1)
    initial: CandidateDefinition
    policy: BoardPolicy


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def atomic_new(path, value):
    """An interrupted write never exposes a partial committed record."""
    raw = canonical(value)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ValueError("immutable record collision") from None
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


class Board:
    def __init__(self, directory: Path):
        self.directory = directory
        self.episode = Episode.model_validate_json((directory / "episode.json").read_bytes())

    @classmethod
    def create(cls, directory: Path, episode: Episode):
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            atomic_new(directory / "episode.json", episode.model_dump())
            board = cls(directory)
            events = board._events()
            if not events:
                board._append(
                    [],
                    "operator",
                    "initial_candidate",
                    {
                        "parent_id": None,
                        "definition": episode.initial.model_dump(),
                        "decisions": [],
                        "rationale": "Operator-supplied research starting point.",
                    },
                )
        return board

    @contextmanager
    def locked(self):
        with (self.directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            # Refuse operator manifest changes across restarts/objects.
            saved = type(self.episode).model_validate_json(
                (self.directory / "episode.json").read_bytes()
            )
            if saved != self.episode:
                raise ValueError("episode changed")
            yield self._events()

    def _events(self):
        records, previous = [], None
        for sequence, path in enumerate(sorted(self.directory.glob("event-*.json")), 1):
            event = json.loads(path.read_bytes())
            ident = event.pop("id")
            if (
                ident != digest(event)
                or event["sequence"] != sequence
                or event["previous"] != previous
                or event["episode_sha256"] != digest(self.episode.model_dump())
                or path.name != f"event-{sequence:06d}.json"
            ):
                raise ValueError("board event integrity failure")
            records.append({**event, "id": ident})
            previous = ident
        return records

    def _append(self, events, actor, kind, body):
        if len(events) >= self.episode.policy.max_events:
            raise ValueError("board event allowance exhausted")
        self._text_bounds(body)
        event = {
            "episode_sha256": digest(self.episode.model_dump()),
            "sequence": len(events) + 1,
            "previous": events[-1]["id"] if events else None,
            "at": datetime.now(UTC).isoformat(),
            "actor": actor,
            "kind": kind,
            "body": body,
        }
        value = {**event, "id": digest(event)}
        atomic_new(self.directory / f"event-{len(events) + 1:06d}.json", value)
        return value

    def _actor(self, actor, roles):
        if self.episode.actors.get(actor) not in roles:
            raise ValueError("principal is not authorized for this operation")

    def _text_bounds(self, value):
        if isinstance(value, str):
            if len(value) > self.episode.policy.max_text_length:
                raise ValueError("board text bound exceeded")
        elif isinstance(value, list):
            for v in value:
                self._text_bounds(v)
        elif isinstance(value, dict):
            for v in value.values():
                self._text_bounds(v)

    def _citations(self, citations):
        for c in citations:
            source = self.episode.sources.get(c.evidence_id)
            if source is None or not c.quote.strip() or c.quote not in source:
                raise ValueError("citation must quote an authorized episode source exactly")

    @staticmethod
    def _head(events):
        return next(e for e in reversed(events) if e["kind"] in ("initial_candidate", "revision"))

    def snapshot(self, actor):
        self._actor(actor, {"author", "reviewer", "supervisor"})
        with self.locked() as events:
            return {
                "episode_id": self.episode.episode_id,
                "head": self._head(events),
                "findings": [e for e in events if e["kind"] == "finding"],
                "versions": [e for e in events if e["kind"] in ("initial_candidate", "revision")],
                "events": events,
            }

    def publish(self, actor: str, finding: Finding):
        self._actor(actor, {"author", "reviewer", "supervisor"})
        self._citations(finding.citations)
        with self.locked() as events:
            versions = {e["id"] for e in events if e["kind"] in ("initial_candidate", "revision")}
            if finding.candidate_id not in versions:
                raise ValueError("finding targets a candidate outside this episode")
            findings = {e["id"]: e for e in events if e["kind"] == "finding"}
            if len(findings) >= self.episode.policy.max_findings:
                raise ValueError("finding allowance exhausted")
            if any(
                i not in findings or findings[i]["body"]["candidate_id"] != finding.candidate_id
                for i in finding.contradicts
            ):
                raise ValueError("conflict must reference a finding on the same candidate")
            return self._append(events, actor, "finding", finding.model_dump())

    def revise(self, actor: str, revision: Revision):
        self._actor(actor, {"author", "supervisor"})
        self._citations(revision.citations)
        with self.locked() as events:
            head = self._head(events)
            if head["id"] != revision.parent_id:
                raise ValueError("stale parent; read the board before proposing another revision")
            if (
                sum(e["kind"] in ("initial_candidate", "revision") for e in events)
                >= self.episode.policy.max_versions
            ):
                raise ValueError("candidate version allowance exhausted")

            def normalize(s):
                return re.sub(r"\s+", "", s).casefold()

            before, after = head["body"]["definition"], revision.definition.model_dump()
            changed = [k for k in before if normalize(before[k]) != normalize(after[k])]
            if not set(changed) - {"name", "hypothesis"}:
                raise ValueError(
                    "revision must change a definition field, not only a name or hypothesis"
                )
            findings = {e["id"]: e for e in events if e["kind"] == "finding"}
            ids = [d.finding_id for d in revision.decisions]
            if len(ids) != len(set(ids)):
                raise ValueError("one disposition per finding is required")
            if any(
                i not in findings or findings[i]["body"]["candidate_id"] != revision.parent_id
                for i in ids
            ):
                raise ValueError("decision must reference a finding on the exact parent")
            # Preserve unresolved conflicts. Every direct peer finding on this
            # parent needs an explicit disposition, including rejected findings.
            relevant = {
                i for i, f in findings.items() if f["body"]["candidate_id"] == revision.parent_id
            }
            if set(ids) != relevant:
                raise ValueError("record adopt/reject/defer for every finding on the parent")
            adopted = [
                findings[d.finding_id] for d in revision.decisions if d.disposition == "adopt"
            ]
            return self._append(
                events,
                actor,
                "revision",
                {
                    **revision.model_dump(),
                    "changed_fields": changed,
                    "peer_finding_ids": [e["id"] for e in adopted if e["actor"] != actor],
                    "verification": "Structural provenance only; "
                    "semantic support needs independent review.",
                },
            )
