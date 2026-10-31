"""Research notes (PLAN Sections 7.6 and 8.10, P8.2): a third artifact kind with
deterministic output-quality checks only.

A note is published to the registry like any version, with no lineage and no pool. The
evaluator checks it at intake: its length against the protocol's limits, that every
cited report was released, that every claim restates a released number within half the
rounding step it was released at, and that it never names the holdout window. The
result is released at once as a note report; the note is never screened or measured.
"""

from typing import Any

import pytest
import yaml
from qfr_core.ids import uuid7
from qfr_eval.configs import activate_version, create_version
from qfr_eval.notes import claim_matches, released_number

from tests.eval.eval_rig import PROTOCOL
from tests.registry_rig import factor_manifest, headers

pytestmark = pytest.mark.postgres


def note_manifest(
    cited: list[str],
    claims: list[dict[str, Any]],
    markdown: str = "# Research note\n\nThe factor's released W1 values.\n",
    name: str = "generation-1-note",
) -> dict[str, Any]:
    generation = str(uuid7())
    return {
        "schema_version": "1",
        "kind": "research_note",
        "family_id": None,
        "name": name,
        "title": "Research note, generation 1",
        "implementation": {
            "language": "qfr-note/1",
            "markdown": markdown,
            "cited_report_ids": cited,
            "claims": claims,
        },
        "provenance": {
            "job_id": str(uuid7()),
            "program_id": str(uuid7()),
            "generation_id": generation,
            "agent_runs": [],
            "trace_ref": generation,
            "qfr_core_version": "0.1.0",
        },
    }


def released_w1(rig) -> Any:
    response = rig.registry.publish(factor_manifest("timed", "Pct($close, 20)"))
    assert response.status_code == 201, response.text
    version_id = response.json()["version"]["version_id"]
    rig.cycle()
    rig.release.tick()
    (row,) = rig.db.rows(
        "SELECT report_id, content FROM eval.released_reports WHERE version_id = :v "
        "AND report_type = 'w1'",
        v=version_id,
    )
    return row


def checked(rig, manifest: dict[str, Any]) -> tuple[str, dict[str, Any] | None, Any]:
    response = rig.registry.publish(manifest)
    assert response.status_code == 201, response.text
    version_id = response.json()["version"]["version_id"]
    rig.cycle(rounds=1)
    rig.release.tick()
    intake = rig.db.rows(
        "SELECT state, reason_code FROM eval.intake WHERE version_id = :v", v=version_id
    )[0]
    reports = rig.db.rows(
        "SELECT report_type, content FROM eval.released_reports WHERE version_id = :v",
        v=version_id,
    )
    note = [r.content for r in reports if r.report_type == "note"]
    return intake.state, (note[0] if note else None), reports


def claim(report_id: Any, field: str, value: float) -> dict[str, Any]:
    return {"report_id": str(report_id), "field": field, "value": value}


def test_a_note_that_restates_released_values_passes(rig):
    w1 = released_w1(rig)
    content = w1.content
    claims = [
        # Within half the RankIC step (0.005) of the released value.
        claim(w1.report_id, "rankic_mean", content["rankic_mean"] + 0.002),
        claim(w1.report_id, "decay_profile.5", content["decay_profile"]["5"]),
        claim(w1.report_id, "complexity", content["complexity"]),
    ]
    state, note, reports = checked(rig, note_manifest([str(w1.report_id)], claims))
    assert state == "NoteChecked"
    assert note == {
        "type": "note", "status": "PASS", "checks": [], "citations": 1, "claims": 3,
        "claims_matched": 3, "failed_claims": [],
    }  # fmt: skip
    # Only the note report: no screening, no W1, nothing measured.
    assert [r.report_type for r in reports] == ["note"]
    assert not rig.db.rows("SELECT 1 FROM eval.queue_jobs WHERE version_id IN (SELECT "
                           "version_id FROM eval.intake WHERE kind = 'research_note')")  # fmt: skip


def test_each_failed_check_is_named_with_the_claims_that_failed(rig):
    w1 = released_w1(rig)
    rankic = w1.content["rankic_mean"]
    never_released = str(uuid7())
    claims = [
        claim(w1.report_id, "rankic_mean", rankic),  # matches
        claim(w1.report_id, "rankic_mean", rankic + 0.01),  # two steps away
        claim(w1.report_id, "w3_rankic", 0.02),  # W1 reports release no such number
        claim(w1.report_id, "flags", 1.0),  # released, but not a number
        claim(never_released, "rankic_mean", 0.03),  # its report was never released
    ]
    markdown = "# Note\n\nThe W3 window probably agrees.\n"
    state, note, _ = checked(
        rig, note_manifest([str(w1.report_id), never_released], claims, markdown)
    )
    assert state == "NoteFailed" and note is not None
    assert note["status"] == "FAIL"
    assert note["checks"] == [
        "CITATION_UNKNOWN", "CLAIM_FIELD_UNKNOWN", "CLAIM_MISMATCH", "UNDISCLOSED_WINDOW",
    ]  # fmt: skip
    assert note["failed_claims"] == [1, 2, 3, 4] and note["claims_matched"] == 1
    event = rig.db.rows(
        "SELECT payload FROM eval.events WHERE action = 'note_checked' ORDER BY at DESC"
    )[0]
    mismatch = [d for d in event.payload["detail"] if d["check"] == "CLAIM_MISMATCH"]
    assert mismatch == [
        {"check": "CLAIM_MISMATCH", "claim": 1, "claimed": rankic + 0.01, "released": rankic,
         "step": 0.005},
    ]  # fmt: skip


@pytest.mark.parametrize(
    "markdown",
    ["The holdout agrees.", "Hold-out results look fine.", "On w3 it held up."],
)
def test_naming_the_holdout_window_fails(rig, markdown):
    w1 = released_w1(rig)
    _, note, _ = checked(rig, note_manifest([str(w1.report_id)], [], markdown))
    assert note is not None and note["checks"] == ["UNDISCLOSED_WINDOW"]


def activate(rig, version: str, change) -> None:
    rig.scheduler.tick()
    raw = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    raw["version"] = version
    change(raw)
    now = rig.clock.now()
    with rig.db.transaction() as conn:
        created, _ = create_version(conn, "protocol", yaml.safe_dump(raw), "test", "r", now)
        activate_version(conn, "protocol", created.id, created.version, "test", None, "r", now)


def test_length_limits_come_from_the_active_protocol(rig):
    w1 = released_w1(rig)
    activate(rig, "test-short-notes", lambda raw: raw["research_note"].update(
        max_markdown_chars=40, max_claims=1))  # fmt: skip
    claims = [claim(w1.report_id, "rankic_mean", w1.content["rankic_mean"])] * 2
    _, note, _ = checked(rig, note_manifest([str(w1.report_id)], claims, "x" * 41))
    assert note is not None and note["checks"] == ["LENGTH_LIMIT"]
    assert note["claims_matched"] == 2  # the claims themselves are right


def test_a_protocol_without_notes_refuses_them_as_an_unsupported_kind(rig):
    w1 = released_w1(rig)

    def without_notes(raw: dict[str, Any]) -> None:
        raw["supported_kinds"] = ["factor", "strategy"]
        del raw["research_note"]

    activate(rig, "test-no-notes", without_notes)
    state, note, reports = checked(rig, note_manifest([str(w1.report_id)], []))
    assert (state, note) == ("IntakeRejected", None)
    assert [(r.report_type, r.content["reasons"]) for r in reports] == [
        ("intake", ["KIND_UNSUPPORTED"])
    ]


def test_the_registry_publishes_notes_without_lineage_or_pools(rig):
    manifest = note_manifest([str(uuid7())], [])
    response = rig.registry.publish(manifest)
    assert response.status_code == 201, response.text
    version = response.json()["version"]
    assert version["kind"] == "research_note"
    assert version["analysis"] == {"markdown_chars": len(manifest["implementation"]["markdown"]),
                                   "citations": 1, "claims": 0}  # fmt: skip
    assert rig.registry.publish(manifest).json()["created"] is False  # idempotent on content
    lineage = rig.registry.client.get(
        f"/v1/artifacts/{version['version_id']}/lineage", headers=headers("evaluator")
    ).json()
    assert lineage["edges"] == [] and lineage["nodes"][0]["operator"] == "note"
    # Notes come from research jobs only: the control token publishes setup imports.
    refused = rig.registry.publish(note_manifest([str(uuid7())], [], name="other"), "control")
    assert refused.status_code == 403 and refused.json()["error"] == "CONTROL_SEEDS_ONLY"


def test_released_numbers_and_rounding_tolerance():
    content = {"rankic_mean": 0.03, "decay_profile": {"5": 0.02}, "library_empty": True,
               "status": "PASS", "max_library_correlation": None}  # fmt: skip
    assert released_number(content, "rankic_mean") == 0.03
    assert released_number(content, "decay_profile.5") == 0.02
    assert released_number(content, "decay_profile.20") is None
    assert released_number(content, "library_empty") is None  # booleans are not numbers
    assert released_number(content, "status") is None
    assert released_number(content, "max_library_correlation") is None
    assert claim_matches(0.0325, 0.03, 0.005) and not claim_matches(0.0326, 0.03, 0.005)
    assert claim_matches(7, 7.0, None) and not claim_matches(7.01, 7.0, None)
