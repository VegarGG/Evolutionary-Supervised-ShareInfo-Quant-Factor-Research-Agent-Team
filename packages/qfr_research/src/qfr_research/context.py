"""The context assembler (P5.4, PLAN Sections 11.5 and 12.7).

A deterministic prompt sampler in the AlphaEvolve style. For an engineer call it gathers
the parents' manifests and released report digests, the island's top 3 elites, 2
diverse archive members, relevant knowledge items, the seed entries named in the brief
(improve modes) and what the lineage has already tried, so the engineer does not repeat
failed attempts. Everything it shows research is research-visible: manifests from
registry-api and released (coarsened) report content from report_cache; owner-grade
evidence never enters. Each section lists its items oldest first, so the prompt budget
trims the oldest material first. The ids of everything included go into the trace.
"""

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_research.clients import ServiceRefused, ServiceUnavailable
from qfr_research.env import ResearchEnv

IMPROVE_SEED_MODES = frozenset({"improve_factors", "improve_strategy", "review_and_iterate"})
W1_DIGEST = (
    "rankic_mean",
    "rankic_ir",
    "ls_net_sharpe",
    "monotonicity",
    "top_turnover",
    "max_library_correlation",
    "decay_profile",
    "flags",
)


def _compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


@dataclass
class Context:
    parents_text: str
    context_text: str
    hypothesis_text: str
    included: dict[str, list[str]] = field(default_factory=dict)
    parents: dict[str, dict[str, Any]] = field(default_factory=dict)


def report_digest(conn: Connection, version_id: UUID | str) -> dict[str, Any]:
    """The latest released W1 values (and W2, screening or intake status) of a version."""
    rows = conn.execute(
        text(
            "SELECT report_id, report_type, content -> 'content' AS content FROM report_cache "
            "WHERE version_id = :v ORDER BY released_at, report_id"
        ),
        {"v": str(version_id)},
    ).all()
    digest: dict[str, Any] = {}
    for row in rows:
        content = row.content or {}
        if row.report_type == "w1":
            digest["w1"] = {k: content.get(k) for k in W1_DIGEST}
            digest["w1_report_id"] = str(row.report_id)
        elif row.report_type in ("w2", "screening", "intake"):
            digest[row.report_type] = {
                k: content.get(k) for k in ("status", "reasons", "flags") if k in content
            }
    return digest


class ContextAssembler:
    def __init__(self, env: ResearchEnv) -> None:
        self.env = env

    def parent_manifest(self, version_id: str) -> dict[str, Any] | None:
        try:
            record = self.env.registry.version(UUID(version_id))
        except (ServiceRefused, ServiceUnavailable):
            return None
        manifest = record.manifest.model_dump(mode="json")
        return {
            "version_id": version_id,
            "family_id": str(record.family_id),
            "name": manifest["name"],
            "title": manifest["title"],
            "expression": manifest["implementation"].get("expression"),
            "declared": manifest["declared"],
            "rationale": manifest["rationale"],
            "operator": manifest["provenance"]["operator"],
            "program_id": manifest["provenance"].get("program_id"),
        }

    def assemble(
        self,
        conn: Connection,
        program_id: UUID,
        island: str,
        parent_ids: list[str],
        settings: dict[str, Any],
        mode: str,
        seed_version_ids: list[str],
    ) -> Context:
        sizes = settings["context"]
        included: dict[str, list[str]] = {}
        parents: dict[str, dict[str, Any]] = {}
        parent_lines = []
        for version_id in parent_ids:
            manifest = self.parent_manifest(version_id)
            if manifest is None:
                continue
            digest = report_digest(conn, version_id)
            parents[version_id] = manifest | {"digest": digest}
            parent_lines.append(
                f"- parent {version_id}: "
                + _compact(
                    {
                        "title": manifest["title"],
                        "expression": manifest["expression"],
                        "declared": manifest["declared"],
                        "rationale": {
                            k: manifest["rationale"].get(k)
                            for k in ("summary", "mechanism", "falsification")
                        },
                        "released": digest or "no released report yet",
                    }
                )
            )
        included["parents"] = list(parents)
        sections = []
        elites = self._elites(conn, program_id, island, int(sizes["island_elites"]))
        included["island_elites"] = [e["version_id"] for e in elites]
        sections.append(
            "Top elites of this island (official fitness, released values):\n"
            + ("\n".join(f"- {_compact(e)}" for e in elites) or "none yet")
        )
        archive = self._diverse_archive(conn, program_id, elites, int(sizes["archive_members"]))
        included["archive_members"] = [a["version_id"] for a in archive]
        sections.append(
            "Diverse archive members (other behavior cells):\n"
            + ("\n".join(f"- {_compact(a)}" for a in archive) or "none yet")
        )
        knowledge = self._knowledge(conn, program_id, int(sizes["lineage_items"]))
        included["knowledge_items"] = [k["item_id"] for k in knowledge]
        sections.append(
            "Knowledge items:\n"
            + ("\n".join(f"- [{k['kind']}] {k['statement']}" for k in knowledge) or "none yet")
        )
        if mode in IMPROVE_SEED_MODES and seed_version_ids:
            seeds = []
            for version_id in seed_version_ids[: int(sizes["lineage_items"])]:
                manifest = self.parent_manifest(version_id)
                if manifest is not None:
                    seeds.append(
                        {
                            "version_id": version_id,
                            "title": manifest["title"],
                            "expression": manifest["expression"],
                        }
                    )
            included["seeds"] = [s["version_id"] for s in seeds]
            sections.append(
                "Seed entries named in the brief:\n"
                + ("\n".join(f"- {_compact(s)}" for s in seeds) or "none")
            )
        tried = self._tried(conn, program_id, parent_ids, int(sizes["lineage_items"]))
        included["lineage_tried"] = [t["candidate_id"] for t in tried]
        sections.append(
            "Already tried from these parents (do not repeat):\n"
            + ("\n".join(f"- {_compact(t)}" for t in tried) or "nothing yet")
        )
        hypothesis = self._hypothesis(conn, parent_ids, parents)
        return Context(
            parents_text="\n".join(parent_lines) or "none",
            context_text="\n\n".join(sections),
            hypothesis_text=hypothesis,
            included=included,
            parents=parents,
        )

    def _elites(
        self, conn: Connection, program_id: UUID, island: str, count: int
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            text(
                "SELECT version_id, expression, fitness, originality, analysis, metrics, "
                "descriptors FROM population_members WHERE program_id = :p AND island_key = :i "
                "AND status = 'official' AND fitness IS NOT NULL"
            ),
            {"p": program_id, "i": island},
        ).all()
        ordered = sorted(
            rows,
            key=lambda r: (
                -float(r.fitness),
                -float(r.originality or 0.0),
                int((r.analysis or {}).get("nodes", 0)),
                str(r.version_id),
            ),
        )
        out = []
        for row in ordered[:count]:
            w1 = (row.metrics or {}).get("w1") or {}
            out.append(
                {
                    "version_id": str(row.version_id),
                    "expression": row.expression,
                    "fitness": round(float(row.fitness), 4),
                    "cell": (row.descriptors or {}).get("cell_key"),
                    "released": {k: w1.get(k) for k in W1_DIGEST if k in w1},
                }
            )
        return out

    def _diverse_archive(
        self, conn: Connection, program_id: UUID, elites: list[dict[str, Any]], count: int
    ) -> list[dict[str, Any]]:
        """Archive elites in cells unlike the island's elites: each pick maximizes the
        number of descriptor coordinates that differ from everything chosen so far, ties
        broken by fitness, then version id."""
        rows = conn.execute(
            text(
                "SELECT a.cell_key, a.elite_version_id, a.fitness, a.descriptors, a.island_key, "
                "m.expression FROM archive_cells a LEFT JOIN LATERAL (SELECT expression FROM "
                "population_members WHERE program_id = a.program_id AND version_id = "
                "a.elite_version_id LIMIT 1) m ON true WHERE a.program_id = :p "
                "ORDER BY a.cell_key"
            ),
            {"p": program_id},
        ).all()
        taken = {e["version_id"] for e in elites}
        chosen_cells = [str(e["cell"]) for e in elites if e.get("cell")]
        pool = [r for r in rows if str(r.elite_version_id) not in taken]
        out: list[dict[str, Any]] = []
        while pool and len(out) < count:

            def distance(row: Any, cells: list[str] = chosen_cells) -> int:
                mine = str(row.cell_key).split("|")
                if not cells:
                    return len(mine)
                return min(
                    sum(a != b for a, b in zip(mine, c.split("|"), strict=False)) for c in cells
                )

            best = max(pool, key=lambda r: (distance(r), float(r.fitness), str(r.elite_version_id)))
            pool.remove(best)
            chosen_cells.append(best.cell_key)
            out.append(
                {
                    "version_id": str(best.elite_version_id),
                    "cell": best.cell_key,
                    "island": best.island_key,
                    "expression": best.expression,
                    "fitness": round(float(best.fitness), 4),
                }
            )
        return out

    def _knowledge(self, conn: Connection, program_id: UUID, count: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            text(
                "SELECT item_id, kind, statement FROM knowledge_items WHERE program_id = :p "
                "ORDER BY created_at DESC, item_id LIMIT :n"
            ),
            {"p": program_id, "n": count},
        ).all()
        return [
            {"item_id": str(r.item_id), "kind": r.kind, "statement": r.statement}
            for r in reversed(rows)
        ]

    def _tried(
        self, conn: Connection, program_id: UUID, parent_ids: list[str], count: int
    ) -> list[dict[str, Any]]:
        """Earlier children of these parents in this program: their expression, what
        happened to them and their released flags."""
        if not parent_ids:
            return []
        rows = conn.execute(
            text(
                "SELECT c.candidate_id, c.operator, c.expression, c.state, c.reason, "
                "c.payload -> 'parent_version_ids' AS parents, v.version_id FROM candidates c "
                "LEFT JOIN candidate_versions v ON v.candidate_id = c.candidate_id WHERE "
                "c.program_id = :p AND c.kind = 'factor' AND c.payload -> 'parent_version_ids' "
                "?| CAST(:ids AS text[]) ORDER BY c.created_at DESC, c.candidate_id LIMIT :n"
            ),
            {"p": program_id, "ids": list(parent_ids), "n": count},
        ).all()
        out = []
        for row in reversed(rows):
            item: dict[str, Any] = {
                "candidate_id": str(row.candidate_id),
                "operator": row.operator,
                "expression": row.expression,
                "outcome": row.state if row.reason is None else f"{row.state} ({row.reason})",
            }
            if row.version_id is not None:
                digest = report_digest(conn, row.version_id)
                if "w1" in digest:
                    item["released_flags"] = digest["w1"].get("flags")
                for key in ("screening", "intake"):
                    if key in digest:
                        item[key] = digest[key]
            out.append(item)
        return out

    def _hypothesis(
        self, conn: Connection, parent_ids: list[str], parents: dict[str, dict[str, Any]]
    ) -> str:
        """The rationale a child inherits: its first parent's program hypothesis when the
        parent was developed here, else the parent manifest's rationale."""
        lines = []
        for version_id in parent_ids:
            row = conn.execute(
                text(
                    "SELECT h.hypothesis_id, h.payload FROM candidate_versions v JOIN candidates c "
                    "ON c.candidate_id = v.candidate_id JOIN hypotheses h ON "
                    "h.hypothesis_id = c.hypothesis_id WHERE v.version_id = :v"
                ),
                {"v": version_id},
            ).first()
            if row is not None:
                lines.append(f"- hypothesis_id {row.hypothesis_id}: {_compact(row.payload)}")
            elif version_id in parents:
                rationale = parents[version_id]["rationale"]
                lines.append(f"- inherited rationale of parent {version_id}: {_compact(rationale)}")
        return "\n".join(lines) or "none"


def parent_hypothesis(conn: Connection, version_id: str) -> UUID | None:
    """The program hypothesis behind a published version, when research developed it."""
    value: UUID | None = conn.execute(
        text(
            "SELECT c.hypothesis_id FROM candidate_versions v JOIN candidates c ON "
            "c.candidate_id = v.candidate_id WHERE v.version_id = :v"
        ),
        {"v": version_id},
    ).scalar()
    return value
