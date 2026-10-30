"""eval_db (P3.1): insert-only evidence, immutable configuration and epochs, and the
feedback views as the only thing feedback_ro can read (INV-4, INV-5, INV-7)."""

import pytest
from sqlalchemy import create_engine, text

from tests.registry_rig import database_url

pytestmark = pytest.mark.postgres

INSERT_ONLY = (
    "data_snapshots", "public_cards", "fingerprints", "quota_usage", "runs", "metrics",
    "series_files", "official_records", "trial_ledger", "released_reports", "events",
)  # fmt: skip
VIEWS = ("released_reports_v", "artifact_status_v", "library_v", "protocol_card_v",
         "policy_card_v")  # fmt: skip


def refused(url: str, sql: str, match: str) -> None:
    engine = create_engine(url)
    try:
        with pytest.raises(Exception, match=match):
            with engine.begin() as conn:
                conn.execute(text(sql))
    finally:
        engine.dispose()


@pytest.mark.parametrize("table", INSERT_ONLY)
def test_evidence_tables_are_insert_only_for_the_evaluator(table):
    """UPDATE and DELETE are refused; TRUNCATE is checked in the catalog, because it waits
    for the table lock that other tests' open transactions hold."""
    url = database_url("EVAL")
    engine = create_engine(url)
    with engine.connect() as conn:
        column = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'eval' "
                "AND table_name = :t ORDER BY ordinal_position LIMIT 1"
            ),
            {"t": table},
        ).scalar_one()
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not conn.execute(
                text("SELECT has_table_privilege(current_user, :t, :p)"),
                {"t": f"eval.{table}", "p": privilege},
            ).scalar_one()
        triggers = set(
            conn.execute(
                text(
                    "SELECT tgname FROM pg_trigger WHERE tgrelid = CAST(:t AS regclass) "
                    "AND NOT tgisinternal AND tgenabled = 'O'"
                ),
                {"t": f"eval.{table}"},
            ).scalars()
        )
    engine.dispose()
    # Even the owner is stopped by the triggers.
    assert {f"{table}_immutable", f"{table}_no_truncate"} <= triggers
    for sql in (f"UPDATE eval.{table} SET {column} = {column}", f"DELETE FROM eval.{table}"):
        refused(url, sql, "permission denied")


def test_configuration_and_epochs_are_immutable_once_written(rig):
    rig.scheduler.tick()  # bootstraps the shipped versions and activates the epoch
    for sql, match in (
        ("UPDATE eval.protocols SET config = '{}'::jsonb", "immutable|invalid configuration"),
        ("DELETE FROM eval.release_policies", "permission denied|never deleted"),
        ("UPDATE eval.quotas SET yaml = 'x'", "immutable|invalid configuration"),
        ("UPDATE eval.epochs SET snapshot_id = repeat('b', 64)", "immutable"),
        ("UPDATE eval.protocols SET status = 'draft', activated_at = NULL", "invalid"),
    ):
        with pytest.raises(Exception, match=match):
            with rig.db.transaction(lock=False) as conn:
                conn.execute(text(sql))


def test_feedback_reader_sees_the_views_and_nothing_else():
    engine = create_engine(database_url("FEEDBACK"))
    try:
        with engine.connect() as conn:
            for view in VIEWS:
                conn.execute(text(f"SELECT * FROM feedback.{view} LIMIT 1")).all()
        for sql in (
            "SELECT * FROM eval.released_reports LIMIT 1",
            "SELECT * FROM eval.official_records LIMIT 1",
            "SELECT * FROM eval.release_queue LIMIT 1",
            "DELETE FROM feedback.library_v",
            "CREATE TABLE feedback.x (a int)",
        ):
            refused(database_url("FEEDBACK"), sql, "permission denied")
    finally:
        engine.dispose()
