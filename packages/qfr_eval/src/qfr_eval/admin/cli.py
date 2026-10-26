"""Local evaluator-owner commands; no HTTP admin surface or research tool exists."""

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.conninfo import make_conninfo
from qfr_core.configuration import load_yaml
from qfr_core.data_layer.snapshots import Snapshot

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.cluster_job import cluster_job
from qfr_eval.db import migrate
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.protocols.store import activate_protocol, create_protocol
from qfr_eval.records import EvaluationRequest
from qfr_eval.screening.command import run_command
from qfr_eval.service import evaluate


def connection_dsn(*, migration: bool = False) -> str:
    role = "postgres" if migration else "eval_rw"
    # Deliberately explicit files; never a model/provider credential or environment dump.
    path = Path(os.environ["QFR_EVAL_PASSWORD_FILE"])
    password = path.read_text().strip()
    if not password:
        raise ValueError("empty evaluator credential")
    return make_conninfo(os.environ["QFR_EVAL_DSN"], user=role, dbname="eval_db", password=password)


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("migrate")
    digest = sub.add_parser("protocol-hash")
    digest.add_argument("file", type=Path)
    create = sub.add_parser("protocol-create")
    create.add_argument("file", type=Path)
    activate = sub.add_parser("protocol-activate")
    activate.add_argument("protocol_id")
    activate.add_argument("version")
    activate.add_argument("--expected-hash", required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--snapshot", type=Path, required=True)
    run.add_argument("--evidence-root", type=Path, required=True)
    cluster = sub.add_parser("cluster-trials")
    cluster.add_argument("--request", type=Path, required=True)
    cluster.add_argument("--evidence-root", type=Path, required=True)
    for action in ("intake-poll", "screen-one"):
        command = sub.add_parser(action)
        command.add_argument("--configuration", type=Path, required=True)
        command.add_argument("--principal", required=True)
        if action == "screen-one":
            command.add_argument("--snapshot", type=Path, required=True)
            command.add_argument("--evidence-root", type=Path, required=True)
    for command in (create, activate, run, cluster):
        command.add_argument("--principal", required=True)
        command.add_argument("--request-id", type=UUID, required=True)
    args = parser.parse_args(arguments)
    if args.action == "protocol-hash":
        print(load_yaml(args.file, FrozenProtocol).sha256)
        return
    try:
        if args.action in ("intake-poll", "screen-one"):
            command_result = run_command(
                args.action,
                args.configuration,
                connection_dsn(),
                principal=args.principal,
                snapshot=getattr(args, "snapshot", None),
                evidence_root=getattr(args, "evidence_root", None),
            )
            print(json.dumps(command_result))
            return
        if args.action == "migrate":
            migrate(connection_dsn(migration=True))
            print(json.dumps({"migration": "complete"}))
            return
        with psycopg.connect(connection_dsn(), autocommit=True) as conn:
            if args.action == "cluster-trials":
                clusters = cluster_job(
                    conn,
                    EvaluationRequest.model_validate_json(args.request.read_bytes()),
                    EvidenceStore(args.evidence_root),
                    principal=args.principal,
                    request_id=args.request_id,
                )
                print(clusters.model_dump_json())
                return
            if args.action == "evaluate":
                request = EvaluationRequest.model_validate_json(args.request.read_bytes())
                record, receipt = evaluate(
                    conn,
                    request,
                    Snapshot.load(args.snapshot),
                    EvidenceStore(args.evidence_root),
                    principal=args.principal,
                    request_id=args.request_id,
                )
                print(
                    json.dumps(
                        {
                            "record_id": record.record_id,
                            "status": record.status,
                            "results_hash": record.results_hash,
                            "receipt_hash": receipt.receipt_hash,
                            "authenticity": receipt.authenticity,
                        }
                    )
                )
                return
            if args.action == "protocol-create":
                result = create_protocol(
                    conn, args.file, principal=args.principal, request_id=args.request_id
                )
            else:
                result = activate_protocol(
                    conn,
                    args.protocol_id,
                    args.version,
                    expected_hash=args.expected_hash,
                    principal=args.principal,
                    request_id=args.request_id,
                )
        print(json.dumps({"protocol_sha256": result, "action": args.action}))
    except (psycopg.Error, OSError, KeyError, ValueError, RuntimeError) as error:
        # CLI errors must not render driver frames, conninfo or secret values.
        parser.exit(1, f"evaluator command failed: {type(error).__name__}\n")


if __name__ == "__main__":
    main()
