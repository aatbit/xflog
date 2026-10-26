# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc AS uv
FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS base

FROM base AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

FROM base AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    HOME=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GRADIO_ANALYTICS_ENABLED=False \
    GRADIO_TEMP_DIR=/tmp/gradio \
    HF_HOME=/tmp/huggingface \
    XFLOG_HOST=0.0.0.0 \
    XFLOG_PORT=7860 \
    XFLOG_DATABASE=/data/history.sqlite3
RUN groupadd --gid 10001 xflog \
    && useradd --uid 10001 --gid xflog --no-create-home --home-dir /data --shell /usr/sbin/nologin xflog \
    && install -d -m 0700 -o xflog -g xflog /data
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
USER 10001:10001
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=6s --start-period=30s --retries=3 CMD ["python", "-m", "xflog.healthcheck"]
CMD ["python", "-m", "xflog"]
