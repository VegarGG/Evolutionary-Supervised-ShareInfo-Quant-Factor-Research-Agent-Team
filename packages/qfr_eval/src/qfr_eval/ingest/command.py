"""Explicit local operator entry; no ingestion scheduler starts on service import."""

import argparse
import json
from pathlib import Path
from uuid import UUID

import psycopg

from qfr_eval.credentials import connection_dsn
from qfr_eval.ingest.models import SnapshotBuildAuthorization, SnapshotBuildPlan
from qfr_eval.ingest.service import ingest_once


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    fingerprint = commands.add_parser("plan-hash")
    fingerprint.add_argument("file", type=Path)
    once = commands.add_parser("once")
    for name in ("plan", "authorization", "source-root", "fixture-root", "output"):
        once.add_argument("--" + name, type=Path, required=True)
    once.add_argument("--principal", required=True)
    once.add_argument("--request-id", type=UUID, required=True)
    args = parser.parse_args(arguments)
    try:
        if args.action == "plan-hash":
            print(SnapshotBuildPlan.model_validate_json(args.file.read_bytes()).sha256)
            return
        plan = SnapshotBuildPlan.model_validate_json(args.plan.read_bytes())
        authorization = SnapshotBuildAuthorization.model_validate_json(
            args.authorization.read_bytes()
        )
        if not authorization.enabled:
            parser.exit(2, "ingest refused: inactive authorization\n")
        with psycopg.connect(
            connection_dsn(), autocommit=True, connect_timeout=10, options="-c lock_timeout=30000"
        ) as conn:
            result = ingest_once(
                conn,
                plan,
                authorization,
                source_root=args.source_root,
                fixtures_root=args.fixture_root,
                output_root=args.output,
                principal=args.principal,
                request_id=args.request_id,
            )
        print(
            json.dumps(
                dict(
                    status="catalog_available",
                    registration_id=result.registration_id,
                    dataset_version_id=result.dataset_version_id,
                    research_snapshot_id=result.research_manifest.snapshot_id,
                )
            )
        )
    except (psycopg.Error, ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, "ingest refused: " + type(error).__name__ + "\n")
