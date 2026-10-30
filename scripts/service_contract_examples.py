"""Structural launch examples with references only, never deployable credentials."""

from pathlib import Path
from uuid import UUID

from qfr_core.contracts import services as s
from qfr_core.contracts.access import PublicServiceClientConfiguration, ServiceAuthentication
from qfr_core.contracts.feedback import FeedbackReadPolicy
from qfr_core.contracts.mcp import MCPBackendBinding, MCPPolicy
from qfr_core.contracts.publication import (
    RegistryAuthenticationConfiguration,
    RegistryClientConfiguration,
)
from qfr_core.contracts.research import ResearchApiPolicy
from qfr_core.contracts.signing import VerificationPolicy
from qfr_core.contracts.transfers import IntakeTransportPolicy


def examples(root: Path, existing):
    def pick(kind):
        return next(value for value in existing if isinstance(value, kind))

    def auth(audience):
        return ServiceAuthentication(
            revision=1,
            audience=audience,
            minimum_token_bytes=32,
            maximum_token_bytes=256,
            bindings=[
                dict(
                    principal="schema-example",
                    token_ref="env:EXAMPLE_TOKEN",
                    roles=["reader"],
                    programs=[str(UUID(int=30))],
                )
            ],
        )

    server = s.HTTPServerConfiguration.model_validate_json(
        (root / "configs/research/http_server_v1.json").read_bytes()
    )
    database = s.ServiceDatabaseConfiguration(
        revision=1,
        host="postgres",
        port=5432,
        password_ref="env:EXAMPLE_DB_PASSWORD",
        connect_timeout_seconds=5,
    )
    research = s.ResearchBackendBinding(
        program_id=UUID(int=30),
        registry=pick(RegistryClientConfiguration),
        feedback=pick(PublicServiceClientConfiguration),
        intake=pick(PublicServiceClientConfiguration),
    )
    return [
        server,
        database,
        research,
        s.ResearchServiceConfiguration(
            schema_version="1",
            server=server,
            database=database,
            authentication=auth("research"),
            policy=pick(ResearchApiPolicy),
            verification=pick(VerificationPolicy),
            research_root=Path("/data/research"),
            backends=[research],
        ),
        s.MCPServiceConfiguration(
            schema_version="1",
            server=server,
            authentication=auth("mcp"),
            policy=pick(MCPPolicy),
            export_policy=pick(ResearchApiPolicy),
            verification=pick(VerificationPolicy),
            backends=[pick(MCPBackendBinding)],
        ),
        s.IntakeServiceConfiguration(
            schema_version="1",
            server=server,
            authentication=auth("intake"),
            policy=pick(IntakeTransportPolicy),
            quarantine_root=Path("/data/quarantine"),
            readonly_import_mounts={},
        ),
        s.FeedbackServiceConfiguration(
            schema_version="1",
            server=server,
            database=database,
            authentication=auth("feedback"),
            policy=pick(FeedbackReadPolicy),
            verification=pick(VerificationPolicy),
        ),
        s.RegistryServiceConfiguration(
            schema_version="1",
            server=server,
            database=database,
            authentication=pick(RegistryAuthenticationConfiguration),
            publication_policy_file=Path("/etc/qfr/policies/registry/publication_v1.json"),
            read_policy_file=Path("/etc/qfr/policies/registry/read_v1.json"),
            dsl_policy_files={
                "pilot_industry_v1": Path("/etc/qfr/policies/dsl/pilot_industry_v1.json")
            },
            payload_root=Path("/artifacts"),
        ),
    ]
