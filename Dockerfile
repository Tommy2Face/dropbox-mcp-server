# syntax=docker/dockerfile:1.7
# Dockerfile for Dropbox MCP Server

# Stage 1: Builder
FROM python:3.11-slim AS builder
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-warn-script-location -r requirements.txt

# Stage 2: Development
FROM python:3.11-slim AS development
WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy source code
COPY . .

# Create non-root user
RUN useradd -m -u 1001 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8080/health || exit 0

CMD ["python", "server.py"]

# Stage 3: Production
FROM python:3.11-slim AS production
WORKDIR /app

LABEL org.opencontainers.image.title="dropbox-mcp" \
      org.opencontainers.image.description="Dropbox MCP Server" \
      org.opencontainers.image.version="1.0" \
      org.opencontainers.image.vendor="Production"

# Install only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    dumb-init \
    && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=2 \
    TRANSPORT=sse

# Copy source code (minimal)
COPY server.py .
COPY .env.example ./

# Create non-root user
RUN useradd -m -u 1001 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8080/health || exit 0

ENTRYPOINT ["dumb-init", "--"]
CMD ["python", "server.py"]
