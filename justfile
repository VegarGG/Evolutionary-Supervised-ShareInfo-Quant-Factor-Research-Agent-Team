set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

check:
    uv run --locked ruff check .
    uv run --locked ruff format --check .
    uv run --locked mypy
    uv run --locked lint-imports
    uv run --locked python scripts/generate_schemas.py
    uv run --locked python scripts/build_public_cards.py
    git diff --exit-code -- schemas configs/public_cards.json
    uv run --locked python scripts/check_licenses.py

test:
    uv run --locked pytest

test-db:
    uv run --locked python scripts/test_database.py

build:
    uv run --locked python scripts/generate_schemas.py
    uv run --locked python scripts/build_public_cards.py
    docker compose --env-file .env -f infra/docker-compose.yml build

# The evaluator records the git commit and the eval image id in every official record.
up:
    QFR_GIT_SHA="$(git rev-parse HEAD 2>/dev/null || echo unversioned)" \
    QFR_EVAL_IMAGE_DIGEST="$(docker image inspect --format '{{{{.Id}}}}' qfr-v2-eval:phase3 2>/dev/null || echo unpinned)" \
    docker compose --env-file .env -f infra/docker-compose.yml up -d

down:
    docker compose --env-file .env -f infra/docker-compose.yml down

init-secrets:
    uv run --locked python scripts/ops.py init-secrets

setup:
    uv run --locked qfr setup

doctor:
    uv run --locked python scripts/doctor.py

data-build *args:
    docker compose --env-file .env -f infra/docker-compose.yml run --rm data-ingest qfr data build {{args}}

# One daily-ingest check now (e.g. `just data-serve-once --force`), outside the schedule.
data-serve-once *args:
    docker compose --env-file .env -f infra/docker-compose.yml run --rm data-ingest qfr data serve --once {{args}}

# EVL-04: re-run an official record with its pinned inputs and compare the results hash.
eval-reproduce record_id:
    docker compose --env-file .env -f infra/docker-compose.yml run --rm eval-worker qfr eval reproduce {{record_id}}

# Draft the next epoch by Section 10.6 into configs/epochs/<epoch_id>.yaml for review: W0
# runs to the old W2's end, W1 is the old W3, W2 and W3 come from the newer data with the
# embargoes (e.g. `just epoch-propose epoch_002`). It changes nothing in the database; the
# rollover itself is qfr.ops.rollover_epoch with the owner's ROLLOVER R-<epoch_id>.
epoch-propose epoch_id *args:
    test ! -e configs/epochs/{{epoch_id}}.yaml || { echo "configs/epochs/{{epoch_id}}.yaml exists"; exit 1; }
    docker compose --env-file .env -f infra/docker-compose.yml run --rm --no-deps -T eval-scheduler qfr eval epoch propose --epoch-id {{epoch_id}} {{args}} > configs/epochs/.{{epoch_id}}.draft
    mv configs/epochs/.{{epoch_id}}.draft configs/epochs/{{epoch_id}}.yaml
    cat configs/epochs/{{epoch_id}}.yaml

# What a rollover to configs/epochs/<epoch_id>.yaml would do now (restarts, cancelled jobs,
# re-measurements, the research cutoff); changes nothing.
epoch-plan epoch_id:
    docker compose --env-file .env -f infra/docker-compose.yml run --rm --no-deps -T eval-scheduler qfr eval epoch plan --epoch-id {{epoch_id}}

# Check every configured model: listed, priced, tool and json_object output, thinking, and
# the Moonshot concurrency and balance. Runs inside research-worker, the only service with
# provider keys. Each probe call is a small paid request recorded in the budget ledger.
llm-probe trigger="manual":
    docker compose --env-file .env -f infra/docker-compose.yml exec -T research-worker qfr llm probe --trigger {{trigger}}

# Write trace.json and iteration_history.md for one published version to exports/traces.
trace-export version_id:
    mkdir -p exports/traces
    docker compose --env-file .env -f infra/docker-compose.yml exec -T research-api qfr trace export {{version_id}} --out /tmp/traces
    docker compose --env-file .env -f infra/docker-compose.yml cp research-api:/tmp/traces/{{version_id}} exports/traces/{{version_id}}

# Re-check an export bundle written by qfr.deliverable.export: every SHA-256 in
# MANIFEST.sha256 and every JSON file against its published schema (SC8).
export-verify path:
    uv run --locked qfr export verify {{path}}

logs *args:
    docker compose --env-file .env -f infra/docker-compose.yml exec -T qfr-mcp qfr logs {{args}}

mcp-config:
    uv run --locked python scripts/ops.py mcp-config

# One backup now, in the running backup service (Section 17.5); the nightly backup runs
# after 02:30 Asia/Shanghai on its own. Writes backups/<date>/ and prints its SHA256SUMS.
backup:
    docker compose --env-file .env -f infra/docker-compose.yml exec -T backup qfr-backup now

# Restore the newest backup into a throwaway Compose project and run BND-01, REG-01 and
# EVL-04 on it. The report is written to exports/restore-drill/ and logged.
restore-drill:
    uv run --locked python scripts/restore_drill.py

# A new owner MCP token: the old one stops working when qfr-mcp is recreated.
rotate-mcp-token:
    uv run --locked python scripts/ops.py rotate-mcp-token
    docker compose --env-file .env -f infra/docker-compose.yml up -d qfr-mcp

# The Section 18.3 benchmarks (BM-PLANTED, BM-NULL, BM-DECAY, BM-STRATEGY) on the
# synthetic worlds, offline with the scripted LLM, against the disposable test database as
# in test-db (or the one CI's environment names). Results are written to exports/benchmarks.
bench *args:
    mkdir -p exports/benchmarks
    if [ -n "${QFR_TEST_RESEARCH_DB_URL:-}" ]; then \
        QFR_BENCHMARK_DIR=exports/benchmarks uv run --locked pytest -m benchmark tests/benchmarks -q {{args}}; \
    else \
        QFR_BENCHMARK_DIR=exports/benchmarks uv run --locked python scripts/test_database.py -m benchmark tests/benchmarks -q {{args}}; \
    fi
