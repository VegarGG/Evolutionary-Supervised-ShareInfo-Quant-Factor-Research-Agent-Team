set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# Harness checks are offline; provider experiments have separate explicit commands.
harness-check:
    uv run --project harness --locked ruff check harness
    uv run --project harness --locked ruff format --check harness
    node --check harness/dsh-plugin/index.js
    node --check harness/dsh-plugin/client.js
    node --check harness/dsh-plugin/research.js
    node --check harness/dsh-plugin/native-models.js
    node --check harness/dsh-plugin/adaptive.js
    uv run --project harness --locked python scripts/check_licenses.py

harness-test:
    uv run --project harness --locked pytest -c harness/pyproject.toml harness/tests -q

harness-ui:
    PYTHONPATH=harness/src uv run --project harness --locked python harness/scripts/start_ui.py --install-plugin

# Explicit operator launch; every model request still waits for an authorized window.
harness-research-ui *args:
    PYTHONPATH=harness/src uv run --project harness --locked python harness/scripts/start_research_ui.py {{args}}

harness-data-plan *args:
    PYTHONPATH=harness/src uv run --project harness --locked python harness/scripts/data_pilot.py {{args}}

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

up:
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

logs *args:
    docker compose --env-file .env -f infra/docker-compose.yml exec -T qfr-mcp qfr logs {{args}}

mcp-config:
    uv run --locked python scripts/ops.py mcp-config

backup:
    uv run --locked python scripts/ops.py deferred backup Phase7

bench:
    uv run --locked python scripts/ops.py deferred bench Phase5
