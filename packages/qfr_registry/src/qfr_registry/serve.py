"""Explicit authenticated Registry launch; all publication remains through its API."""

import argparse
import os
from collections.abc import Mapping
from pathlib import Path

import psycopg
import uvicorn
from fastapi import FastAPI
from qfr_core.contracts.services import RegistryServiceConfiguration
from qfr_core.dsl.language import DSLConfig
from qfr_core.service_runtime import (
    database_arguments,
    database_identity,
    load_contract,
    server_arguments,
)

from qfr_registry.api.app import create_app
from qfr_registry.auth import StaticTokenAuthorizer
from qfr_registry.policy import RegistryPolicy, RegistryReadPolicy
from qfr_registry.publication import Registry
from qfr_registry.storage.objects import PayloadStore


def application(config: RegistryServiceConfiguration, environment: Mapping[str, str]) -> FastAPI:
    authority = StaticTokenAuthorizer(config.authentication, environment)
    credentials = database_arguments(config.database, environment, "registry")
    policy = load_contract(config.publication_policy_file, RegistryPolicy)
    read_policy = load_contract(config.read_policy_file, RegistryReadPolicy)
    dsl = {
        profile: load_contract(path, DSLConfig) for profile, path in config.dsl_policy_files.items()
    }

    def connect() -> psycopg.Connection:
        return psycopg.connect(**credentials)

    with connect() as conn:
        if conn.execute("SELECT current_user,current_database()").fetchone() != database_identity(
            "registry"
        ):
            raise PermissionError("registry database identity differs")
        conn.execute("SELECT id,published_seq FROM registry.artifact_versions LIMIT 0")
    return create_app(
        Registry(connect, PayloadStore(config.payload_root), policy, dsl),
        authorize=authority,
        read_policy=read_policy,
    )


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    args = parser.parse_args(arguments)
    try:
        config = load_contract(args.configuration, RegistryServiceConfiguration)
        app = application(config, os.environ)
    except (ValueError, OSError, PermissionError, psycopg.Error) as error:
        parser.exit(1, "registry startup refused: " + type(error).__name__ + "\n")
    uvicorn.run(app, **server_arguments(config.server))


if __name__ == "__main__":
    main()
