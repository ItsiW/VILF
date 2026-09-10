# VILF admin app image, built by .github/workflows/deploy.yaml and run on Cloud Run.
#
# Python version: every native dependency in uv.lock (pillow, pillow-heif,
# psycopg-binary, uvloop, httptools) ships a cp314 manylinux wheel today. If a
# future dependency bump has no 3.14 wheel, switch the tag below to
# ghcr.io/astral-sh/uv:python3.12-bookworm-slim (requires-python is >=3.12;
# .python-version stays 3.14 for local dev).
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first so the layer is cached until the lock changes.
# pyproject has [tool.uv] package = false, so there is no project to install
# and --no-install-project would be a no-op.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

# Everything else (see .dockerignore for what stays out).
COPY . .

ENV PATH=/app/.venv/bin:$PATH

# Cloud Run sends traffic to 8080; the port is fixed here, PORT from .env is a local-only default.
# app/main.py (FastAPI `app`) is written by the app package.
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
