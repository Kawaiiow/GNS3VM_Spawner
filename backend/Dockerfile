# ==============================================================================
# Multi-stage Dockerfile for FastAPI Backend on AWS ECS (Fargate / EC2)
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build Dependencies
# ------------------------------------------------------------------------------
FROM python:3.14-slim-bookworm AS builder

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Install build dependencies required for compiling any native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ------------------------------------------------------------------------------
# Stage 2: Final Minimal Runtime Image
# ------------------------------------------------------------------------------
FROM python:3.14-slim-bookworm AS runner

LABEL maintainer="GNS3 Cloud Team" \
      description="FastAPI Backend for GNS3 Cloud VM Spawner on AWS ECS"

# Ensure runtime environment variables are set:
# - PYTHONUNBUFFERED=1 ensures logs stream immediately to AWS CloudWatch
# - PYTHONDONTWRITEBYTECODE=1 prevents creating .pyc cache files in container
# - PORT defines the container port (default 8000)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PATH="/opt/venv/bin:$PATH"

# Create a non-root group and user for security compliance (CIS / AWS Well-Architected)
RUN groupadd --system --gid 10001 appgroup && \
    useradd --system --uid 10001 --gid 10001 --no-create-home --shell /sbin/nologin appuser

# Install curl for container healthcheck & ALB / ECS target health verification
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built virtual environment from builder stage
COPY --from=builder --chown=appuser:appgroup /opt/venv /opt/venv

WORKDIR /app

# Copy application source code
COPY --chown=appuser:appgroup app/ ./app/

# Switch to unprivileged user
USER appuser:appgroup

# Expose backend application port
EXPOSE 8000

# Container health check (communicates with FastAPI /health endpoint)
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

# Launch uvicorn server (exec form ensures uvicorn receives SIGTERM for graceful shutdown)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
