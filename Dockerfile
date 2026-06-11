# syntax=docker/dockerfile:1.7
#
# MemoGraph web backend image.
#
# Build:    docker build -t memograph:dev .
# Run:      docker run --rm -p 8000:8000 \
#               -v $(pwd)/vault:/data/vault \
#               -e MEMOGRAPH_VAULT=/data/vault \
#               memograph:dev
#
# Layers are arranged so that source-only changes do not invalidate the
# pip-install layer. requirements.lock (Phase 0.5) will provide hash-pinned
# installs once it's generated; until then the runtime image installs from
# pyproject extras.

ARG PYTHON_VERSION=3.12-slim-bookworm

# ---------- Stage 1: build wheels into a temporary venv ----------
FROM python:${PYTHON_VERSION} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Build deps for wheels that may need compilation (e.g. some optional extras).
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy only the files needed to resolve dependencies first; this keeps
# subsequent code-only changes from busting the install cache.
COPY pyproject.toml requirements.txt ./
COPY memograph/__init__.py ./memograph/__init__.py
COPY memograph/py.typed ./memograph/py.typed

# Create a venv inside /opt and install runtime deps + the web extra.
# We deliberately install the web extra here so uvicorn ships in the image.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY . /build
RUN pip install --upgrade pip && \
    pip install ".[web]"

# ---------- Stage 2: runtime ----------
FROM python:${PYTHON_VERSION} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    MEMOGRAPH_VAULT="/data/vault"

# Run as a non-root user. UID 1000 is the conventional first non-system UID
# on Debian; matches host user IDs on most desktop Linux distros so volume
# mounts don't end up root-owned.
RUN groupadd --system --gid 1000 memograph && \
    useradd --system --uid 1000 --gid memograph --home /home/memograph \
            --create-home --shell /usr/sbin/nologin memograph

# Vault volume — bind- or volume-mount this to persist data.
RUN mkdir -p /data/vault && chown -R memograph:memograph /data

COPY --from=builder --chown=memograph:memograph /opt/venv /opt/venv
COPY --from=builder --chown=memograph:memograph /build /app

WORKDIR /app
USER memograph

EXPOSE 8000

# Curl is not in the slim image; use python for the healthcheck so we don't
# bloat the image just to probe a URL.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3).status==200 else 1)" \
        || exit 1

CMD ["uvicorn", "memograph.web.backend.asgi:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
