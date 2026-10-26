"""Conservative semantic identity and approved development-only equivalence."""

import hashlib
import math

from qfr_core.contracts.artifacts import (
    ArtifactDefinition,
    DSLImplementation,
    FactorPayload,
    PackageImplementation,
    PythonImplementation,
)
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.dsl.language import DSLConfig, analyze, canonical_hash, parse

from qfr_eval.scheduler.models import DevelopmentBehavior, IntakeCampaign, PilotScreeningPolicy


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def verify_publication(artifact: PublishedArtifact, dsl_configs: dict[str, DSLConfig]) -> None:
    definition = {key: getattr(artifact.manifest, key) for key in ArtifactDefinition.model_fields}
    body = ArtifactDefinition.model_validate(definition).model_dump(
        mode="json", exclude={"family_id"}
    )
    expected = digest(
        {
            "hash_spec": "qfr-publication/1",
            "profile": artifact.profile,
            "dsl_policy_hash": artifact.dsl_policy_hash,
            "manifest": body,
        }
    )
    if expected != artifact.manifest.content_hash or expected != artifact.payload_digest:
        raise ValueError("registry publication hash mismatch")
    manifest = artifact.manifest
    if manifest.implementation_fingerprint != digest(
        {
            "implementation": manifest.implementation.model_dump(mode="json"),
            "payloads": [f.model_dump(mode="json") for f in manifest.payload_files],
        }
    ):
        raise ValueError("registry implementation fingerprint mismatch")
    if isinstance(manifest.implementation, DSLImplementation):
        config = dsl_configs.get(artifact.profile)
        if config is None or not isinstance(manifest.payload, FactorPayload):
            raise ValueError("DSL policy unavailable")
        expression = manifest.implementation.expression
        analysis = analyze(parse(expression, config), config)
        if (
            artifact.dsl_policy_hash != digest(config.model_dump(mode="json"))
            or manifest.canonical_fingerprint != canonical_hash(expression, config)
            or manifest.complexity != analysis.complexity
            or set(manifest.payload.fields_used) != analysis.fields
            or manifest.payload.max_lookback_days != analysis.lookback
        ):
            raise ValueError("registry parsed declaration mismatch")
    elif manifest.canonical_fingerprint is not None or artifact.dsl_policy_hash is not None:
        raise ValueError("non-DSL publication has an unsupported canonical declaration")


def semantic_scope(artifact: PublishedArtifact, campaign: IntakeCampaign) -> str:
    manifest = artifact.manifest
    implementation = manifest.implementation
    execution = (
        implementation.execution_contract.model_dump(mode="json")
        if isinstance(implementation, (PackageImplementation, PythonImplementation))
        else None
    )
    payload = manifest.payload.model_dump(mode="json")
    if manifest.kind.value == "factor":
        # Human descriptions and the expression's spelling are not semantic keys;
        # the registry's parsed canonical fingerprint binds the actual computation.
        payload.pop("formulation")
        payload.pop("mechanism_card")
    elif manifest.kind.value == "model":
        # A display description cannot bypass same-runtime/output dedup by
        # renaming a model. Frozen weights and preprocessing remain declared.
        payload.pop("specification")
    return digest(
        {
            "identity_spec": "qfr-intake-semantics/1",
            "profile": artifact.profile,
            "program": manifest.provenance.program_id,
            "kind": manifest.kind.value,
            "payload": payload,
            "parameters": manifest.parameters,
            "data_requirements": [r.model_dump(mode="json") for r in manifest.data_requirements],
            "cycles": manifest.cycles,
            "output_schema_ref": manifest.output_schema_ref,
            "execution": execution,
            "dsl_policy_hash": artifact.dsl_policy_hash,
            "protocol_hash": campaign.protocol_hash,
            "snapshot_id": campaign.snapshot_id,
            "runtime_hash": campaign.runtime_hash,
            "screening_policy_hash": campaign.screening_policy_hash,
        }
    )


def equivalent(
    candidate: DevelopmentBehavior, reference: DevelopmentBehavior, policy: PilotScreeningPolicy
) -> bool:
    if (
        candidate.semantic_scope_sha256 != reference.semantic_scope_sha256
        or candidate.score_columns != reference.score_columns
        or candidate.tables.keys() != reference.tables.keys()
        or not any(table.rows for table in candidate.tables.values())
    ):
        return False
    for name, left in candidate.tables.items():
        right = reference.tables[name]
        if (
            left.columns != right.columns
            or left.dtypes != right.dtypes
            or len(left.rows) != len(right.rows)
        ):
            return False
        for a_row, b_row in zip(left.rows, right.rows, strict=True):
            for column, a, b in zip(left.columns, a_row, b_row, strict=True):
                if a is None or b is None:
                    if a is not None or b is not None:
                        return False
                elif (
                    column in candidate.score_columns[name]
                    and isinstance(a, (int, float))
                    and isinstance(b, (int, float))
                ):
                    if (
                        not math.isfinite(a)
                        or not math.isfinite(b)
                        or abs(a - b) > policy.score_atol + policy.score_rtol * abs(b)
                    ):
                        return False
                elif a != b:
                    return False
    return True
