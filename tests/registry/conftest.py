import json
from pathlib import Path
from uuid import uuid4

import pytest
from qfr_core.contracts.publication import PublicationRequest
from qfr_core.dsl.language import DSLConfig, analyze, parse
from qfr_registry.policy import RegistryPolicy
from qfr_registry.publication import Principal, Registry
from qfr_registry.storage.objects import PayloadStore


@pytest.fixture
def registry_policy():
    return RegistryPolicy.model_validate_json(
        Path("configs/registry/publication_v1.json").read_bytes()
    )


@pytest.fixture
def registry_service(registry_connect, registry_policy, tmp_path):
    return Registry(
        registry_connect,
        PayloadStore(tmp_path / "registry-payloads"),
        registry_policy,
        {
            profile: DSLConfig.load(Path(f"configs/dsl/{profile}.json"))
            for profile in ("pilot_industry_v1", "stock_daily_v1")
        },
    )


@pytest.fixture
def publisher():
    return Principal(
        "fixture-publisher-" + str(uuid4()), frozenset({"publisher"}), frozenset({"test-program"})
    )


@pytest.fixture
def draft():
    def make(expression="Ref($close,1)"):
        manifest = json.loads(Path("contracts/examples/ArtifactDefinition.valid.json").read_text())
        manifest.update(
            {
                "name": "factor-" + uuid4().hex,
                "family_id": None,
                "parent_version_ids": [],
                "payload_files": [],
            }
        )
        manifest["provenance"]["program_id"] = "test-program"
        manifest["implementation"] = {
            "type": "dsl",
            "language": "qfr-dsl/1",
            "expression": expression,
        }
        config = DSLConfig.load(Path("configs/dsl/pilot_industry_v1.json"))
        analysis = analyze(parse(expression, config), config)
        manifest["complexity"] = analysis.complexity
        manifest["payload"].update(
            {"fields_used": sorted(analysis.fields), "max_lookback_days": analysis.lookback}
        )
        return PublicationRequest.model_validate(
            {
                "publish_key": str(uuid4()),
                "profile": "pilot_industry_v1",
                "manifest": manifest,
                "files": [],
                "content_hash": "f" * 64,
            }
        )

    return make
