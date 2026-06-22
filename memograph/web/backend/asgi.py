"""ASGI entry point for production deployment.

Exposes a uvicorn-callable `app` that reads its configuration from
environment variables. Used by the Dockerfile and any external ASGI
runner (gunicorn, hypercorn, etc.) that does not accept arguments.

Environment:
    MEMOGRAPH_VAULT     Path to the vault directory (required).
    MEMOGRAPH_USE_GAM   "0" / "false" / "no" disables GAM. Default: enabled.
"""

from __future__ import annotations

import os

from .server import create_app

_vault = os.environ.get("MEMOGRAPH_VAULT")
if not _vault:
    raise RuntimeError(
        "MEMOGRAPH_VAULT environment variable is not set; "
        "set it to the path of the vault to serve."
    )

_use_gam = os.environ.get("MEMOGRAPH_USE_GAM", "1").lower() not in {"0", "false", "no"}

app = create_app(vault_path=_vault, use_gam=_use_gam)
