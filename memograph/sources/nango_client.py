"""Async wrapper around Nango's REST API.

Nango (https://nango.dev) handles the OAuth dance, encrypted token
storage, automatic refresh, and provider-API proxying for 800+
services. MemoGraph delegates the entire cloud-source plumbing to it
instead of maintaining bespoke per-provider OAuth code.

This module is the only place in the codebase that talks to Nango.
Everything else (the adapter, the routes, the webhook) goes through
:class:`NangoClient`. Keeping the surface area thin makes the
service-swap path open if we ever migrate to a different connector.

The Nango Python SDK was "coming soon" at the time of writing
(https://nango.dev/docs/reference/backend/backend-sdk/python.md), so
we hit the REST API directly via ``httpx``. ``httpx`` is already a
transitive dependency of FastAPI — no new install required.

Configuration (env, read at construction):

* ``MEMOGRAPH_NANGO_BASE_URL`` — e.g. ``http://localhost:3003`` for a
  self-hosted instance or ``https://api.nango.dev`` for Nango Cloud.
* ``MEMOGRAPH_NANGO_SECRET_KEY`` — server-side API key with the
  ``environment:connect_sessions:write``, ``environment:connections:*``,
  and ``environment:proxy`` scopes.
* ``MEMOGRAPH_NANGO_WEBHOOK_SECRET`` — shared secret for verifying
  the HMAC signature Nango attaches to outbound webhooks.

Mapping our :class:`SourceKind` to Nango's provider-config-key slugs
is centralised here so the rest of the codebase can stay
provider-agnostic.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from memograph.sources.base import (
    SourceAuthError,
    SourceError,
    SourceKind,
    SourceNotFoundError,
)

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


# MemoGraph SourceKind → Nango provider-config-key (the slug used in
# Nango's admin UI when registering the integration). These match
# Nango's canonical names; operators must use the same slugs when
# creating the integration entries.
KIND_TO_PROVIDER_KEY: dict[SourceKind, str] = {
    SourceKind.GDRIVE: "google-drive",
    SourceKind.ONEDRIVE: "one-drive",
    SourceKind.NOTION: "notion",
}

# Inverse — used by the webhook handler to map the provider key
# back to our SourceKind enum when registering a new connection.
PROVIDER_KEY_TO_KIND: dict[str, SourceKind] = {
    v: k for k, v in KIND_TO_PROVIDER_KEY.items()
}


@dataclass(frozen=True)
class NangoConfig:
    """Operator config for the Nango integration.

    Two URLs are tracked separately because a Docker self-host has
    different addresses for the same Nango instance depending on who's
    talking to it:

    * ``base_url`` — what the MemoGraph backend uses (server-to-server).
      Inside Docker this may be a container DNS name like
      ``http://nango-server:3003``.
    * ``public_url`` — what the user's browser uses (Nango Connect UI
      runs client-side). Outside the container, that's usually
      ``http://localhost:3003`` or the reverse-proxy hostname.

    Single-machine installs leave them equal; ``MEMOGRAPH_NANGO_PUBLIC_URL``
    defaults to ``MEMOGRAPH_NANGO_BASE_URL`` when unset.
    """

    base_url: str
    secret_key: str
    public_url: str = ""
    webhook_secret: str | None = None

    def __post_init__(self) -> None:
        # Frozen dataclass: bypass the immutability guard for the
        # derived default. Inputs are still validated at the from_env
        # boundary; this just lets callers omit public_url for
        # single-machine setups.
        if not self.public_url:
            object.__setattr__(self, "public_url", self.base_url)

    @classmethod
    def from_env(cls) -> "NangoConfig":
        base_url = os.environ.get("MEMOGRAPH_NANGO_BASE_URL", "").strip()
        if not base_url:
            raise NangoConfigError(
                "MEMOGRAPH_NANGO_BASE_URL is not set. Point this at your "
                "self-hosted Nango (e.g. http://localhost:3003) or use "
                "https://api.nango.dev for Nango Cloud."
            )
        secret_key = os.environ.get("MEMOGRAPH_NANGO_SECRET_KEY", "").strip()
        if not secret_key:
            raise NangoConfigError(
                "MEMOGRAPH_NANGO_SECRET_KEY is not set. Mint one in the "
                "Nango admin UI under Environment Settings → API keys."
            )
        webhook_secret = (
            os.environ.get("MEMOGRAPH_NANGO_WEBHOOK_SECRET", "").strip() or None
        )
        public_url = (
            os.environ.get("MEMOGRAPH_NANGO_PUBLIC_URL", "").strip() or base_url
        )
        return cls(
            base_url=base_url.rstrip("/"),
            secret_key=secret_key,
            public_url=public_url.rstrip("/"),
            webhook_secret=webhook_secret,
        )


class NangoConfigError(SourceError):
    """Misconfiguration of the Nango integration — invalid env vars, etc."""


@dataclass(frozen=True)
class ConnectSession:
    """Short-lived session token the frontend hands to Nango Connect UI.

    Nango docs say sessions expire after 30 minutes; we surface
    ``expires_at`` so the frontend can refuse to open a stale modal.
    """

    token: str
    expires_at: datetime
    connect_link: str | None = None


@dataclass(frozen=True)
class ConnectionInfo:
    """A live Nango connection. Returned by :meth:`NangoClient.get_connection`.

    We don't expose the raw credentials — for proxy calls Nango injects
    them server-side, and for the few places we need to introspect, the
    flags here are enough.
    """

    connection_id: str
    provider_config_key: str
    provider: str
    has_auth_error: bool
    created_at: str | None
    updated_at: str | None
    metadata: dict[str, Any]


class NangoClient:
    """Thin async wrapper over Nango's REST API.

    One instance per process (created in the lifespan). The wrapped
    ``httpx.AsyncClient`` is reused across calls; the
    :meth:`aclose` method shuts it down on app shutdown.
    """

    def __init__(
        self,
        config: NangoConfig,
        *,
        http_client: "httpx.AsyncClient | None" = None,
    ) -> None:
        self.config = config
        self._http: "httpx.AsyncClient | None" = http_client
        self._owns_client = http_client is None

    @classmethod
    def from_env(cls) -> "NangoClient":
        return cls(NangoConfig.from_env())

    def _ensure_http(self) -> "httpx.AsyncClient":
        if self._http is not None:
            return self._http
        try:
            import httpx
        except ImportError as exc:
            raise SourceError(
                "NangoClient requires httpx. Install with: "
                "pip install 'memograph[sources-cloud]'"
            ) from exc
        # 30s timeout matches the existing per-adapter clients. Nango's
        # proxy adds a hop; if the upstream provider is slow this needs
        # to be higher, but 30s covers the common case.
        self._http = httpx.AsyncClient(
            timeout=30.0,
            headers={"Authorization": f"Bearer {self.config.secret_key}"},
        )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and self._owns_client:
            await self._http.aclose()
            self._http = None

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> "httpx.Response":
        """Unified request wrapper that turns transport errors into SourceError.

        Without this every ``httpx.RequestError`` (DNS failure, connection
        refused, read timeout) propagates as a bare 500 from the route.
        Mapping them to ``SourceError`` lets the route layer return a
        useful 502 with the operator-facing reason ("Nango unreachable").
        """
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover — guarded in _ensure_http
            raise SourceError(
                "NangoClient requires httpx. Install with: "
                "pip install 'memograph[sources-cloud]'"
            ) from exc
        http = self._ensure_http()
        # Dispatch on method so test fakes that only stub per-verb
        # helpers (httpx.AsyncClient.get/post/delete) keep working —
        # and so we exercise the same code paths real callers always
        # have. ``httpx.AsyncClient.request`` exists in real httpx, but
        # we prefer the verb methods for fidelity.
        try:
            verb = method.upper()
            # Only pass kwargs the caller actually supplied so test
            # fakes with minimal signatures keep working.
            kw: dict[str, Any] = {}
            if params is not None:
                kw["params"] = params
            if headers is not None:
                kw["headers"] = headers
            if verb == "GET":
                return await http.get(url, **kw)
            if verb == "POST":
                if json is not None:
                    kw["json"] = json
                return await http.post(url, **kw)
            if verb == "DELETE":
                return await http.delete(url, **kw)
            if json is not None:
                kw["json"] = json
            return await http.request(method, url, **kw)
        except httpx.TimeoutException as exc:
            raise SourceError(
                f"Nango request timed out ({method} {url}): {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise SourceError(
                f"Nango unreachable ({method} {url}): {exc}. "
                "Check MEMOGRAPH_NANGO_BASE_URL and that the Nango stack "
                "is running."
            ) from exc

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        max_attempts: int = 3,
    ) -> "httpx.Response":
        """Like :meth:`_request` but retries transient 5xx + 429 with backoff.

        Used for proxy calls where the upstream provider (or Nango's
        own gateway) can blip on rate limits or transient outages. We
        only retry on 502/503/504/429 and on transport errors — never on
        4xx (those are the caller's problem).
        """
        import asyncio

        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                resp = await self._request(
                    method, url, json=json, params=params, headers=headers
                )
            except SourceError as exc:
                last_exc = exc
                # Transport error — retry with backoff.
                if attempt + 1 < max_attempts:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise
            if resp.status_code in (429, 502, 503, 504) and attempt + 1 < max_attempts:
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            return resp
        # Defensive — loop always either returns or raises.
        if last_exc is not None:  # pragma: no cover
            raise last_exc
        raise SourceError(f"Nango {method} {url} exhausted retries")  # pragma: no cover

    # --- Integrations ----------------------------------------------------

    async def list_integrations(self) -> list[dict[str, Any]]:
        """Return the integrations configured in Nango.

        Nango's ``GET /integrations`` returns
        ``{ data: [{ unique_key, provider, meta: { displayName, ... }, ... }] }``.
        The ``unique_key`` is the integration's provider-config-key
        (what we send as the ``Provider-Config-Key`` header on proxy
        calls). Callers commonly use this to gate the wizard's
        cloud-kind buttons — show only the providers that the operator
        has actually configured.

        Returns an empty list on success-with-no-integrations.
        """
        resp = await self._request("GET", f"{self.config.base_url}/integrations")
        if resp.status_code == 401:
            raise NangoConfigError(
                "Nango rejected the secret key (401) when listing integrations."
            )
        if resp.status_code >= 400:
            raise SourceError(
                f"Nango list-integrations failed ({resp.status_code}): "
                f"{_safe_text(resp)}"
            )
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        return list(data) if isinstance(data, list) else []

    # --- Connect sessions -------------------------------------------------

    async def create_connect_session(
        self,
        *,
        kind: SourceKind,
        tenant_id: str | None,
        source_id: str,
        end_user_id: str,
        end_user_email: str | None = None,
        display_name: str | None = None,
    ) -> ConnectSession:
        """Mint a short-lived session token for the Connect UI.

        ``tags`` is the round-trip channel: every key set here comes
        back on the connection-creation webhook. We stuff our
        ``source_id``, ``tenant_id``, and ``kind`` in there so the
        webhook handler can register the resulting connection
        without a separate state store.
        """
        provider_key = KIND_TO_PROVIDER_KEY.get(kind)
        if provider_key is None:
            raise SourceError(
                f"NangoClient cannot connect sources of kind {kind.value!r}; "
                "only the OAuth cloud kinds (gdrive, onedrive, notion) "
                "are routed through Nango"
            )
        tags: dict[str, str] = {
            "end_user_id": end_user_id,
            "memograph_source_id": source_id,
            "memograph_kind": kind.value,
        }
        if end_user_email:
            tags["end_user_email"] = end_user_email
        if tenant_id:
            tags["memograph_tenant_id"] = tenant_id
        if display_name:
            tags["memograph_display_name"] = display_name[:255]

        body: dict[str, Any] = {
            "allowed_integrations": [provider_key],
            "tags": tags,
        }
        resp = await self._request(
            "POST", f"{self.config.base_url}/connect/sessions", json=body
        )
        if resp.status_code == 401:
            raise NangoConfigError(
                "Nango rejected the secret key (401). Check "
                "MEMOGRAPH_NANGO_SECRET_KEY and the API key scopes."
            )
        if resp.status_code >= 400:
            raise SourceError(
                f"Nango connect-session failed ({resp.status_code}): "
                f"{_safe_text(resp)}"
            )
        payload = resp.json().get("data") or {}
        token = payload.get("token")
        expires_at_raw = payload.get("expires_at")
        if not token or not expires_at_raw:
            raise SourceError(
                f"Nango connect-session response missing token/expires_at: "
                f"{payload}"
            )
        try:
            expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise SourceError(
                f"Nango returned malformed expires_at: {expires_at_raw!r}"
            ) from exc
        return ConnectSession(
            token=token,
            expires_at=expires_at,
            connect_link=payload.get("connect_link"),
        )

    # --- Connection introspection ----------------------------------------

    async def get_connection(
        self,
        *,
        connection_id: str,
        kind: SourceKind,
    ) -> ConnectionInfo:
        """Fetch a connection's status.

        Nango maps refresh failures two ways:

        * **HTTP 424** ("Connection refresh exhausted") — the refresh
          token is dead. Raise :class:`SourceAuthError`.
        * **200 with ``errors[]`` containing an entry of
          ``type == "auth"``** — Nango knows the connection is broken
          but is still returning metadata. Also raise auth-error.

        The healthy case returns a populated :class:`ConnectionInfo`.
        """
        provider_key = KIND_TO_PROVIDER_KEY.get(kind)
        if provider_key is None:
            raise SourceError(
                f"NangoClient: unknown kind {kind.value!r} for connection lookup"
            )
        resp = await self._request(
            "GET",
            f"{self.config.base_url}/connections/{connection_id}",
            params={"provider_config_key": provider_key},
        )
        if resp.status_code == 404:
            raise SourceNotFoundError(f"Nango connection not found: {connection_id}")
        if resp.status_code == 424:
            raise SourceAuthError(
                f"Nango connection {connection_id} can no longer be "
                "refreshed; reconnect via the Connect UI."
            )
        if resp.status_code == 401:
            raise NangoConfigError(
                "Nango rejected the secret key (401) when fetching a connection."
            )
        if resp.status_code >= 400:
            raise SourceError(
                f"Nango get-connection failed ({resp.status_code}): "
                f"{_safe_text(resp)}"
            )
        body = resp.json()
        errors = body.get("errors") or []
        has_auth_error = any(
            isinstance(e, dict) and e.get("type") == "auth" for e in errors
        )
        if has_auth_error:
            raise SourceAuthError(
                f"Nango connection {connection_id} has an auth error; "
                "user needs to reconnect."
            )
        return ConnectionInfo(
            connection_id=body.get("connection_id", connection_id),
            provider_config_key=body.get("provider_config_key", provider_key),
            provider=body.get("provider", provider_key),
            has_auth_error=False,
            created_at=body.get("created_at"),
            updated_at=body.get("updated_at"),
            metadata=body.get("metadata") or {},
        )

    # --- Proxy ------------------------------------------------------------

    async def proxy_get(
        self,
        *,
        connection_id: str,
        kind: SourceKind,
        path: str,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> "httpx.Response":
        """Forward a GET request to the provider via Nango's proxy.

        ``path`` is the provider-side path (e.g. ``drive/v3/files``).
        Query params, including those with non-string values, are
        forwarded unchanged by Nango. Extra request headers must be
        prefixed with ``nango-proxy-`` per the Nango spec; we add the
        prefix here so callers don't have to remember.

        Returns the raw ``httpx.Response`` so callers can decide
        whether to parse JSON or read raw bytes for file downloads.
        Errors are NOT raised — the caller inspects ``status_code`` to
        translate to source-specific errors (404 → SourceNotFoundError,
        401 → SourceAuthError, etc.).
        """
        provider_key = KIND_TO_PROVIDER_KEY.get(kind)
        if provider_key is None:
            raise SourceError(
                f"NangoClient: unknown kind {kind.value!r} for proxy call"
            )
        headers: dict[str, str] = {
            "Provider-Config-Key": provider_key,
            "Connection-Id": connection_id,
            "Retries": "2",
        }
        if extra_headers:
            for k, v in extra_headers.items():
                # Nango forwards any header prefixed with nango-proxy-.
                if not k.lower().startswith("nango-proxy-"):
                    k = f"nango-proxy-{k}"
                headers[k] = v
        url = f"{self.config.base_url}/proxy/{path.lstrip('/')}"
        return await self._request_with_retry(
            "GET", url, params=params or None, headers=headers
        )

    async def proxy_post(
        self,
        *,
        connection_id: str,
        kind: SourceKind,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> "httpx.Response":
        """Forward a POST request through Nango's proxy.

        Used by adapters whose list operations require POST bodies
        (Notion's ``databases/{id}/query``, etc.). Same error-handling
        contract as :meth:`proxy_get` — returns the raw response so
        the caller can map status codes.
        """
        provider_key = KIND_TO_PROVIDER_KEY.get(kind)
        if provider_key is None:
            raise SourceError(
                f"NangoClient: unknown kind {kind.value!r} for proxy POST"
            )
        headers = {
            "Provider-Config-Key": provider_key,
            "Connection-Id": connection_id,
            "Retries": "2",
        }
        url = f"{self.config.base_url}/proxy/{path.lstrip('/')}"
        return await self._request_with_retry(
            "POST", url, json=json, params=params or None, headers=headers
        )

    async def proxy_get_bytes(
        self,
        *,
        connection_id: str,
        kind: SourceKind,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        """Convenience wrapper for binary downloads (file contents).

        Raises :class:`SourceAuthError` on 401/403, :class:`SourceNotFoundError`
        on 404, and :class:`SourceError` for anything else >= 400.
        Returns the raw response body.
        """
        resp = await self.proxy_get(
            connection_id=connection_id, kind=kind, path=path, params=params
        )
        if resp.status_code in (401, 403):
            raise SourceAuthError(
                f"Nango proxy returned {resp.status_code} for "
                f"connection {connection_id}: {_safe_text(resp)}"
            )
        if resp.status_code == 404:
            raise SourceNotFoundError(
                f"Nango proxy: {path!r} not found via connection {connection_id}"
            )
        if resp.status_code >= 400:
            raise SourceError(
                f"Nango proxy GET {path!r} failed ({resp.status_code}): "
                f"{_safe_text(resp)}"
            )
        return resp.content

    # --- Connection deletion ----------------------------------------------

    async def delete_connection(
        self,
        *,
        connection_id: str,
        kind: SourceKind,
    ) -> bool:
        """Revoke a connection in Nango. Idempotent.

        Returns True if the connection existed and was removed, False
        if Nango reported 404. Other errors raise :class:`SourceError`.
        Callers should treat both outcomes as "the connection no longer
        exists" and continue with their own cleanup.
        """
        provider_key = KIND_TO_PROVIDER_KEY.get(kind)
        if provider_key is None:
            raise SourceError(f"NangoClient: unknown kind {kind.value!r} for delete")
        resp = await self._request(
            "DELETE",
            f"{self.config.base_url}/connections/{connection_id}",
            params={"provider_config_key": provider_key},
        )
        if resp.status_code == 404:
            return False
        if resp.status_code >= 400:
            raise SourceError(
                f"Nango delete-connection failed ({resp.status_code}): "
                f"{_safe_text(resp)}"
            )
        return True

    # --- Webhook signature verification ----------------------------------

    def verify_webhook_signature(
        self, *, raw_body: bytes, signature: str | None
    ) -> bool:
        """Verify a Nango webhook against the shared secret.

        Nango signs outbound webhooks with HMAC-SHA256 over the raw
        request body. The signature arrives in the
        ``X-Nango-Signature`` header. When no webhook secret is
        configured this method returns ``True`` only in dev (the
        operator must opt into the looser mode by leaving
        ``MEMOGRAPH_NANGO_WEBHOOK_SECRET`` unset); production setups
        are expected to set the secret so unsigned requests get
        rejected.
        """
        secret = self.config.webhook_secret
        if not secret:
            logger.warning(
                "Nango webhook arrived but MEMOGRAPH_NANGO_WEBHOOK_SECRET "
                "is not set — accepting without verification. Set the env "
                "var for any production deployment."
            )
            return True
        if not signature:
            return False
        expected = hmac.new(
            secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        # Nango can prefix the signature with the algorithm ("sha256=...");
        # tolerate either shape.
        cleaned = signature.split("=", 1)[-1].strip()
        return hmac.compare_digest(expected, cleaned)


def _safe_text(resp: "httpx.Response") -> str:
    """Truncate a response body for log/error messages."""
    try:
        text = resp.text
    except Exception:  # noqa: BLE001
        return "<unreadable>"
    return text[:500] + ("…" if len(text) > 500 else "")


__all__ = [
    "KIND_TO_PROVIDER_KEY",
    "PROVIDER_KEY_TO_KIND",
    "ConnectSession",
    "ConnectionInfo",
    "NangoClient",
    "NangoConfig",
    "NangoConfigError",
]
