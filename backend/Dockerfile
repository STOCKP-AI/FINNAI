# MarketMood API image for the Render free web service (render.yaml) and, later, Cloud Run.
# Build context: the repository root (the workspace lockfile lives there).
#   docker build -f backend/Dockerfile -t marketmood-api .
#   docker run --rm -p 10000:10000 --env-file backend/.env marketmood-api

FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Dependencies first (cached layer): only the files the lockfile needs.
COPY pyproject.toml uv.lock ./
COPY ml/pyproject.toml ml/pyproject.toml
COPY backend/pyproject.toml backend/pyproject.toml
RUN uv sync --package marketmood-backend --locked --no-dev --no-install-workspace
# Then the API code, installed as a normal (non-editable) package.
COPY backend/app backend/app
RUN uv sync --package marketmood-backend --locked --no-dev --no-editable

FROM python:3.12-slim-bookworm
RUN useradd --create-home --uid 10001 app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /home/app
USER app
EXPOSE 10000
# Render sets PORT (default 10000). Proxy headers are handled by the app itself
# (TRUST_PROXY_HEADERS / PROXY_HOPS), so uvicorn must not rewrite the client address.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --no-proxy-headers --no-server-header --timeout-graceful-shutdown 20"]
