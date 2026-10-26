"""Frozen source identity tests; actual pilot sandbox replay has a separate gate."""

import json
from pathlib import Path

import pytest
from qfr_core.data_layer.snapshots import canonical_json
from qfr_eval.execution_bundle import ArtifactExecutionBundle
from qfr_eval.records import EvaluationRequest, RegistryExecutionBinding

ROOT = Path("packages/qfr_eval/src/qfr_eval/private_contracts")


def test_pre_registry_request_bytes_and_hash_are_unchanged():
    original = json.loads((ROOT / "EvaluationRequest.valid.json").read_bytes())
    request = EvaluationRequest.model_validate(original)
    assert request.registry_execution is None
    assert "registry_execution" not in request.model_dump(mode="json")
    assert canonical_json(request.model_dump(mode="json")) == canonical_json(original)
    # Recorded before adding Registry bindings; not regenerated from implementation.
    assert request.sha256 == "e5c6953ec39dc89e2005d44c054d524684eda2540931fb2455b460a53d2b5c15"


def test_registry_request_cannot_omit_binding_or_relabel_a_builtin():
    original = json.loads((ROOT / "EvaluationRequest.valid.json").read_bytes())
    binding = RegistryExecutionBinding.model_validate_json(
        (ROOT / "RegistryExecutionBinding.valid.json").read_bytes()
    )
    with pytest.raises(ValueError, match="screened execution binding"):
        EvaluationRequest.model_validate({**original, "variant": "registry"})
    with pytest.raises(ValueError, match="screened execution binding"):
        EvaluationRequest.model_validate({**original, "registry_execution": binding})
    request = EvaluationRequest.model_validate(
        {**original, "variant": "registry", "registry_execution": binding}
    )
    assert request.model_dump(mode="json")["registry_execution"] == binding.model_dump(mode="json")
    assert EvaluationRequest.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize("mutation", ["content", "policy", "extra_asset", "encoding"])
def test_frozen_bundle_rejects_changed_publication_policy_or_payloads(mutation):
    body = json.loads((ROOT / "ArtifactExecutionBundle.valid.json").read_bytes())
    assert ArtifactExecutionBundle.model_validate(body).assets() == {}
    if mutation == "content":
        body["artifact"]["manifest"]["name"] += "-changed"
    elif mutation == "policy":
        body["dsl_config"]["max_nodes"] += 1
    else:
        body["payloads_base64"]["unexpected"] = "%%%" if mutation == "encoding" else "eA=="
    with pytest.raises(ValueError):
        ArtifactExecutionBundle.model_validate(body)
