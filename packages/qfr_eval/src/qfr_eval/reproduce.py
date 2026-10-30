"""`qfr eval reproduce <record_id>` (PLAN Section 8.9, EVL-04).

Re-runs an official record with its pinned inputs (the version's manifest, the protocol
version, the epoch's windows, the data snapshot, the seed and, for W1, the exact library
files) and compares the recomputed results hash with the stored one. It writes nothing.
"""

import json
import os
from typing import Annotated, Any
from uuid import UUID

import typer
from qfr_core.config import RuntimeSettings
from qfr_core.contracts import FactorManifest
from sqlalchemy import text

from qfr_eval.configs import EvalError, resolved_windows
from qfr_eval.plugins import results_hash
from qfr_eval.runtime import Database, EvalConfig, EvalEnvironment, eval_config
from qfr_eval.store import ArtifactStore
from qfr_eval.worker import Evaluator, LibraryMember, MarketCache, make_runner

app = typer.Typer(no_args_is_help=True, help="Evaluation operations (evaluation side).")


def reproduce(
    db: Database,
    env: EvalEnvironment,
    config: EvalConfig,
    record_id: UUID,
    evaluator: Evaluator | None = None,
) -> dict[str, Any]:
    with db.read() as conn:
        record = conn.execute(
            text("SELECT * FROM eval.official_records WHERE record_id = :r"), {"r": record_id}
        ).first()
        if record is None:
            raise EvalError(404, "RECORD_NOT_FOUND", "no official record with this id")
        intake = conn.execute(
            text("SELECT manifest FROM eval.intake WHERE version_id = :v"),
            {"v": record.version_id},
        ).first()
        protocol: dict[str, Any] = conn.execute(
            text("SELECT config FROM eval.protocols WHERE id = :id AND version = :v"),
            {"id": record.protocol_id, "v": record.protocol_version},
        ).scalar_one()
        epoch: dict[str, Any] = conn.execute(
            text("SELECT config FROM eval.epochs WHERE epoch_id = :e"), {"e": record.epoch_id}
        ).scalar_one()
    if intake is None:
        raise EvalError(409, "VERSION_UNKNOWN", "the record's version has no intake row")
    manifest = FactorManifest.model_validate(intake.manifest["manifest"])
    windows = resolved_windows(epoch)
    library_spec = (record.summary.get("library") or {}).get("members") or []
    library = [LibraryMember(m["version_id"], m["uri"], m["sha256"]) for m in library_spec]
    if evaluator is None:
        store = ArtifactStore(env.store_dir)
        evaluator = Evaluator(env, make_runner(config, store), MarketCache(env.full_snapshot_dir))
    outcome = evaluator.evaluate(
        manifest,
        str(record.version_id),
        dict(protocol),
        windows,
        record.snapshot_id,
        library,
        config.runner.load_cpu_seconds,
        seed=int(record.seed),
    )
    stage = outcome.screening if record.stage == "screening" else outcome.w1
    actual = None if stage is None else results_hash(stage.metrics)
    return {
        "record_id": str(record_id),
        "version_id": str(record.version_id),
        "stage": record.stage,
        "snapshot_id": record.snapshot_id,
        "seed": int(record.seed),
        "expected_results_hash": record.results_hash,
        "actual_results_hash": actual,
        "match": actual == record.results_hash,
    }


@app.command("reproduce")
def reproduce_command(
    record_id: Annotated[str, typer.Argument(help="Official record id")],
) -> None:
    """Re-run an official record with its pinned inputs and compare the results hash."""
    settings = RuntimeSettings(service="eval-reproduce", zone="eval")
    env = EvalEnvironment.from_env(os.environ, settings)
    try:
        result = reproduce(
            Database(os.environ.get("EVAL_DB_URL", "")), env, eval_config(settings.config_dir),
            UUID(record_id),
        )  # fmt: skip
    except (EvalError, ValueError) as error:
        typer.echo(
            json.dumps({"status": "error", "error": type(error).__name__, "message": str(error)})
        )
        raise typer.Exit(1) from None
    typer.echo(
        json.dumps(result | {"status": "ok" if result["match"] else "mismatch"}, sort_keys=True)
    )
    if not result["match"]:
        raise typer.Exit(2)
