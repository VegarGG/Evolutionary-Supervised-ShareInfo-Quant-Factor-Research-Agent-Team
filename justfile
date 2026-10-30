set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

check:
    uv run --locked ruff check .
    uv run --locked ruff format --check .
    uv run --locked mypy
    uv run --locked lint-imports
    uv run --locked python scripts/generate_schemas.py
    uv run --locked python scripts/build_public_cards.py
    git diff --exit-code -- schemas configs/public_cards.json

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
