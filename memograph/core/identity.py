"""Public identity seam.

Core facilities (e.g. the action/audit logger) need to know *who* is acting,
but the public core must NOT import the auth module — after the open-core
split, auth lives in the private enterprise layer (OIDC/API-key/RBAC). This
module is the neutral seam: the public default resolves to "no identity"
(anonymous), and an enterprise auth plugin registers a provider that pulls the
real user from the request context.

See docs/EXTRACTION_MANIFEST.md and docs/PUBLIC_VS_PRIVATE_SPLIT.md.
"""

from __future__ import annotations

from typing import Callable

# A provider returns ``(user_id, tenant_id)``; both None means anonymous.
IdentityProvider = Callable[[], "tuple[str | None, str | None]"]


def _anonymous() -> tuple[str | None, str | None]:
    return (None, None)


_provider: IdentityProvider = _anonymous


def set_identity_provider(provider: IdentityProvider) -> None:
    """Install the identity provider (called by the enterprise auth plugin).

    Passing ``None`` resets to the anonymous default.
    """
    global _provider
    _provider = provider if provider is not None else _anonymous


def current_identity() -> tuple[str | None, str | None]:
    """Return ``(user_id, tenant_id)`` for the current context.

    Defaults to ``(None, None)`` in the public build. Never raises: a broken
    provider degrades to anonymous rather than failing the operation being
    audited.
    """
    try:
        return _provider()
    except Exception:  # pragma: no cover - provider must never break callers
        return (None, None)


__all__ = ["IdentityProvider", "set_identity_provider", "current_identity"]
