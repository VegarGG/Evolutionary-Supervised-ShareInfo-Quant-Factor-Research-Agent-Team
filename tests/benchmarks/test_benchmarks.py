"""BM-PLANTED and BM-NULL at W1 level (PLAN Section 18.3, P5.8; Phase 5 acceptance).

Both run the whole offline stack: the scripted client submits through the MCP front
door, research runs its generations with the scripted LLM, the evaluator measures each
publication on W1, and the release engine releases the reports. Results
are written as JSON (QFR_BENCHMARK_DIR in `just bench` and the nightly workflow, which
keeps them as an artifact). Both are marked `benchmark` and run with `just bench`.

BM-PLANTED checks the Phase 5 acceptance on the planted world: within 10 generations a
factor with mean rank correlation 0.7 or more to A1 or A2 passes W1 (generations to
discovery are recorded), the best island fitness improves, archive coverage reaches 25%
of the cells and stays there, the deliverable's iteration history of the discovery
reaches back to its explore hypothesis, and TRC-03 holds on the run: every operator
application has its parents and AST diffs, and the iteration history of every published
version reconstructs each hop of its lineage DAG (the scripted five-generation lineage
with a crossover is tests/research/test_lineage.py). BM-NULL records the W1 pass rate on
the null world with the same pool (50 generations by default; QFR_BM_NULL_GENERATIONS
overrides). Both run with fixed seeds for the scripted LLM and the engine.
"""

import os

import pytest

from tests.benchmarks.harness import (
    BenchmarkModels,
    BenchmarkScript,
    discoveries,
    fix_engine_seeds,
    lineage_report,
    operator_steps,
    run_benchmark,
    run_body,
    write_results,
)
from tests.research.rig import research_stack

pytestmark = [pytest.mark.postgres, pytest.mark.benchmark]

ISLANDS = ["I1", "I2", "I3", "I4", "I5", "I6"]
PLANTED_SEED = 20251031
NULL_SEED = 20251101
COVERAGE_MIN = 0.25  # the diversity guardrail's archive coverage (Section 12.6)


def test_bm_planted(tmp_path, monkeypatch, small_zones):
    monkeypatch.setenv("QFR_EXPORTS_DIR", str(tmp_path / "exports"))
    fix_engine_seeds(monkeypatch, PLANTED_SEED)
    script = BenchmarkScript(expressions=[], engineer_uses_tool=False, seed=PLANTED_SEED)
    with research_stack(tmp_path, monkeypatch, small_zones, script, BenchmarkModels) as full:
        run = run_benchmark(full, 10, ISLANDS)
        found = discoveries(run)
        lineage = lineage_report(full, run)
        applications = operator_steps(full)
        first = min((p["generation_seq"] for p in found), default=None)
        body = run_body(
            "bm_planted",
            run,
            script,
            discoveries=found,
            generations_to_discovery=first,
            lineage=lineage,
            operator_applications=applications["counts"],
        )
        path = write_results("bm_planted", body, tmp_path)
        summary = body["summary"]

        assert len(run.generations) == 10 and all(g.state == "CLOSED" for g in run.generations)
        assert found, f"no planted factor passed W1; results in {path}"
        assert first is not None and first <= 10
        tracked = [g.tracked_best for g in run.generations if g.tracked_best is not None]
        assert tracked and tracked[-1] > tracked[0], tracked
        # Archive coverage reaches 25% of the cells and stays there (the empty start
        # begins at 0).
        coverage = [g.coverage for g in run.generations]
        reached = next((i for i, c in enumerate(coverage) if c >= COVERAGE_MIN), None)
        assert reached is not None, coverage
        assert all(c >= COVERAGE_MIN for c in coverage[reached:]), coverage
        assert summary["final_coverage"] >= COVERAGE_MIN, summary

        # The deliverable lists the discovery, and its history reaches back to the
        # explore hypothesis that started its lineage.
        assert run.deliverable is not None
        items = {i["version_id"]: i for i in run.deliverable["deliverable"]["items"]}
        delivered = [p for p in found if p["version_id"] in items]
        assert delivered, "the discovery is not in the deliverable"
        history = items[delivered[0]["version_id"]]["iteration_history"]
        roots = [h for h in history["hops"] if not h["from_version_ids"]]
        assert roots and all(h["operator"] == "explore" for h in roots)
        assert all(h["hypothesis_title"].startswith("Benchmark mechanism") for h in roots)

        # TRC-03: every operator application has parents and AST diffs.
        assert applications["missing"] == [], applications["missing"]
        assert set(applications["counts"]) >= {
            "MUTATION_APPLIED",
            "CROSSOVER_APPLIED",
            "SYNTACTIC_MUTATION_APPLIED",
        }, applications["counts"]
        # ... and every published version's history reconstructs every hop of its DAG
        # (the lineage spans are in the results; tests/research/test_lineage.py builds the
        # five-generation lineage with a crossover).
        assert lineage["mismatches"] == [], lineage["mismatches"]
        assert lineage["checked"] == len(run.published)


def test_bm_null(tmp_path, monkeypatch, null_zones):
    generations = int(os.environ.get("QFR_BM_NULL_GENERATIONS", "50"))
    monkeypatch.setenv("QFR_EXPORTS_DIR", str(tmp_path / "exports"))
    fix_engine_seeds(monkeypatch, NULL_SEED)
    script = BenchmarkScript(expressions=[], engineer_uses_tool=False, seed=NULL_SEED)
    with research_stack(tmp_path, monkeypatch, null_zones, script, BenchmarkModels) as full:
        run = run_benchmark(full, generations, ISLANDS)
        body = run_body("bm_null", run, script)
        write_results("bm_null", body, tmp_path)
        summary = body["summary"]
        assert summary["generations"] == generations
        # Recorded, not gated, at Phase 5: acceptance (zero acceptances) is Phase 6.
        assert summary["w1_pass_rate"] is None or 0.0 <= summary["w1_pass_rate"] <= 1.0
