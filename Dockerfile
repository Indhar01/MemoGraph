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
# pip-install layer.
#
# Base image is pinned by digest so a transient tag retag in upstream
# python:slim cannot silently change what we ship. To refresh:
#   docker pull python:3.12-slim-bookworm
#   docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim-bookworm
# Then update BASE_IMAGE below.

ARG BASE_IMAGE=python@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b

# ---------- Stage 1: build wheels into a temporary venv ----------
FROM ${BASE_IMAGE} AS builder

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
COPY pyproject.toml requirements.txt requirements.lock ./
COPY memograph/__init__.py ./memograph/__init__.py
COPY memograph/py.typed ./memograph/py.typed

# Create a venv inside /opt and install runtime deps from the hash-pinned
# lockfile. requirements.lock is generated with:
#   pip-compile --generate-hashes --extra web -o requirements.lock pyproject.toml
# so any tampered wheel breaks the install rather than landing silently.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

RUN pip install --upgrade pip && \
    pip install --require-hashes --no-deps -r requirements.lock

# Now copy the source and install the package itself (without re-resolving
# deps, which are already locked above).
COPY . /build
RUN pip install --no-deps .

# ---------- Stage 2: runtime ----------
FROM ${BASE_IMAGE} AS runtime

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
