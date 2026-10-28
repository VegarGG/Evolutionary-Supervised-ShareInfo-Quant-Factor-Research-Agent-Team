"""Explicit evaluator-only credential references; no numerical imports."""

import os
from pathlib import Path

from psycopg.conninfo import make_conninfo


def connection_dsn(*, migration: bool = False) -> str:
    role = "postgres" if migration else "eval_rw"
    password = Path(os.environ["QFR_EVAL_PASSWORD_FILE"]).read_text().strip()
    if not password:
        raise ValueError("empty evaluator credential")
    return make_conninfo(os.environ["QFR_EVAL_DSN"], user=role, dbname="eval_db", password=password)
