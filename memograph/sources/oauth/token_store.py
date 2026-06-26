"""Encrypted OAuth token persistence.

Tokens are written to ``<sources_dir>/<source_id>.token.enc`` as
Fernet-encrypted JSON. The key is derived from
``MEMOGRAPH_SECRET_KEY`` (mandatory env var when any OAuth source
is registered) so the same operator can restore from a backup
without re-authorising every connection. Lose the key, lose every
saved token — refresh by reconnecting each source via the OAuth UI.

Why not use the system keyring: keyrings are great for desktop
apps but break on headless servers (no D-Bus, no Keychain) which
is the primary deployment target. Encrypted-on-disk works the same
on every host the rest of the stack runs on (Docker, Helm, bare
metal) and the secret-key boundary is what the operator already
manages for their other secrets.

Format::

    sources_dir/<source_id>.token.enc   ← Fernet-encrypted JSON

Plaintext JSON shape::

    {
      "access_token": "ya29...",
      "refresh_token": "1//0e...",   // optional
      "expires_at": "2026-06-26T13:30:00+00:00",  // ISO8601
      "scope": "https://www.googleapis.com/auth/drive.readonly",
      "token_type": "Bearer",
      "provider": "google",
      "extra": {}                    // adapter-specific extras
    }
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TokenStoreError(Exception):
    """Raised on encryption/decryption/IO failures.

    The encrypted-token contract is "either you get a valid token or
    you get an explicit failure" — we never silently return None or
    a placeholder. Routes that want to fall through to a re-auth
    path catch this and redirect to the OAuth start flow.
    """


@dataclass(frozen=True)
class TokenBundle:
    """The decrypted token payload + metadata.

    Immutable so a leaked reference to an old bundle can't mutate a
    refreshed one stored elsewhere.
    """

    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scope: str
    token_type: str = "Bearer"
    provider: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, *, now: datetime | None = None, leeway_seconds: int = 60) -> bool:
        """True if the access token has expired (or is about to).

        ``leeway_seconds`` triggers a refresh slightly before the
        actual expiry so a slow refresh doesn't cause a request to
        fail with 401. 60 seconds is conservative; tighten if your
        deployment has very low Drive-API latency.
        """
        if self.expires_at is None:
            return False
        moment = now or datetime.now(timezone.utc)
        from datetime import timedelta

        return moment + timedelta(seconds=leeway_seconds) >= self.expires_at

    def to_json(self) -> str:
        payload = asdict(self)
        if self.expires_at is not None:
            payload["expires_at"] = self.expires_at.isoformat()
        return json.dumps(payload, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "TokenBundle":
        data = json.loads(raw)
        exp_raw = data.get("expires_at")
        exp: datetime | None = (
            datetime.fromisoformat(exp_raw) if exp_raw else None
        )
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=exp,
            scope=data.get("scope", ""),
            token_type=data.get("token_type", "Bearer"),
            provider=data.get("provider", ""),
            extra=data.get("extra", {}) or {},
        )


class EncryptedTokenStore:
    """Per-source encrypted token persistence.

    Reads :envvar:`MEMOGRAPH_SECRET_KEY` at construction time. The
    value can be either a 32-byte urlsafe-base64 Fernet key (the
    natural format) or any arbitrary string — in the latter case
    we derive a Fernet key by SHA-256 hashing the value. The
    derivation makes operator setup easier (any password works) at
    the cost of slightly reduced entropy versus a freshly-generated
    Fernet key; that's an acceptable trade for "no operator has to
    figure out how to mint a Fernet key."
    """

    _ENV_VAR = "MEMOGRAPH_SECRET_KEY"

    def __init__(
        self,
        sources_dir: Path,
        secret_key: str | bytes | None = None,
    ) -> None:
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:
            raise TokenStoreError(
                "Encrypted token storage requires the `cryptography` "
                "package. Install with: pip install 'memograph[sources-gdrive]'"
            ) from exc

        self._sources_dir = Path(sources_dir)
        raw = secret_key if secret_key is not None else os.environ.get(self._ENV_VAR)
        if not raw:
            raise TokenStoreError(
                f"{self._ENV_VAR} is not set. Generate one with "
                "`python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"` and set it in "
                "the environment before registering OAuth sources."
            )
        self._fernet = Fernet(_to_fernet_key(raw))

    def _path(self, source_id: str) -> Path:
        return self._sources_dir / f"{source_id}.token.enc"

    def save(self, source_id: str, bundle: TokenBundle) -> None:
        """Persist a token bundle atomically.

        Writes through a tempfile + rename so a crash mid-write
        cannot leave a half-encrypted blob on disk that decrypts
        to garbage.
        """
        self._sources_dir.mkdir(parents=True, exist_ok=True)
        ciphertext = self._fernet.encrypt(bundle.to_json().encode("utf-8"))
        target = self._path(source_id)
        tmp = target.with_suffix(".enc.tmp")
        tmp.write_bytes(ciphertext)
        tmp.replace(target)

    def load(self, source_id: str) -> TokenBundle:
        """Return the decrypted bundle. Raises if missing or unreadable."""
        target = self._path(source_id)
        if not target.exists():
            raise TokenStoreError(
                f"no token saved for source {source_id!r}; reconnect "
                "via the OAuth flow first"
            )
        try:
            from cryptography.fernet import InvalidToken
        except ImportError:  # pragma: no cover
            raise TokenStoreError("cryptography is not installed")

        try:
            plaintext = self._fernet.decrypt(target.read_bytes()).decode("utf-8")
        except InvalidToken as exc:
            raise TokenStoreError(
                f"token decryption failed for source {source_id!r}. "
                f"This usually means {self._ENV_VAR} has changed since "
                "the token was saved; reconnect the source via the "
                "OAuth flow to mint a fresh token."
            ) from exc
        return TokenBundle.from_json(plaintext)

    def delete(self, source_id: str) -> bool:
        """Best-effort token removal. Idempotent. Returns True on hit."""
        target = self._path(source_id)
        if not target.exists():
            return False
        try:
            target.unlink()
        except OSError as exc:
            logger.warning(
                "failed to delete token for %s: %s", source_id, exc
            )
            return False
        return True

    def exists(self, source_id: str) -> bool:
        return self._path(source_id).exists()


def _to_fernet_key(raw: str | bytes) -> bytes:
    """Coerce an operator-supplied secret into a Fernet key.

    If it parses as a proper Fernet key (32 bytes after urlsafe-base64
    decode) we use it directly; otherwise we SHA-256-hash and base64url-
    encode. The two paths produce indistinguishable bytes for downstream
    code — the operator can't tell which branch ran from outside.
    """
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    else:
        raw_bytes = raw
    # Try direct: a 44-character urlsafe-base64 string is the
    # canonical Fernet key format.
    try:
        decoded = base64.urlsafe_b64decode(raw_bytes)
        if len(decoded) == 32:
            return raw_bytes
    except (ValueError, base64.binascii.Error):
        pass
    # Derive: SHA-256 → 32 bytes → urlsafe-base64.
    import hashlib

    digest = hashlib.sha256(raw_bytes).digest()
    return base64.urlsafe_b64encode(digest)


__all__ = [
    "EncryptedTokenStore",
    "TokenBundle",
    "TokenStoreError",
]
