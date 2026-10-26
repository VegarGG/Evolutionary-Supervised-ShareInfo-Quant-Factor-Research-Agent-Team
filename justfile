set shell := ["bash", "-euo", "pipefail", "-c"]

check:
    uv run --locked --all-packages ruff check .
    uv run --locked --all-packages ruff format --check .
    uv run --locked --all-packages mypy
    uv run --locked --all-packages lint-imports
    uv run --locked --all-packages python -m scripts.generate_contracts --check
    uv run --locked --all-packages python -m scripts.generate_eval_contracts --check
    uv run --locked --all-packages python -m scripts.check_licenses

test:
    uv run --locked --all-packages python -m pytest

up:
    uv run --locked --all-packages python scripts/local_secrets.py
    docker compose --env-file configs/deployment.env -p qfr-stage0 -f infra/docker-compose.yml up -d --wait postgres

down:
    docker compose --env-file configs/deployment.env -p qfr-stage0 -f infra/docker-compose.yml down

build-images:
    bash scripts/build_images.sh

local-ci:
    bash scripts/local_ci.sh

schemas:
    uv run --locked --all-packages python -m scripts.generate_contracts
