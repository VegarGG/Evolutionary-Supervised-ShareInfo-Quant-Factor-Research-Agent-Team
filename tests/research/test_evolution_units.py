"""Unit tests of the evolutionary engine's deterministic parts (Phase 5, Section 12):
fitness and descriptors, syntactic mutation and subtree crossover, parent selection,
slot allocation, the plan validator and the publication selection. No database."""

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from qfr_core.config import public_protocol_section
from qfr_core.dsl import DslLimits, ast_diff, canonicalize, parse, to_string, validate
from qfr_research.engine import (
    allocate,
    candidate_slots,
    ensure_explore,
    ensure_island_explore,
    evolution_settings,
    explore_task_sizes,
    raise_explore,
    split_slots,
)
from qfr_research.fitness import (
    FitnessInput,
    cell_count,
    descriptors,
    field_group,
    percentile,
    quantile,
    rank_key,
    score,
    w0_input,
    w1_input,
)
from qfr_research.outputs import GenerationPlan, IslandPause, PlanTask
from qfr_research.planning import (
    Proposal,
    assign_variants,
    fit_to_budget,
    stagnation_choices,
    validate_plan,
)
from qfr_research.selection import (
    Screened,
    behavioral_dedup,
    prescreen,
    provisional_fitness,
    select,
)
from qfr_research.settings import ResearchConfig
from qfr_research.variation import (
    Choice,
    derive_seed,
    generator,
    select_parent,
    subtree_crossover,
    syntactic_mutation,
    tournament,
    within_constraints,
)

CONFIG = ResearchConfig.load(Path("configs"))
SETTINGS = evolution_settings(CONFIG.charter_values, {})
LIMITS = DslLimits.from_protocol(public_protocol_section(Path("configs"), "dsl"))
CONSTRAINTS = {"max_nodes": 30, "max_lookback_days": 120}
P1, P2, P3 = (
    "01900000-0000-7000-8000-000000000001",
    "01900000-0000-7000-8000-000000000002",
    "01900000-0000-7000-8000-000000000003",
)


def member(key: str, island: str = "I1", **values: float | None) -> FitnessInput:
    base: dict[str, float | None] = {
        "rankic_ir": 0.2,
        "ls_net_sharpe": 1.0,
        "library_corr": None,
        "monotonicity": 0.5,
        "top_turnover": 0.3,
    }
    base |= values
    return FitnessInput(key=key, island=island, nodes=10, **base)  # type: ignore[arg-type]


# Fitness (Section 12.2) -------------------------------------------------------------------


def test_percentile_is_mid_rank_with_ties_sharing_the_middle():
    assert percentile(1.0, []) == 0.5
    assert percentile(2.0, [1.0, 2.0, 3.0]) == pytest.approx(0.5)
    assert percentile(3.0, [1.0, 2.0, 3.0]) == pytest.approx(5 / 6)
    assert percentile(1.0, [1.0, 1.0]) == pytest.approx(0.5)


def test_fitness_formula_weights_and_empty_library():
    """A lone member sits at the middle of every percentile: 0.5 for each term, and the
    library term is 0.5 because the library is empty."""
    result = score([member("a")], SETTINGS)["a"]
    assert result.value == pytest.approx(0.5)
    assert result.detail["pct"]["library"] == 0.5
    assert result.detail["basis"] == "global"


def test_fitness_ranks_the_better_member_higher_and_uses_island_basis_from_five():
    members = [member(f"m{i}", rankic_ir=0.1 * i) for i in range(1, 6)]
    scored = score(members, SETTINGS)
    values = [scored[f"m{i}"].value for i in range(1, 6)]
    assert values == sorted(values) and values[-1] > values[0]
    assert {s.detail["basis"] for s in scored.values()} == {"island"}
    # Fewer than island_percentile_min members on an island: global percentiles.
    mixed = score([*members[:4], member("x", "I2")], SETTINGS)
    assert mixed["x"].detail["basis"] == "global" and mixed["x"].detail["basis_size"] == 5


def test_fitness_complexity_penalty_and_provisional_factor():
    plain = score([member("a")], SETTINGS)["a"].value
    big = FitnessInput("b", "I1", 0.2, 1.0, None, 0.5, 0.3, nodes=25)
    assert score([big], SETTINGS)["b"].value == pytest.approx(plain - 0.01 * 10)
    provisional = score([member("a")], SETTINGS, provisional=True)["a"]
    assert provisional.value == pytest.approx(plain * 0.5)
    assert provisional.detail["provisional"] is True


def test_w1_multipliers_sign_mismatch_and_w2():
    w1 = {"rankic_ir": 0.3, "ls_net_sharpe": 1.0, "library_empty": True, "flags": []}
    assert w1_input("a", "I1", 1, 5, w1, SETTINGS).multiplier == 1.0
    mismatch = w1_input("a", "I1", 1, 5, w1 | {"flags": ["SIGN_MISMATCH"]}, SETTINGS)
    assert mismatch.multiplier == 0.0 and mismatch.multiplier_reasons == ("SIGN_MISMATCH",)
    assert w1_input("a", "I1", 1, 5, w1, SETTINGS, w2_status="PASS").multiplier == 1.1
    assert w1_input("a", "I1", 1, 5, w1, SETTINGS, w2_status="FAIL").multiplier == 0.5
    # The declared sign adjusts RankIC_IR; an empty library has no library value.
    flipped = w1_input("a", "I1", -1, 5, w1, SETTINGS)
    assert flipped.rankic_ir == -0.3 and flipped.library_corr is None
    with_library = w1_input(
        "a", "I1", 1, 5, w1 | {"library_empty": False, "max_library_correlation": 0.4}, SETTINGS
    )
    assert with_library.value("library") == pytest.approx(0.6)
    assert w0_input("a", "I1", 1, 5, {"rankic_ir": 0.2}, None).library_corr is None


def test_rank_key_breaks_ties_by_originality_then_complexity_then_id():
    keys = sorted(
        [
            ("d", rank_key(0.5, 0.2, 9, "d")),
            ("c", rank_key(0.5, 0.2, 9, "c")),
            ("b", rank_key(0.5, 0.2, 8, "b")),
            ("a", rank_key(0.5, 0.9, 20, "a")),
            ("e", rank_key(0.6, 0.0, 30, "e")),
            ("f", rank_key(None, 1.0, 1, "f")),
        ],
        key=lambda x: x[1],
    )
    assert [k for k, _ in keys] == ["e", "a", "b", "c", "d", "f"]


def test_quantile_matches_numpy_linear_interpolation():
    import numpy as np

    values = [0.1, 0.4, 0.2, 0.9, 0.5]
    assert quantile(values, 0.75) == pytest.approx(float(np.quantile(values, 0.75)))
    assert quantile([], 0.5) == float("inf")


# MAP-Elites descriptors (Section 12.1) ------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "group"),
    [
        ("-Pct($close,5)", "price_only"),
        ("Mean($volume,5)/Mean($volume,20)", "volume_only"),
        ("Sign($ret)*($volume/Mean($volume,20)-1)", "price_volume"),
        ("Std($ret,20)", "range_volatility"),
        ("$high/$low-1", "range_volatility"),
    ],
)
def test_field_group(expression, group):
    fields = validate(expression, LIMITS).analysis.fields  # type: ignore[union-attr]
    assert field_group(expression, fields, SETTINGS) == group


def test_descriptors_best_signed_horizon_and_turnover_bucket():
    w1 = {"decay_profile": {"1": 0.01, "5": 0.03, "10": -0.05, "20": 0.02}, "top_turnover": 0.45}
    d = descriptors("-Pct($close,5)", ["close"], 1, w1, SETTINGS)
    assert d == {
        "horizon": 5,
        "turnover_bucket": 2,
        "field_group": "price_only",
        "cell_key": "h5|t2|price_only",
    }
    # A negative declared sign flips which horizon is best.
    assert descriptors("-Pct($close,5)", ["close"], -1, w1, SETTINGS)["horizon"] == 10
    assert cell_count(SETTINGS) == 64


# Syntactic mutation and subtree crossover (Section 12.4) -------------------------------------


def test_syntactic_mutation_is_deterministic_valid_and_records_its_diff():
    expression = "Mean($close,5)/Mean($close,20)-1"
    seed = derive_seed("program", 3, "syntactic", "I1", 0)
    first = syntactic_mutation(P1, expression, seed, LIMITS, CONSTRAINTS, SETTINGS["variation"])
    again = syntactic_mutation(P1, expression, seed, LIMITS, CONSTRAINTS, SETTINGS["variation"])
    assert first is not None and again is not None
    assert first.as_json() == again.as_json()
    assert first.rule in SETTINGS["variation"]["syntactic_rules"]
    assert first.parent_version_ids == [P1] and first.seed == seed
    parent = canonicalize(parse(expression))
    assert first.expression != to_string(parent)
    assert validate(first.expression, LIMITS).ok
    assert first.ast_diffs == [
        [dict(e) for e in ast_diff(parent, canonicalize(parse(first.expression)))]
    ]
    assert first.ast_diffs[0], "a mutant differs from its parent"


def test_syntactic_mutation_rules_each_produce_valid_variants():
    expression = "Mean($close,10)-Std($close,10)"
    for rule in SETTINGS["variation"]["syntactic_rules"]:
        cfg = SETTINGS["variation"] | {"syntactic_rules": [rule]}
        made = [
            syntactic_mutation(P1, expression, derive_seed(rule, i), LIMITS, CONSTRAINTS, cfg)
            for i in range(5)
        ]
        variants = [v for v in made if v is not None]
        assert variants, rule
        for variant in variants:
            assert variant.rule == rule
            ok, problems, _ = within_constraints(variant.expression, LIMITS, CONSTRAINTS)
            assert ok, (rule, variant.expression, problems)


def test_syntactic_mutation_respects_the_brief_constraints():
    tight = {"max_nodes": 30, "max_lookback_days": 20, "fields_allowed": ["close"]}
    for i in range(20):
        variant = syntactic_mutation(
            P1, "Mean($close,5)", derive_seed("tight", i), LIMITS, tight, SETTINGS["variation"]
        )
        if variant is not None:
            ok, problems, analysis = within_constraints(variant.expression, LIMITS, tight)
            assert ok, problems
            assert analysis.max_lookback_days <= 20 and set(analysis.fields) <= {"close"}


def test_subtree_crossover_takes_a_subtree_from_each_parent():
    parents = [(P1, "Mean($close,5)/Mean($close,20)-1"), (P2, "Sign($ret)*Rank($volume)")]
    seed = derive_seed("program", 4, "crossover", "I2", 0)
    child = subtree_crossover(parents, seed, LIMITS, CONSTRAINTS, SETTINGS["variation"])
    assert child is not None
    assert child == subtree_crossover(parents, seed, LIMITS, CONSTRAINTS, SETTINGS["variation"])
    assert child.operator == "crossover" and child.parent_version_ids == [P1, P2]
    assert len(child.ast_diffs) == 2 and all(child.ast_diffs)
    assert (
        child.details["donor"] in to_string(canonicalize(parse(parents[1][1])))
        or child.details["donor"] in child.expression
    )
    assert child.expression not in {to_string(canonicalize(parse(e))) for _, e in parents}


# Parent selection (Section 12.3) -------------------------------------------------------------


def choices(n: int, island: str = "I1") -> list[Choice]:
    return [
        Choice(f"v{i:02d}", island, 1.0 - i / 100, "official", "-Pct($close,5)", 1, f"c{i}")
        for i in range(n)
    ]


def test_tournament_draws_from_the_top_and_the_best_entrant_wins():
    ranked = choices(15)
    for seed in range(30):
        winner, detail = tournament(generator(seed), ranked, 3, 10)  # type: ignore[misc]
        assert detail["pool_size"] == 10 and len(detail["entrants"]) == 3
        assert all(e in {c.version_id for c in ranked[:10]} for e in detail["entrants"])
        assert winner.version_id == min(detail["entrants"])
    assert tournament(generator(1), [], 3, 10) is None


def test_select_parent_exploits_with_probability_point_seven():
    ranked, archive = choices(12), choices(4, "I2")
    modes = [select_parent(generator(s), ranked, archive, SETTINGS)[1] for s in range(400)]  # type: ignore[index]
    exploit = sum(1 for m in modes if m["rule"] == "tournament") / len(modes)
    assert 0.6 < exploit < 0.8
    assert {m["rule"] for m in modes} == {"tournament", "archive_elite"}
    # An empty side falls back to the other; both empty gives no parent.
    only_archive = select_parent(generator(3), [], archive, SETTINGS)
    assert only_archive is not None and only_archive[1]["rule"] == "archive_elite"
    assert select_parent(generator(3), [], [], SETTINGS) is None


# Slots and the operator mix (Section 12.6) ----------------------------------------------------


def test_allocate_floor_cap_and_quota():
    samples = {"I1": 0.9, "I2": 0.1, "I3": 0.5, "I4": 0.4, "I5": 0.3, "I6": 0.2}
    slots = allocate(12, samples, 1, 0.40)
    assert sum(slots.values()) == 12
    assert min(slots.values()) >= 1 and max(slots.values()) <= 4
    assert slots["I1"] == max(slots.values())
    # Fewer slots than islands: the highest samples get the floor.
    few = allocate(3, samples, 1, 0.40)
    assert sum(few.values()) == 3 and few["I1"] == few["I3"] == few["I4"] == 1
    assert allocate(5, {}, 1, 0.4) == {}


def test_candidate_slots_three_per_publication_within_the_cap():
    publication = {"I1": 4, "I2": 1, "I3": 0}
    slots = candidate_slots(publication, 36, ["I1", "I2", "I3"])
    assert slots == {"I1": 12, "I2": 3, "I3": 1}
    capped = candidate_slots(publication, 10, ["I1", "I2", "I3"])
    assert sum(capped.values()) == 10 and min(capped.values()) >= 1


def test_raise_explore_and_split_slots():
    mix = SETTINGS["operator_mix"]
    raised = raise_explore(mix, 0.40)
    assert raised["explore"] == 0.40 and sum(raised.values()) == pytest.approx(1.0)
    assert raised["llm_mutation"] / raised["crossover"] == pytest.approx(0.35 / 0.15)
    assert raise_explore(raised, 0.30) == raised
    split = split_slots(6, mix)
    assert sum(split.values()) == 6 and split["llm_mutation"] == 2


def test_ensure_explore_keeps_the_generation_share_after_rounding():
    plan = {k: split_slots(1, SETTINGS["operator_mix"]) for k in ("I1", "I2", "I3", "I4")}
    ensure_explore(plan, 0.25)
    total = sum(sum(c.values()) for c in plan.values())
    assert sum(c["explore"] for c in plan.values()) >= 0.25 * total
    assert total == 4
    counts = {"explore": 0, "llm_mutation": 2, "crossover": 1}
    ensure_island_explore(counts, 2)
    assert counts["explore"] == 2 and sum(counts.values()) == 3


def test_explore_task_sizes():
    assert explore_task_sizes(0, 2) == []
    assert explore_task_sizes(1, 2) == [1]
    assert explore_task_sizes(4, 1) == [2, 2]
    assert explore_task_sizes(3, 2) == [2, 1]
    assert explore_task_sizes(7, 1) == [3, 2, 2]


# The plan validator (Sections 11.6 and 12) ----------------------------------------------------


def task(kind: str, island: str = "I1", parents: tuple[str, ...] = (), n: int = 1) -> PlanTask:
    return PlanTask(
        type=kind,  # type: ignore[arg-type]
        island_id=island,  # type: ignore[arg-type]
        brief="A task.",
        parent_version_ids=[UUID(p) for p in parents],
        hypothesis_id=None,
        max_candidates=n,
    )


def plan(tasks: list[PlanTask], pauses: list[str] = ()) -> GenerationPlan:  # type: ignore[assignment]
    allocations: dict[str, int] = {}
    for t in tasks:
        allocations[t.island_id] = allocations.get(t.island_id, 0) + t.max_candidates
    return GenerationPlan(
        objectives=["Test."],
        allocations=allocations,  # type: ignore[arg-type]
        allocation_reasons={},
        tasks=tasks,
        islands_to_pause=[IslandPause(island_id=i, reason="Stagnant.") for i in pauses],  # type: ignore[arg-type]
        rationale="Test.",
    )


def proposal(default: GenerationPlan, **overrides) -> Proposal:
    body = {
        "islands": ["I1", "I2"],
        "allocations": dict(default.allocations),
        "operator_mix": SETTINGS["operator_mix"],
        "parents": [P1, P2, P3],
        "publication_quota": 12,
        "max_slots": 36,
        "min_explore_share": 0.25,
        "compose_strategy_max": 0,
        "default_plan": default,
        "parent_info": {
            P1: {"island": "I1", "status": "official", "offered_as": "llm_mutation"},
            P2: {"island": "I2", "status": "provisional", "offered_as": "crossover"},
            P3: {"island": "I1", "status": "archived", "offered_as": "repair"},
        },
        "selections": [
            {"type": "llm_mutation", "island": "I1", "parent_version_ids": [P1]},
            {"type": "crossover", "island": "I1", "parent_version_ids": [P1, P2]},
        ],
        "variants": [
            {"variant_id": "a", "island": "I1", "parent_version_ids": [P1]},
            {"variant_id": "b", "island": "I1", "parent_version_ids": [P1]},
        ],
        "provisional_parents": [P2],
    }
    return Proposal(**(body | overrides))


def violations(p: GenerationPlan, prop: Proposal) -> list[str]:
    return validate_plan(p, prop, Decimal("100"), Decimal("1")).violations


def test_validator_accepts_a_plan_following_the_proposal():
    good = plan(
        [
            task("explore", "I1", n=2),
            task("llm_mutation", "I1", (P1,), 2),
            task("crossover", "I1", (P1, P2)),
            task("repair", "I1", (P3,)),
            task("syntactic_batch", "I1", (P1,), 2),
            task("explore", "I2", n=2),
        ]
    )
    verdict = validate_plan(good, proposal(good), Decimal("100"), Decimal("1"))
    assert verdict.valid, verdict.violations
    assert verdict.values["llm_tasks"] == 5  # the syntactic batch calls no LLM
    assert assign_variants(good.tasks, proposal(good))[4] == proposal(good).variants


def test_validator_refuses_parents_and_pairs_the_engine_did_not_propose():
    base = plan([task("explore", "I1"), task("explore", "I2")])
    prop = proposal(base)
    stranger = "01900000-0000-7000-8000-0000000000ff"
    cases = {
        "PARENT_NOT_PROPOSED": [task("llm_mutation", "I1", (stranger,))],
        "PARENT_NOT_ELIGIBLE": [task("llm_mutation", "I1", (P3,))],
        "CROSSOVER_PAIR_NOT_PROPOSED": [task("crossover", "I1", (P1, P3))],
        "PARENT_ARITY": [task("crossover", "I1", (P1,))],
        "CROSSOVER_CANDIDATES": [task("crossover", "I1", (P1, P2), 2)],
        "REPAIR_CANDIDATES": [task("repair", "I1", (P3,), 2)],
        "PARENTS_NOT_ALLOWED": [task("explore", "I1", (P1,))],
        "SYNTACTIC_BATCH_WITHOUT_VARIANTS": [task("syntactic_batch", "I1", (P1,), 3)],
    }
    for code, extra in cases.items():
        found = violations(plan([*base.tasks, *extra]), prop)
        assert any(v.startswith(code) for v in found), (code, found)


def test_validator_limits_children_of_a_provisional_parent():
    two = plan(
        [
            task("explore", "I1", n=3),
            task("explore", "I2", n=3),
            task("crossover", "I1", (P1, P2)),
            task("crossover", "I2", (P2, P1)),
        ]
    )
    found = violations(two, proposal(two))
    assert any(v.startswith("PROVISIONAL_PARENT_OVER_LIMIT") for v in found)


def test_validator_slot_cap_explore_share_islands_and_budget():
    tasks = [task("llm_mutation", "I1", (P1,), 3), task("explore", "I2")]
    found = violations(plan(tasks), proposal(plan(tasks), min_explore_share=0.4))
    assert any(v.startswith("EXPLORE_SHARE: 0.25 < 0.40") for v in found), found
    assert not any(
        v.startswith("EXPLORE_SHARE") for v in violations(plan(tasks), proposal(plan(tasks)))
    )
    one_island = plan([task("explore", "I1")])
    assert "ISLAND_WITHOUT_SLOT: I2" in violations(one_island, proposal(one_island))
    over = plan([task("explore", "I1", n=3), task("explore", "I2", n=3)])
    assert any(
        v.startswith("SLOTS_OVER_CAP") for v in violations(over, proposal(over, max_slots=4))
    )
    budget = validate_plan(over, proposal(over), Decimal("1"), Decimal("1"))
    assert any(v.startswith("BUDGET") for v in budget.violations)
    paused = plan([task("explore", "I1"), task("explore", "I2")], pauses=["I2"])
    assert "PAUSED_ISLAND_WITH_TASKS: I2" in violations(paused, proposal(paused))
    moved = plan([task("explore", "I1", n=3), task("explore", "I2")])
    prop = proposal(moved, allocations={"I1": 1, "I2": 1})
    assert any(v.startswith("ALLOCATION_MOVED_TOO_FAR") for v in violations(moved, prop))


def test_validator_requires_a_stagnant_island_to_be_reseeded_or_paused():
    one = plan([task("explore", "I1", n=2), task("explore", "I2", n=2)])
    prop = proposal(one, stagnant_islands=["I2"])
    assert any(v.startswith("STAGNANT_ISLAND_NOT_HANDLED") for v in violations(one, prop))
    assert stagnation_choices(one, prop) == {"I2": "unhandled"}
    reseeded = plan([task("explore", "I1", n=2), task("explore", "I2"), task("explore", "I2")])
    assert not violations(reseeded, proposal(reseeded, stagnant_islands=["I2"]))
    assert stagnation_choices(reseeded, proposal(reseeded, stagnant_islands=["I2"])) == {
        "I2": "reseed"
    }
    paused = plan([task("explore", "I1", n=2)], pauses=["I2"])
    prop = proposal(paused, stagnant_islands=["I2"])
    assert not violations(paused, prop) and stagnation_choices(paused, prop) == {"I2": "pause"}


def test_fit_to_budget_keeps_one_task_per_island_and_every_syntactic_batch():
    full = plan(
        [
            task("explore", "I1"),
            task("llm_mutation", "I1", (P1,)),
            task("syntactic_batch", "I1", (P1,), 2),
            task("explore", "I2"),
        ]
    )
    trimmed = fit_to_budget(full, Decimal("2"), Decimal("1"))
    kinds = [(t.type, t.island_id) for t in trimmed.tasks]
    assert kinds == [("explore", "I1"), ("syntactic_batch", "I1"), ("explore", "I2")]
    assert fit_to_budget(full, Decimal("10"), Decimal("1")) is full


# Pre-screen and selection (Section 12.5) ------------------------------------------------------


class Row:
    def __init__(self, **kw):
        self.candidate_id = kw.get("candidate_id", "c1")
        self.island_key = kw.get("island", "I1")
        self.kind = "factor"
        self.workbench = {"metrics": kw.get("metrics", {})}
        self.similarity = kw.get("similarity", {})
        self.analysis = kw.get("analysis", {"nodes": 5, "max_lookback_days": 20})
        self.payload = {"expected_sign": kw.get("sign", 1)}
        self.expression = kw.get("expression", "-Pct($close,5)")


def test_prescreen_checks_each_threshold_with_its_value():
    thresholds = SETTINGS["prescreen"]
    good = {"coverage": 0.95, "rankic_mean": -0.03, "rankic_ir": -0.3}
    passed = prescreen(
        Row(metrics=good, sign=-1, similarity={"originality": 0.8}), thresholds, CONSTRAINTS
    )
    assert passed.passed and passed.checks["similarity"]["vacuous"] is True
    wrong_sign = prescreen(Row(metrics=good, sign=1), thresholds, CONSTRAINTS)
    assert not wrong_sign.passed and not wrong_sign.checks["rankic"]["passed"]
    similar = prescreen(
        Row(metrics=good, sign=-1, similarity={"max_behavioral_similarity": 0.95}),
        thresholds,
        CONSTRAINTS,
    )
    assert not similar.checks["similarity"]["passed"]
    long = prescreen(
        Row(metrics=good, sign=-1, analysis={"nodes": 40, "max_lookback_days": 250}),
        thresholds,
        CONSTRAINTS,
    )
    assert not long.checks["complexity"]["passed"] and not long.checks["lookback"]["passed"]


def screened(cid: str, island: str, fitness: float, expression: str = "") -> Screened:
    return Screened(cid, island, True, {}, fitness, 0.5, "factor", 5, expression, fitness, {})


def test_select_gives_each_island_its_slots_then_the_best_remaining():
    survivors = [
        screened("a", "I1", 0.9),
        screened("b", "I1", 0.8),
        screened("c", "I1", 0.7),
        screened("d", "I2", 0.2),
        screened("e", "I3", 0.1),
    ]
    chosen, ranks = select(survivors, 4, {"I1": 1, "I2": 1, "I3": 1})
    assert [c.candidate_id for c in chosen] == ["a", "d", "e", "b"]
    assert ranks["a"] == 1 and ranks["e"] == 5
    round_robin, _ = select(survivors, 3, None)
    assert [c.candidate_id for c in round_robin] == ["a", "d", "e"]


def test_publication_rank_is_provisional_fitness_plus_novelty():
    # Section 11.6: the slightly stronger candidate that copies the population's structure
    # ranks below a novel one; the rank score is fitness + novelty_weight * originality.
    strong = {"coverage": 0.95, "rankic_mean": 0.04, "rankic_ir": 0.40}
    weaker = {"coverage": 0.95, "rankic_mean": 0.035, "rankic_ir": 0.35}
    rows = {
        "copy": Row(candidate_id="copy", metrics=strong, similarity={"originality": 0.25}),
        "novel": Row(candidate_id="novel", metrics=weaker, similarity={"originality": 0.9}),
    }
    screened_rows = [prescreen(r, SETTINGS["prescreen"], CONSTRAINTS) for r in rows.values()]
    scored = provisional_fitness(screened_rows, rows, SETTINGS)
    by_id = {x.candidate_id: x for x in scored}
    assert by_id["copy"].fitness > by_id["novel"].fitness
    weight = SETTINGS["selection"]["novelty_weight"]
    for x in scored:
        assert x.rank_score == pytest.approx(x.fitness + weight * x.originality)
    assert [x.candidate_id for x in sorted(scored, key=Screened.key)] == ["novel", "copy"]


def test_behavioral_dedup_keeps_the_better_ranked_twin():
    ranked = [
        screened("a", "I1", 0.9, "x"),
        screened("b", "I1", 0.8, "x2"),
        screened("c", "I2", 0.7, "y"),
    ]
    similarity = {frozenset({"x", "x2"}): 0.95, frozenset({"x", "y"}): 0.2}
    kept, dropped = behavioral_dedup(
        ranked, lambda a, b: similarity.get(frozenset({a, b}), 0.1), 0.9
    )
    assert [k.candidate_id for k in kept] == ["a", "c"]
    assert dropped["b"]["candidate_id"] == "a" and dropped["b"]["similarity"] == 0.95
