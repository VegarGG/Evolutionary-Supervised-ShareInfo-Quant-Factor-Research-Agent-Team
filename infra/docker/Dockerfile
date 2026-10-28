FROM ghcr.io/astral-sh/uv:0.11.19@sha256:b46b03ddfcfbf8f547af7e9eaefdf8a39c8cebcba7c98858d3162bd28cf536f6 AS uv
FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS builder
COPY --from=uv /uv /usr/local/bin/uv
ARG QFR_PACKAGE
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY LICENSE NOTICE ADDITIONAL-PERMISSION.md THIRD-PARTY-NOTICES.md ./
COPY packages ./packages
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package "${QFR_PACKAGE}"

FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
ARG QFR_PACKAGE
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
# Docker's private named volume inherits this directory's ownership and mode.
# Only the opt-in controller and evaluator worker mount that volume.
RUN mkdir -p /run/qfr-sandbox && chown 65532:65532 /run/qfr-sandbox && chmod 0700 /run/qfr-sandbox
# New data volumes inherit the trusted ingester's ownership at first creation.
# Research services mount only the research volume, read-only; no host chmod.
RUN mkdir -p /data/full /data/research && chown 65532:65532 /data/full /data/research && chmod 0750 /data/full /data/research
USER 65532:65532
CMD ["python", "-c", "print('QFR Stage 0 service stub; no jobs, scheduling, evaluation or LLM calls.')"]
