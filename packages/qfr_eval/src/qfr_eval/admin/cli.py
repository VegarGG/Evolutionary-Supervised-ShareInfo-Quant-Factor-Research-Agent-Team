"""Local evaluator-owner commands; no HTTP admin surface or research tool exists."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

import psycopg

from qfr_eval.credentials import connection_dsn as connection_dsn
from qfr_eval.runtime_bootstrap import bootstrap_cli
from qfr_eval.runtime_contracts import RuntimeCompatibilityError


def main(arguments: list[str] | None = None) -> None:
    try:
        bootstrap_cli(arguments if arguments is not None else sys.argv[1:])
    except RuntimeCompatibilityError as error:
        raise SystemExit("evaluator command refused: " + error.reason) from None
    from qfr_core.configuration import load_yaml
    from qfr_core.contracts.signing import VerificationPolicy
    from qfr_core.data_layer.snapshots import Snapshot
    from qfr_core.signatures import EvidenceVerifier

    from qfr_eval.artifact_store import EvidenceStore
    from qfr_eval.cluster_job import cluster_job
    from qfr_eval.db import migrate
    from qfr_eval.protocols.models import FrozenProtocol
    from qfr_eval.protocols.store import activate_protocol, create_protocol
    from qfr_eval.receipt_signing import sign_measurement_receipt
    from qfr_eval.records import EvaluationRequest, RuntimeIdentity
    from qfr_eval.release.cards import publish_policy_cards
    from qfr_eval.release.publish import publish_ready
    from qfr_eval.release.store import POLICY, activate_policy, create_policy
    from qfr_eval.screening.command import run_command
    from qfr_eval.service import evaluate
    from qfr_eval.signing import EvaluatorSigner

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
    policy_hash = sub.add_parser("policy-hash")
    policy_hash.add_argument("file", type=Path)
    policy_create = sub.add_parser("policy-create")
    policy_create.add_argument("file", type=Path)
    policy_activate = sub.add_parser("policy-activate")
    policy_activate.add_argument("--expected-hash", required=True)
    cards = sub.add_parser("public-cards")
    cards.add_argument("--policy-sha256", required=True)
    release = sub.add_parser("release-ready")
    release.add_argument("--limit", type=int, required=True)
    release.add_argument("--policy-sha256", required=True)
    release.add_argument("--program-id", required=True)
    release.add_argument("--intake-runtime", type=Path)
    sign_receipt = sub.add_parser("sign-receipt")
    sign_receipt.add_argument("--record-id", type=UUID, required=True)
    for command in (release, sign_receipt):
        command.add_argument("--signing-key", type=Path, required=True)
        command.add_argument("--verification-policy", type=Path, required=True)
        command.add_argument("--evidence-root", type=Path, required=True)
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
    for command in (
        create,
        activate,
        run,
        cluster,
        policy_create,
        policy_activate,
        cards,
        release,
        sign_receipt,
    ):
        command.add_argument("--principal", required=True)
        command.add_argument("--request-id", type=UUID, required=True)
    args = parser.parse_args(arguments)
    try:
        if args.action == "protocol-hash":
            print(load_yaml(args.file, FrozenProtocol).sha256)
            return
        if args.action == "policy-hash":
            print(POLICY.validate_json(args.file.read_bytes()).sha256)
            return
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
            if args.action in ("release-ready", "sign-receipt"):
                signer = EvaluatorSigner.from_private_file(
                    args.signing_key, purposes=["released_report", "measurement_receipt"]
                )
                verifier = EvidenceVerifier(
                    VerificationPolicy.model_validate_json(args.verification_policy.read_bytes())
                )
                store = EvidenceStore(args.evidence_root)
                if args.action == "release-ready":
                    runtime = (
                        RuntimeIdentity.model_validate_json(args.intake_runtime.read_bytes())
                        if args.intake_runtime
                        else None
                    )
                    reports = publish_ready(
                        conn,
                        signer,
                        verifier,
                        limit=args.limit,
                        policy_hash=args.policy_sha256,
                        program_id=args.program_id,
                        principal=args.principal,
                        request_id=args.request_id,
                        evidence_store=store,
                        intake_runtime=runtime,
                    )
                    print(json.dumps({"published_report_ids": [r.report_id for r in reports]}))
                else:
                    signed_receipt = sign_measurement_receipt(
                        conn,
                        args.record_id,
                        store,
                        signer,
                        verifier,
                        principal=args.principal,
                        request_id=args.request_id,
                    )
                    print(json.dumps({"signed_record_id": signed_receipt.receipt.record_id}))
                return
            if args.action == "policy-create":
                value = create_policy(
                    conn,
                    POLICY.validate_json(args.file.read_bytes()),
                    principal=args.principal,
                    request_id=args.request_id,
                )
                print(json.dumps({"policy_sha256": value, "action": args.action}))
                return
            if args.action == "policy-activate":
                value = activate_policy(
                    conn,
                    args.expected_hash,
                    principal=args.principal,
                    request_id=args.request_id,
                )
                print(json.dumps({"policy_sha256": value, "action": args.action}))
                return
            if args.action == "public-cards":
                hashes = publish_policy_cards(
                    conn,
                    args.policy_sha256,
                    principal=args.principal,
                    request_id=args.request_id,
                )
                print(json.dumps({"public_card_hashes": hashes, "action": args.action}))
                return
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
    except RuntimeCompatibilityError as error:
        parser.exit(1, "evaluator command refused: " + error.reason + "\n")
    except (psycopg.Error, OSError, KeyError, ValueError, RuntimeError) as error:
        # CLI errors must not render driver frames, conninfo or secret values.
        parser.exit(1, f"evaluator command failed: {type(error).__name__}\n")


if __name__ == "__main__":
    main()
