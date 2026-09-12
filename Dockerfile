# Local LLM Studio — application image.
#
# Multistage build to keep the runtime image small (no compilers, no caches).
# Runs uvicorn as an unprivileged user. All configuration comes from env vars
# (see backend/config.py for the full list).

# ── Stage 1: build deps into a wheel cache ──────────────────────────────
FROM python:3.12-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --wheel-dir=/wheels --no-cache-dir -r requirements.txt


# ── Stage 2: minimal runtime ────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Runtime deps only — sqlite (bundled with python), no build tools.
RUN adduser --disabled-password --gecos '' --uid 1000 app \
    && mkdir -p /data /app \
    && chown -R app:app /data /app

WORKDIR /app

# Install wheels from the build stage — no PyPI network calls at runtime.
COPY --from=build /wheels /tmp/wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels -r requirements.txt \
    && rm -rf /tmp/wheels

# Application code.
COPY --chown=app:app backend /app/backend
COPY --chown=app:app static /app/static
COPY --chown=app:app migrations /app/migrations
COPY --chown=app:app scripts /app/scripts
COPY --chown=app:app prompts /app/prompts

# Data (SQLite, uploads, artifacts, backups, token file) lives on a volume
# so the container can be rebuilt without losing state.
ENV STUDIO_DATA_DIR=/data \
    STUDIO_DB_PATH=/data/workspace.db \
    STUDIO_UPLOAD_DIR=/data/uploads \
    STUDIO_ARTIFACTS_DIR=/data/artifacts \
    STUDIO_TOKEN_FILE=/data/token \
    BIND_HOST=0.0.0.0 \
    BIND_PORT=8080 \
    LOG_LEVEL=INFO \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

VOLUME /data
EXPOSE 8080
USER app

# Simple healthcheck: /api/health returns 200 whether or not Ollama is up
# (the endpoint reports Ollama status as a field but doesn't fail the response).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, sys; \
      r = urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3); \
      sys.exit(0 if r.status == 200 else 1)" || exit 1

CMD ["python", "-m", "uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8080"]
