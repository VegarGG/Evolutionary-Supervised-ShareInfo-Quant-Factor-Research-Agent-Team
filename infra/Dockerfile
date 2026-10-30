# syntax=docker/dockerfile:1
FROM postgres:16 AS postgres
# Bake readable initialization files into the image: external Mac volumes can
# expose executable bits on a noexec mount. The official entrypoint sources .sh.
COPY --chmod=0444 infra/postgres/init/ /docker-entrypoint-initdb.d/
USER 999:999

FROM ghcr.io/astral-sh/uv:0.11.19 AS uv
FROM scratch AS wheel-cache
COPY infra/wheel-cache/ /

FROM python:3.12-slim AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/qfr_core/pyproject.toml packages/qfr_core/pyproject.toml
COPY packages/qfr_registry/pyproject.toml packages/qfr_registry/pyproject.toml
COPY packages/qfr_research/pyproject.toml packages/qfr_research/pyproject.toml
COPY packages/qfr_eval/pyproject.toml packages/qfr_eval/pyproject.toml
COPY packages/qfr_mcp/pyproject.toml packages/qfr_mcp/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,from=wheel-cache,target=/wheelhouse \
    if ls /wheelhouse/*.whl >/dev/null 2>&1; then \
      uv venv /app/.venv && \
      uv export --frozen --no-dev --all-packages --no-emit-workspace --format requirements-txt >/tmp/requirements.txt && \
      uv pip sync --python /app/.venv/bin/python --require-hashes --no-index --find-links=/wheelhouse /tmp/requirements.txt; \
    else uv sync --frozen --no-dev --no-install-workspace --all-packages; fi

FROM dependencies AS build
ARG QFR_PACKAGE=qfr-core
COPY packages ./packages
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,from=wheel-cache,target=/wheelhouse \
    uv sync --frozen --no-dev --no-editable --package ${QFR_PACKAGE} --find-links=/wheelhouse

FROM python:3.12-slim AS runtime
RUN groupadd --gid 10001 qfr && useradd --uid 10001 --gid qfr --create-home qfr \
    && mkdir -p /var/log/qfr /app/configs /app/schemas /data/full /data/research \
    && chown -R qfr:qfr /var/log/qfr /data
COPY --from=build /app/.venv /app/.venv
COPY configs/logging.yaml configs/mcp.yaml /app/configs/
COPY configs/research /app/configs/research
COPY configs/public_cards.json /app/configs/public_cards.json
ENV PATH="/app/.venv/bin:$PATH" QFR_CONFIG_DIR=/app/configs QFR_LOG_DIR=/var/log/qfr \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
WORKDIR /app
USER 10001:10001
CMD ["python", "-m", "qfr_core.placeholder"]

FROM runtime AS mcp
COPY schemas/private/owner_evidence.json /app/schemas/owner_evidence.json

FROM dependencies AS migration-build
COPY packages ./packages
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,from=wheel-cache,target=/wheelhouse \
    uv sync --frozen --no-dev --no-editable --all-packages --find-links=/wheelhouse

FROM runtime AS migrate
COPY --from=migration-build /app/.venv /app/.venv
COPY infra/migrations /app/infra/migrations
COPY scripts/migrate.py /app/scripts/migrate.py
CMD ["python", "scripts/migrate.py"]

FROM build AS test-build
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,from=wheel-cache,target=/wheelhouse \
    uv sync --frozen --no-editable --all-packages --find-links=/wheelhouse
COPY tests ./tests
COPY scripts ./scripts
COPY infra ./infra
COPY configs ./configs
COPY schemas ./schemas
COPY .importlinter ./
CMD ["uv", "run", "--frozen", "pytest"]
