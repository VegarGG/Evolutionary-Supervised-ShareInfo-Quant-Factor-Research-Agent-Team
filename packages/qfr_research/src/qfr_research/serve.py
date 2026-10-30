"""Explicit Research API launch; startup neither admits jobs nor runs research."""

import argparse
import os
from collections.abc import Mapping
from pathlib import Path

import psycopg
import uvicorn
from fastapi import FastAPI
from qfr_core.access import BearerAuthority
from qfr_core.contracts.services import ResearchServiceConfiguration
from qfr_core.registry_client import RegistryClient
from qfr_core.service_client import PublicServiceClient
from qfr_core.service_runtime import (
    database_arguments,
    database_identity,
    load_contract,
    server_arguments,
)
from qfr_core.signatures import EvidenceVerifier

from qfr_research.api.app import create_app
from qfr_research.api.evidence import EvidenceGateway, ProgramServices
from qfr_research.api.exports import Exports
from qfr_research.api.storage import Storage


def application(config: ResearchServiceConfiguration, environment: Mapping[str, str]) -> FastAPI:
    authority = BearerAuthority(config.authentication, environment)
    credentials = database_arguments(config.database, environment, "research")
    verifier = EvidenceVerifier(config.verification)
    clients = {
        item.program_id: ProgramServices(
            RegistryClient.from_environment(item.registry, environment),
            PublicServiceClient.from_environment(item.feedback, environment),
            PublicServiceClient.from_environment(item.intake, environment),
        )
        for item in config.backends
    }
    if not config.research_root.is_dir():
        raise ValueError("research-only snapshot volume unavailable")

    def connect() -> psycopg.Connection:
        return psycopg.connect(**credentials)

    with connect() as conn:
        if conn.execute("SELECT current_user,current_database()").fetchone() != database_identity(
            "research"
        ):
            raise PermissionError("research database identity differs")
        # Operator applies migrations separately. Startup performs no schema writes.
        conn.execute("SELECT id,active_delivery_proposal_id FROM research.research_jobs LIMIT 0")
        conn.execute("SELECT id FROM research.export_records LIMIT 0")
    service = Exports(
        Storage(connect, config.policy), EvidenceGateway(clients, verifier), config.research_root
    )
    return create_app(service, authority=authority)


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    args = parser.parse_args(arguments)
    try:
        config = load_contract(args.configuration, ResearchServiceConfiguration)
        app = application(config, os.environ)
    except (ValueError, OSError, PermissionError, psycopg.Error) as error:
        parser.exit(1, "research startup refused: " + type(error).__name__ + "\n")
    uvicorn.run(app, **server_arguments(config.server))


if __name__ == "__main__":
    main()
