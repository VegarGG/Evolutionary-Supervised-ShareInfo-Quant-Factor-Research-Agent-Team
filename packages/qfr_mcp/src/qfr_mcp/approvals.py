"""Approval scopes and short codes (PLAN Sections 10.5 and 13.5, MCP-03).

An approval names exactly what the owner decided. Before anything is stored, the front
door resolves the scope against the services that own its items and works out the short
code of each item:

- a deliverable item: the job's code and the item's code, J-nnnn F-k for a factor and
  J-nnnn S-k for a strategy (research numbers them when it assembles the deliverable);
- an acceptance case: C-nnnn (the evaluator numbers cases when it opens them);
- a pool entry: E- and the last six hex digits of the entry id (qfr.pool.list shows it);
- a job with no item named, for a rejection: J-nnnn.

The owner's confirmation must contain every code in scope; a deliverable item's job code
and item code may appear apart, as in "APPROVE J-0042 F-1 F-2". This guards against an
approval by paraphrase. It is not cryptographic and does not pretend to be.

An approval that adds to a pool also fixes the tier: the tier the evaluator confirms for
every version in scope (its pool tier), or a lower tier the owner names.
"""

import re
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from qfr_core.contracts import TIER_ORDER, ApprovalScope, PoolEntry, Tier
from qfr_core.eval_api import AcceptanceCase

from qfr_mcp.api_client import DownstreamRefused, DownstreamUnavailable
from qfr_mcp.eval_client import EvalAdminClient
from qfr_mcp.registry_client import RegistryClient
from qfr_mcp.research_client import ResearchClient

Decision = Literal["approve", "reject", "retire", "accept_case", "reject_case", "rollover_epoch"]
Pool = Literal["factor", "strategy"]
RANK = {tier: i for i, tier in enumerate(TIER_ORDER)}


class ApprovalRefused(ValueError):
    """The scope cannot be resolved, or the confirmation lacks a short code."""

    def __init__(self, code: str, message: str, details: dict[str, object] | None = None):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.details = code, message, details or {}


@dataclass(frozen=True)
class Code:
    """One item's short code and the tokens the confirmation must contain."""

    label: str
    tokens: tuple[str, ...]


def entry_code(entry_id: UUID) -> str:
    return f"E-{entry_id.hex[-6:]}"


def item_code(label: str) -> Code:
    """A deliverable item's code as research writes it, for example "J-0042 F-1"."""
    return Code(label, tuple(label.upper().split()))


def single(label: str) -> Code:
    return Code(label, (label.upper(),))


def match(codes: list[Code], confirmation: str, pattern: str) -> tuple[list[str], list[str]]:
    """The labels whose tokens all appear in the confirmation, and those that do not."""
    found = {m.group(0).upper() for m in re.finditer(pattern, confirmation, re.IGNORECASE)}
    matched = [c.label for c in codes if all(t in found for t in c.tokens)]
    missing = [c.label for c in codes if c.label not in matched]
    return matched, missing


@dataclass
class Resolved:
    scope: ApprovalScope
    codes: list[Code]
    kinds: dict[UUID, str] = field(default_factory=dict)


@dataclass
class Resolver:
    research: ResearchClient | None
    admin: EvalAdminClient | None
    registry: RegistryClient | None

    @staticmethod
    def _refused(error: DownstreamRefused, code: str, message: str) -> ApprovalRefused:
        if error.status == 404:
            return ApprovalRefused(code, message)
        return ApprovalRefused(error.error, error.message)

    async def resolve(
        self,
        decision: Decision,
        *,
        job_id: UUID | None,
        deliverable_id: UUID | None,
        version_ids: list[UUID],
        pool: Pool | None,
        tier: Tier | None,
        case_id: UUID | None,
        entry_ids: list[UUID],
    ) -> Resolved:
        if decision == "rollover_epoch":
            raise ApprovalRefused(
                "DECISION_UNSUPPORTED",
                "epoch rollover arrives with Phase 8 (qfr.ops.rollover_epoch)",
            )
        versions = list(dict.fromkeys(version_ids))
        entries_wanted = list(dict.fromkeys(entry_ids))
        try:
            items, job_id = await self._deliverable(job_id, deliverable_id)
            job_code = await self._job_code(job_id)
            case = await self._case(case_id)
            entries = await self._entries(pool, entries_wanted)
        except DownstreamUnavailable as error:
            raise ApprovalRefused(
                "SCOPE_UNAVAILABLE", f"the scope cannot be checked now: {error}"
            ) from None

        kinds: dict[UUID, str] = {v: kind for v, (_, kind) in items.items()}
        codes: list[Code] = []
        if decision in ("accept_case", "reject_case"):
            if case is None:
                raise ApprovalRefused("SCOPE_INVALID", "a case decision names its case_id")
            if deliverable_id or entries_wanted or pool or tier:
                raise ApprovalRefused(
                    "SCOPE_INVALID", "a case decision names the case and its version only"
                )
            if any(v != case.version_id for v in versions):
                raise ApprovalRefused("SCOPE_INVALID", "the case is about another version")
            if case.state != "open":
                raise ApprovalRefused("CASE_DECIDED", f"case {case.short_code} is already decided")
            versions = [case.version_id]
            kinds[case.version_id] = case.kind
            codes.append(single(case.short_code))
        elif decision == "retire":
            if not entries_wanted:
                raise ApprovalRefused("SCOPE_INVALID", "a retirement names the pool and entry_ids")
            if tier is not None or case is not None or deliverable_id is not None:
                raise ApprovalRefused("SCOPE_INVALID", "a retirement names pool entries only")
            covered = {e.version_id for e in entries.values()}
            if any(v not in covered for v in versions):
                raise ApprovalRefused("SCOPE_INVALID", "a version is not one of the entries")
            versions = [entries[e].version_id for e in entries_wanted]
            codes.extend(single(entry_code(e)) for e in entries_wanted)
        elif decision == "reject":
            if job_id is None or job_code is None:
                raise ApprovalRefused(
                    "SCOPE_INVALID", "a rejection names the job (job_id or deliverable_id)"
                )
            if case is not None or entries_wanted or pool or tier:
                raise ApprovalRefused("SCOPE_INVALID", "a rejection names a job and its items")
            for version_id in versions:
                if version_id not in items:
                    raise ApprovalRefused(
                        "SCOPE_INVALID", f"version {version_id} is not an item of the deliverable"
                    )
                codes.append(item_code(items[version_id][0]))
            if not versions:
                codes.append(single(job_code))
        else:  # approve
            if not versions and not entries_wanted and items:
                versions = list(items)  # the whole deliverable
            if not versions and not entries_wanted:
                raise ApprovalRefused(
                    "SCOPE_INVALID", "an approval names versions, a deliverable or pool entries"
                )
            by_entry = {e.version_id: entry_id for entry_id, e in entries.items()}
            for version_id in versions:
                if version_id in items:
                    codes.append(item_code(items[version_id][0]))
                elif case is not None and case.version_id == version_id:
                    codes.append(single(case.short_code))
                    kinds[version_id] = case.kind
                elif version_id in by_entry:
                    pass  # named by its entry's code below
                else:
                    raise ApprovalRefused(
                        "VERSION_UNCODED",
                        f"no short code names version {version_id}: approve it from a "
                        "deliverable (J-nnnn F-k or S-k), an acceptance case (C-nnnn) or its "
                        "pool entry (E-xxxxxx)",
                    )
            for entry_id in entries_wanted:
                entry = entries[entry_id]
                codes.append(single(entry_code(entry_id)))
                kinds[entry.version_id] = entry.pool
                if entry.version_id not in versions:
                    versions.append(entry.version_id)
            if pool is not None:
                wrong = [str(v) for v in versions if kinds.get(v, pool) != pool]
                if wrong:
                    raise ApprovalRefused(
                        "KIND_POOL_CONFLICT",
                        f"these versions cannot enter the {pool} pool: {wrong}",
                    )
            try:
                tier = await self._tier(versions, tier)
            except (DownstreamUnavailable, DownstreamRefused) as error:
                raise ApprovalRefused(
                    "SCOPE_UNAVAILABLE", f"the evaluator cannot confirm the tier now: {error}"
                ) from None
        scope = ApprovalScope(
            job_id=job_id,
            deliverable_id=deliverable_id,
            version_ids=versions,
            pool=pool,
            tier=tier,
            case_id=case_id,
            entry_ids=entries_wanted,
        )
        return Resolved(scope, codes, kinds)

    async def _deliverable(
        self, job_id: UUID | None, deliverable_id: UUID | None
    ) -> tuple[dict[UUID, tuple[str, str]], UUID | None]:
        if deliverable_id is None:
            return {}, job_id
        if self.research is None:
            raise ApprovalRefused("RESEARCH_UNCONFIGURED", "RESEARCH_API_URL is not set")
        try:
            view = await self.research.deliverable(deliverable_id, False)
        except DownstreamRefused as error:
            raise self._refused(error, "DELIVERABLE_NOT_FOUND", "no such deliverable") from None
        document = view.deliverable
        if job_id is not None and document.job_id != job_id:
            raise ApprovalRefused("SCOPE_INVALID", "the deliverable belongs to another job")
        items: dict[UUID, tuple[str, str]] = {
            item.version_id: (label, item.kind)
            for item, label in zip(document.items, document.short_codes, strict=True)
        }
        return items, document.job_id

    async def _job_code(self, job_id: UUID | None) -> str | None:
        if job_id is None:
            return None
        if self.research is None:
            raise ApprovalRefused("RESEARCH_UNCONFIGURED", "RESEARCH_API_URL is not set")
        try:
            return (await self.research.job(job_id)).short_code
        except DownstreamRefused as error:
            raise self._refused(error, "JOB_NOT_FOUND", "no such job") from None

    async def _case(self, case_id: UUID | None) -> AcceptanceCase | None:
        if case_id is None:
            return None
        if self.admin is None:
            raise ApprovalRefused("EVAL_ADMIN_UNCONFIGURED", "EVAL_ADMIN_API_URL is not set")
        try:
            page = await self.admin.cases(case_id=case_id)
        except DownstreamRefused as error:
            raise self._refused(
                error, "CASE_NOT_FOUND", "no acceptance case with this id"
            ) from None
        if not page.items:
            raise ApprovalRefused("CASE_NOT_FOUND", "no acceptance case with this id")
        return page.items[0]

    async def _entries(self, pool: Pool | None, entry_ids: list[UUID]) -> dict[UUID, PoolEntry]:
        if not entry_ids:
            return {}
        if pool is None:
            raise ApprovalRefused("SCOPE_INVALID", "name the pool of the entries")
        if self.registry is None:
            raise ApprovalRefused("REGISTRY_UNCONFIGURED", "REGISTRY_API_URL is not set")
        found: dict[UUID, PoolEntry] = {}
        for entry_id in entry_ids:
            try:
                found[entry_id] = (await self.registry.pool_entry(pool, entry_id)).entry
            except DownstreamRefused as error:
                raise self._refused(
                    error, "ENTRY_NOT_FOUND", f"no entry {entry_id} in the {pool} pool"
                ) from None
        return found

    async def _tier(self, versions: list[UUID], named: Tier | None) -> Tier:
        """The tier every version has reached, from the evaluator; a named tier may be
        lower, never higher."""
        if self.admin is None:
            raise ApprovalRefused(
                "EVAL_ADMIN_UNCONFIGURED", "the evaluator must confirm the tier reached"
            )
        page = await self.admin.version_states(versions)
        reached = {s.version_id: s.pool_tier for s in page.items}
        short = [str(v) for v in versions if reached.get(v) is None]
        if short:
            raise ApprovalRefused("TIER_NOT_REACHED", f"the evaluator confirms no pass for {short}")
        floor = min((reached[v] for v in versions), key=lambda t: RANK[t])  # type: ignore[index]
        assert floor is not None
        if named is not None and RANK[named] > RANK[floor]:
            raise ApprovalRefused(
                "TIER_NOT_REACHED", f"tier {named} is above the tier reached ({floor})"
            )
        return named or floor
