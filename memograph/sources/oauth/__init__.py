"""OAuth scaffolding for cloud Source adapters (ADR 0002 Phases 3-4).

Shared primitives used by :class:`GoogleDriveSource` (Phase 3) and the
upcoming :class:`OneDriveSource` (Phase 4):

* :mod:`memograph.sources.oauth.pkce` — RFC 7636 PKCE generator.
* :mod:`memograph.sources.oauth.token_store` — Fernet-encrypted
  on-disk token persistence, scoped to ``(tenant_id, source_id)``.
* :mod:`memograph.sources.oauth.google` — Google authorization-code
  + PKCE flow with refresh-token handling.

The Microsoft equivalent lands in Phase 4 as
:mod:`memograph.sources.oauth.microsoft` and reuses the same store.
"""

from memograph.sources.oauth.pkce import (
    PKCEChallenge,
    new_pkce_challenge,
)
from memograph.sources.oauth.token_store import (
    EncryptedTokenStore,
    TokenBundle,
    TokenStoreError,
)

__all__ = [
    "EncryptedTokenStore",
    "PKCEChallenge",
    "TokenBundle",
    "TokenStoreError",
    "new_pkce_challenge",
]
