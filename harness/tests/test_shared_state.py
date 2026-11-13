from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from qfh.shared_state import Board, CandidateDefinition, Episode, Finding, Revision


def episode(ident="test-episode"):
    policy = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "configs/shared-state.yaml").read_text()
    )
    return Episode(
        episode_id=ident,
        category="diagnostic",
        synthetic_evidence=True,
        actors={"author": "author", "reviewer": "reviewer", "supervisor": "supervisor"},
        sources={"source": "Data are released after the close. Revenue is in thousands."},
        initial=CandidateDefinition(
            name="Test",
            expression="revenue / cap",
            input_units="Both in units",
            availability_rule="Period end",
            signal_rule="Period close",
            execution_rule="Next observation",
            universe="Synthetic listing",
            hypothesis="An unmeasured test hypothesis",
        ),
        policy=policy,
    )


def finding(board, statement="Use release time", **changes):
    return Finding.model_validate(
        {
            "candidate_id": board.snapshot("author")["head"]["id"],
            "topic": "timing",
            "statement": statement,
            "status": "supported",
            "citations": [{"evidence_id": "source", "quote": "released after the close"}],
            "contradicts": [],
            **changes,
        }
    )


def revision(board, **changes):
    state = board.snapshot("author")
    return Revision.model_validate(
        {
            "parent_id": state["head"]["id"],
            "definition": {
                **state["head"]["body"]["definition"],
                "availability_rule": "Actual release time",
            },
            "decisions": [
                {"finding_id": e["id"], "disposition": "adopt", "reason": "Release timing matters"}
                for e in state["findings"]
                if e["body"]["candidate_id"] == state["head"]["id"]
            ],
            "citations": [{"evidence_id": "source", "quote": "released after the close"}],
            "rationale": "Correct information availability",
            "unresolved": [],
            **changes,
        }
    )


def test_peer_contribution_revision_and_restart_preserve_every_version(tmp_path):
    board = Board.create(tmp_path, episode())
    original = board.snapshot("author")["head"]
    contribution = board.publish("reviewer", finding(board))
    child = board.revise("author", revision(board))
    state = Board(tmp_path).snapshot("supervisor")
    assert state["head"] == child and state["versions"][0] == original
    assert child["body"]["peer_finding_ids"] == [contribution["id"]]
    assert child["body"]["changed_fields"] == ["availability_rule"]
    assert len(state["events"]) == 3
    assert Board.create(tmp_path, episode()).snapshot("author") == state


def test_missing_unseen_or_invented_excerpt_is_refused(tmp_path):
    b = Board.create(tmp_path, episode())
    with pytest.raises(ValidationError, match="source excerpts"):
        finding(b, citations=[])
    for citation in (
        {"evidence_id": "foreign", "quote": "released"},
        {"evidence_id": "source", "quote": "available at period end"},
    ):
        with pytest.raises(ValueError, match="authorized episode source"):
            b.publish("reviewer", finding(b, citations=[citation]))
    with pytest.raises(ValueError, match="principal"):
        b.publish("invented-agent", finding(b))
    with pytest.raises(ValueError, match="principal"):
        b.revise("reviewer", revision(b))
    assert len(b.snapshot("author")["events"]) == 1


def test_conflicts_stay_visible_and_must_be_disposed_explicitly(tmp_path):
    b = Board.create(tmp_path, episode())
    first = b.publish(
        "author", finding(b, statement="Use period end", status="hypothesis", citations=[])
    )
    second = b.publish("reviewer", finding(b, contradicts=[first["id"]]))
    with pytest.raises(ValueError, match="every finding"):
        b.revise("author", revision(b, decisions=[]))
    decisions = [
        {"finding_id": first["id"], "disposition": "reject", "reason": "Release is later."},
        {
            "finding_id": second["id"],
            "disposition": "adopt",
            "reason": "Source supports release timing.",
        },
    ]
    child = b.revise("author", revision(b, decisions=decisions))
    assert child["body"]["decisions"] == decisions
    assert len(b.snapshot("reviewer")["findings"]) == 2


def test_stale_concurrent_and_cross_episode_writes_are_refused(tmp_path):
    b = Board.create(tmp_path / "one", episode())
    other = Board.create(tmp_path / "two", episode("other"))
    with pytest.raises(ValueError, match="outside this episode"):
        other.publish("reviewer", finding(b))
    edit = revision(b)

    def attempt(_):
        try:
            return Board(tmp_path / "one").revise("author", edit)["id"]
        except ValueError as e:
            assert "stale parent" in str(e)
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert len([i for i in results if i]) == 1
    with pytest.raises(ValueError, match="stale parent"):
        b.revise("author", edit)


def test_noop_forged_decision_and_tampered_history_are_refused(tmp_path):
    b = Board.create(tmp_path, episode())
    before = b.snapshot("author")["head"]["body"]["definition"]
    with pytest.raises(ValueError, match="definition field"):
        b.revise("author", revision(b, definition={**before, "name": "Renamed"}))
    with pytest.raises(ValueError, match="exact parent"):
        b.revise(
            "author",
            revision(
                b,
                decisions=[
                    {"finding_id": "a" * 64, "disposition": "adopt", "reason": "Invented peer"}
                ],
            ),
        )
    path = tmp_path / "event-000001.json"
    path.write_text(path.read_text().replace("Period end", "Release date"))
    with pytest.raises(ValueError, match="integrity"):
        Board(tmp_path).snapshot("author")


def test_allowances_stop_repeated_review_and_manifest_cannot_be_replaced(tmp_path):
    spec = episode()
    spec = spec.model_copy(update={"policy": spec.policy.model_copy(update={"max_findings": 1})})
    b = Board.create(tmp_path, spec)
    b.publish("reviewer", finding(b))
    with pytest.raises(ValueError, match="allowance"):
        b.publish("reviewer", finding(b))
    with pytest.raises(ValueError, match="immutable"):
        Board.create(tmp_path, episode("different"))
