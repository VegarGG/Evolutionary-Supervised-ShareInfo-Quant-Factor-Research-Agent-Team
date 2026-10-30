"""Explicit quarantine transport launch; no database, signer or source execution."""

import argparse
import os
import sqlite3
from collections.abc import Mapping
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from qfr_core.access import BearerAuthority
from qfr_core.contracts.services import IntakeServiceConfiguration
from qfr_core.service_runtime import load_contract, server_arguments

from qfr_eval.ingest.intake_app import create_app
from qfr_eval.ingest.quarantine import Quarantine


def application(config: IntakeServiceConfiguration, environment: Mapping[str, str]) -> FastAPI:
    authority = BearerAuthority(config.authentication, environment)
    return create_app(
        Quarantine(config.quarantine_root, config.policy, config.readonly_import_mounts),
        authority=authority,
    )


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    args = parser.parse_args(arguments)
    try:
        config = load_contract(args.configuration, IntakeServiceConfiguration)
        app = application(config, os.environ)
    except (ValueError, OSError, PermissionError, sqlite3.Error) as error:
        parser.exit(1, "intake startup refused: " + type(error).__name__ + "\n")
    uvicorn.run(app, **server_arguments(config.server))


if __name__ == "__main__":
    main()
