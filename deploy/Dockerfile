# ── SkillPool V4.3 Dockerfile ────────────────────────────────────
# Multi-stage build: builder + runtime
# docker build -f deploy/Dockerfile -t skillpool:4.3.0 .
# ──────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ──
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
COPY pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir --upgrade pip build && \
    python -m build --wheel --no-isolation

# ── Stage 2: Runtime ──
FROM python:3.12-slim

# Non-root user for security
RUN groupadd -r skillpool && useradd -r -g skillpool -d /data -s /sbin/nologin skillpool

WORKDIR /app

# Install from built wheel
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

# Create data directory
RUN mkdir -p /data && chown skillpool:skillpool /data

# Environment defaults
ENV SKILLPOOL_HOST=0.0.0.0 \
    SKILLPOOL_PORT=8000 \
    SKILLPOOL_DATA_DIR=/data \
    SKILLPOOL_LOG_LEVEL=INFO

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

USER skillpool

EXPOSE 8000

VOLUME ["/data"]

ENTRYPOINT ["skillpool-mcp"]
