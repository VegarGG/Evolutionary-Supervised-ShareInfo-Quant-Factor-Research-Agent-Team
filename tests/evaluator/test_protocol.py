import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from qfr_core.configuration import load_yaml
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.protocols.store import activate_protocol, create_protocol, get_active

CONFIG = Path("configs/evaluation/pilot_p0_p1_verification_v1.yaml")


def test_exact_approved_settings_and_original_oracle_remain_distinct():
    protocol = load_yaml(CONFIG, FrozenProtocol)
    oracle = load_yaml(CONFIG.with_name("pilot_original_oracle.yaml"), FrozenProtocol)
    assert protocol.turnover.top_threshold.hex() == "0x1.6f4d327fbc7bep-1"
    assert protocol.turnover.bottom_threshold.hex() == "0x1.6f5e121519084p-1"
    assert protocol.release_intent.ladder_step.hex() == "0x1.704f37a7b7335p-7"
    assert protocol.windows["development"].end.year == 2022
    assert oracle.windows["development"].end.year == 2023
    assert protocol.windows["confirmation"].access == "locked"
    assert protocol.scope == "P0_P1_verification_only"
    assert protocol.bootstrap.draws == 10000
    assert oracle.bootstrap.draws == 2000 and oracle.bootstrap.seed == 20260101
    assert protocol.release_intent.feedback_versions_per_lineage_generation == 3
    assert protocol.release_intent.confirmation_requires_separate_authorization
    private = Path("packages/qfr_eval/src/qfr_eval/private_contracts")
    schema = json.loads((private / "FrozenProtocol.schema.json").read_text())
    Draft202012Validator(schema).validate(protocol.model_dump(mode="json"))
    assert list(
        Draft202012Validator(schema).iter_errors(
            json.loads((private / "FrozenProtocol.invalid.json").read_text())
        )
    )
    assert "FrozenProtocol" not in json.loads(Path("contracts/public-contracts.json").read_text())


@pytest.mark.parametrize("change", ["overlap", "draws", "turnover", "confirmation", "extra"])
def test_unapproved_or_incomplete_semantics_rejected(change):
    body = load_yaml(CONFIG, FrozenProtocol).model_dump(mode="json")
    if change == "overlap":
        body["windows"]["validation"]["start"] = "2022-01-01"
    elif change == "draws":
        body["bootstrap"]["draws"] = 9999
    elif change == "turnover":
        body["turnover"] = None
    elif change == "confirmation":
        body["windows"]["confirmation"]["access"] = "research"
    else:
        body["unknown"] = "not accepted"
    with pytest.raises(ValidationError):
        FrozenProtocol.model_validate(body)


@pytest.mark.database
def test_activation_hash_idempotency_and_conflict(eval_connect, tmp_path):
    protocol = load_yaml(CONFIG, FrozenProtocol)
    body = protocol.model_dump(mode="json")
    body["protocol_id"] += ":fixture:" + str(uuid4())
    path = tmp_path / "protocol.yaml"
    path.write_text(json.dumps(body))  # JSON is valid YAML, canonical hash is format-independent.
    with eval_connect() as conn:
        digest = create_protocol(conn, path, principal="test-owner", request_id=uuid4())
        assert create_protocol(conn, path, principal="test-owner", request_id=uuid4()) == digest
        with pytest.raises(ValueError, match="not active"):
            get_active(conn, body["protocol_id"], body["version"])
        with pytest.raises(ValueError, match="hash mismatch"):
            activate_protocol(
                conn,
                body["protocol_id"],
                body["version"],
                expected_hash="0" * 64,
                principal="test-owner",
                request_id=uuid4(),
            )
        activate_protocol(
            conn,
            body["protocol_id"],
            body["version"],
            expected_hash=digest,
            principal="test-owner",
            request_id=uuid4(),
        )
        assert get_active(conn, body["protocol_id"], body["version"]).sha256 == digest
        body["atol"] = 1e-11
        path.write_text(json.dumps(body))
        with pytest.raises(ValueError, match="different content"):
            create_protocol(conn, path, principal="test-owner", request_id=uuid4())
