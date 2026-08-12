# syntax=docker/dockerfile:1.7
#
# Hugging Face Spaces Dockerfile for the read-only MemoGraph demo.
#
# This is intentionally minimal — it installs the published `memograph`
# wheel from PyPI rather than building from source, so the Space rebuilds
# in <60s on every commit and we never ship a version that PyPI doesn't
# already have.
#
# Image runs as UID 1000 (HF Spaces' enforced non-root convention).
# Free Spaces are ephemeral, so we re-seed the demo vault on every
# container boot via `memograph quickstart`.
#
# To deploy:
#   1. Create a new HF Space (sdk: docker) at
#      https://huggingface.co/new-space
#   2. git clone the empty Space repo
#   3. Copy this Dockerfile + the sibling README.md into the Space repo
#   4. git push — HF builds and serves automatically

FROM python:3.12-slim-bookworm

# HF Spaces requires non-root + a HOME the process can write to.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    MEMOGRAPH_VAULT=/home/user/demo-vault \
    MEMOGRAPH_READONLY=true \
    MEMOGRAPH_LOG_JSON=1 \
    MEMOGRAPH_AUTH_PROVIDER=none \
    MEMOGRAPH_DEBUG=0

RUN useradd -m -u 1000 user
USER user
WORKDIR /home/user

# Pin to a known-good release. Bump deliberately rather than tracking
# floating "latest" — a bad PyPI release should not silently break the
# public demo.
ARG MEMOGRAPH_VERSION=0.4.1
RUN pip install --user "memograph[web]==${MEMOGRAPH_VERSION}"

# Seed the demo vault at image-build time so first-request latency
# doesn't include the quickstart ingest. The vault is then re-ingested
# at startup by the lifespan handler (idempotent against the on-disk
# cache). --force replaces any pre-existing directory contents
# non-interactively (the quickstart command has no interactive prompt
# when --force is passed).
RUN memograph quickstart --target "$MEMOGRAPH_VAULT" --force

EXPOSE 8000

# HF Spaces ignores HEALTHCHECK — they probe the listening port directly.
# Bind 0.0.0.0:8000 (matches app_port in README.md frontmatter).
CMD ["uvicorn", "memograph.web.backend.asgi:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
