"""The generation's research note (Phase 8, P8.2): built deterministically from the final
interpretations, within the active protocol's limits."""

from qfr_core.contracts import NoteImplementation
from qfr_core.ids import uuid7
from qfr_research.notes import TRUNCATED, Interpretation, NoteLimits, build_note

from tests.research.scripted import CAVEATS

LIMITS = NoteLimits(max_markdown_chars=20000, max_claims=100, max_citations=100)


def interpretation(reports, claims=(), status="final", **extra):
    body = {
        "report_ids": [str(r) for r in reports],
        "what_was_tested": "One factor on the W1 window.",
        "observed": "A released RankIC mean of 0.03.",
        "diagnosis": "Conjecture: reversal.",
        "implications": [],
        "next_steps": ["Try a neighbouring horizon."],
        "confidence": "low",
        "caveats": CAVEATS,
        "claims": [{"report_id": str(r), "field": f, "value": v} for r, f, v in claims],
    } | extra
    return Interpretation(str(uuid7()), status, body)


def test_the_note_collects_each_interpretation_and_its_claims():
    a, b = uuid7(), uuid7()
    stray = uuid7()  # a claim about a report the interpretation did not read is dropped
    items = [
        interpretation([a], [(a, "rankic_mean", 0.03), (stray, "rankic_mean", 0.05)]),
        interpretation([a, b], [(b, "decay_profile.5", 0.02)], status="amended",
                       amended_text="The decay is faster than stated."),
    ]  # fmt: skip
    note = build_note(3, items, LIMITS)
    assert note is not None
    implementation = NoteImplementation.model_validate(note)
    assert implementation.cited_report_ids == [a, b]
    assert [(c.report_id, c.field, c.value) for c in implementation.claims] == [
        (a, "rankic_mean", 0.03),
        (b, "decay_profile.5", 0.02),
    ]
    markdown = implementation.markdown
    assert markdown.startswith("# Research note: generation 3")
    assert markdown.count("## One factor on the W1 window.") == 2
    assert "Diagnosis (conjecture): Conjecture: reversal." in markdown
    assert "Amended on review: The decay is faster than stated." in markdown
    assert f"`{a}`" in markdown


def test_limits_bound_citations_claims_and_length():
    reports = [uuid7() for _ in range(3)]
    items = [interpretation([r], [(r, "rankic_mean", 0.01)] * 2) for r in reports]
    note = build_note(1, items, NoteLimits(max_markdown_chars=300, max_claims=3,
                                           max_citations=2))  # fmt: skip
    assert note is not None
    assert note["cited_report_ids"] == [str(r) for r in reports[:2]]
    assert len(note["claims"]) == 3
    assert len(note["markdown"]) == 300 and note["markdown"].endswith(TRUNCATED)
    NoteImplementation.model_validate(note)


def test_nothing_to_say_publishes_nothing():
    assert build_note(1, [], LIMITS) is None
    assert NoteLimits.from_card({"protocol_id": "cn_csi300_daily"}) is None
    assert NoteLimits.from_card(
        {"research_note": {"max_markdown_chars": 10, "max_claims": 1, "max_citations": 1}}
    ) == NoteLimits(10, 1, 1)
