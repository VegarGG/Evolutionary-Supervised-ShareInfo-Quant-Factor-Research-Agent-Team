"""Explicit GET-only feedback launch; never starts an evaluation or release worker."""

import argparse
import os
from collections.abc import Mapping
from pathlib import Path

import psycopg
import uvicorn
from fastapi import FastAPI
from qfr_core.access import BearerAuthority
from qfr_core.contracts.services import FeedbackServiceConfiguration
from qfr_core.service_runtime import (
    database_arguments,
    database_identity,
    load_contract,
    server_arguments,
)
from qfr_core.signatures import EvidenceVerifier

from qfr_eval.feedback.app import create_app
from qfr_eval.feedback.reads import FeedbackReader


def application(config: FeedbackServiceConfiguration, environment: Mapping[str, str]) -> FastAPI:
    authority = BearerAuthority(config.authentication, environment)
    verifier = EvidenceVerifier(config.verification)
    credentials = database_arguments(config.database, environment, "feedback")

    def connect() -> psycopg.Connection:
        return psycopg.connect(**credentials)

    with connect() as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            if conn.execute(
                "SELECT current_user,current_database()"
            ).fetchone() != database_identity("feedback"):
                raise PermissionError("feedback database identity differs")
            conn.execute("SELECT id FROM feedback.delivery_receipts_v LIMIT 0")
    return create_app(
        FeedbackReader(connect, config.policy, verifier=verifier), authority=authority
    )


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    args = parser.parse_args(arguments)
    try:
        config = load_contract(args.configuration, FeedbackServiceConfiguration)
        app = application(config, os.environ)
    except (ValueError, OSError, PermissionError, psycopg.Error) as error:
        parser.exit(1, "feedback startup refused: " + type(error).__name__ + "\n")
    uvicorn.run(app, **server_arguments(config.server))


if __name__ == "__main__":
    main()
