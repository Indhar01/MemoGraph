"""``SourceRegistry`` — per-tenant LRU of warm :class:`Source` instances.

Sister of :class:`memograph.core.tenant_registry.TenantRegistry`. The
shape is intentionally similar; both are bounded LRUs that materialize
a heavyweight object on demand and evict on memory pressure. The
differences are the persistence layer (sources persist as JSON
configs on disk) and the cardinality (many sources per tenant; only
one tenant per request).

Persistence layout::

    <global_root>/<tenant_id>/.sources/
        <source_id>.json        ← SourceConfig as JSON
        _active.json            ← which source the kernel currently reads
        _audit.log              ← append-only audit trail (Phase 2+)

Tokens are NOT stored here — those live in the encrypted token store
(``memograph.sources.oauth.token_store``) and are loaded by adapters
on demand.

Concurrency model matches :class:`TenantRegistry`: one registry-level
``RLock`` guards the warm dict; per-source ``Event`` lets cold
constructions overlap across different sources without contention.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from memograph.sources.base import (
    Source,
    SourceConfig,
    SourceError,
    SourceKind,
)

logger = logging.getLogger(__name__)


DEFAULT_MAX_WARM = 128
"""LRU bound. Sized for a single VPS with ~1000 tenants × ~5 sources
each warm in working set; tune in the registry constructor or via the
``MEMOGRAPH_SOURCES_MAX_WARM`` env var."""


# Source ids share the validation rules of tenant ids: lowercase
# alnum + dash + underscore, 1-64 chars. Tightly scoped because the
# id ends up in filenames + URLs.
_SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")

# Sentinel distinct from None so the active-source cache can
# distinguish "I checked and there is no active source" (cached as
# None) from "I haven't checked yet" (key absent / value is _UNSET).
_UNSET: Any = object()


class InvalidSourceIdError(SourceError):
    """Raised when a source_id fails validation."""


def validate_source_id(source_id: str) -> str:
    """Return the source_id unchanged if valid; raise otherwise.

    Mirrors :func:`memograph.storage.tenant_storage.validate_tenant_id`
    so the audit log and filenames stay portable.
    """
    if not isinstance(source_id, str) or not _SOURCE_ID_PATTERN.match(source_id):
        raise InvalidSourceIdError(
            f"invalid source_id: {source_id!r}; " "must match ^[a-z0-9_-]{1,64}$"
        )
    return source_id


SourceFactory = Callable[[SourceConfig], Source]
"""Factory signature for built-in + future adapters. The default
factory dispatches on :attr:`SourceConfig.kind`; tests inject stubs
to avoid touching real cloud APIs."""


def default_source_factory(config: SourceConfig) -> Source:
    """Build a :class:`Source` from a config, dispatching on kind.

    Dispatch goes through the adapter registry
    (:mod:`memograph.sources.adapter_registry`). The public package ships
    only the ``LOCAL`` adapter; optional/commercial adapters (S3, and the
    Nango-backed cloud kinds) are registered by plugins at import time. A kind
    with no registered adapter raises a clear error rather than being
    hardcoded here.

    The cloud OAuth kinds (GDRIVE / ONEDRIVE / NOTION) need a
    :class:`NangoClient` injected at construction and are built through
    :meth:`SourceRegistry._build_with_context`, not this context-free factory.
    """
    from memograph.sources.adapter_registry import get_source_adapter

    factory = get_source_adapter(config.kind)
    if factory is not None:
        return factory(config)
    if config.kind in (
        SourceKind.GDRIVE,
        SourceKind.ONEDRIVE,
        SourceKind.NOTION,
    ):
        raise SourceError(
            f"{config.kind.value!r} sources route through Nango and need "
            "a NangoClient injected - go through SourceRegistry.get() "
            "rather than calling default_source_factory directly."
        )
    raise SourceError(
        f"no adapter registered for source kind {config.kind.value!r}; "
        "install the plugin that provides it (e.g. memograph-enterprise "
        "for S3 and cloud sources)."
    )


class SourceRegistry:
    """Bounded LRU of warm :class:`Source` instances per tenant.

    Use one registry per process. Multi-worker uvicorn deployments
    will share state through the Redis pub/sub coordinator added in
    Phase 5; the registry itself stays in-process.
    """

    def __init__(
        self,
        global_root: Path | str,
        source_factory: SourceFactory = default_source_factory,
        max_warm: int = DEFAULT_MAX_WARM,
        nango_client: Any = None,
    ) -> None:
        if max_warm < 1:
            raise ValueError(f"max_warm must be >= 1, got {max_warm}")
        self.global_root = Path(global_root).expanduser().resolve()
        self.global_root.mkdir(parents=True, exist_ok=True)
        self._factory = source_factory
        self.max_warm = max_warm
        # Optional. None when the operator hasn't wired Nango; the
        # registry then refuses to materialize cloud sources with a
        # clear error rather than crashing.
        self._nango_client = nango_client

        self._lock = threading.RLock()
        # Key is "(tenant_id, source_id)" so a single OrderedDict
        # handles the LRU across all tenants; cross-tenant eviction
        # is fine — the registry doesn't know which tenant is hot.
        self._warm: OrderedDict[tuple[str | None, str], Source] = OrderedDict()
        self._building: dict[tuple[str | None, str], threading.Event] = {}
        # In-memory cache of the active-source decision per tenant.
        # The on-disk ``_active.json`` is still source of truth, but
        # reading it on every request is wasteful. The
        # :class:`SwapCoordinator` invalidates entries here when a
        # peer worker activates a different source.
        self._active_cache: dict[str | None, str | None] = {}

    # --- persistence ---

    def _sources_dir(self, tenant_id: str | None) -> Path:
        """Per-tenant ``.sources`` directory under ``global_root``.

        Single-tenant installs (``tenant_id`` is None) use
        ``<global_root>/.sources/`` directly. Multi-tenant installs
        nest one level deeper so the existing tenant directory
        layout from :class:`TenantStorage` is preserved.
        """
        base = self.global_root if tenant_id is None else self.global_root / tenant_id
        return base / ".sources"

    def _config_path(self, tenant_id: str | None, source_id: str) -> Path:
        return self._sources_dir(tenant_id) / f"{source_id}.json"

    def _active_path(self, tenant_id: str | None) -> Path:
        return self._sources_dir(tenant_id) / "_active.json"

    # --- registration / lookup ---

    def register(self, config: SourceConfig) -> Source:
        """Persist a config and return the warmed-up source.

        Idempotent: re-registering the same ``source_id`` for a
        tenant overwrites the previous config. Callers that want
        strict create-only semantics should check :meth:`get_config`
        first.
        """
        validate_source_id(config.source_id)
        sources_dir = self._sources_dir(config.tenant_id)
        sources_dir.mkdir(parents=True, exist_ok=True)
        # Atomic write: serialise to a temp file in the same
        # directory, then rename. Avoids leaving a half-written
        # config on disk if the process is killed mid-write.
        tmp = self._config_path(config.tenant_id, config.source_id).with_suffix(
            ".json.tmp"
        )
        final = self._config_path(config.tenant_id, config.source_id)
        tmp.write_text(_config_to_json(config), encoding="utf-8")
        tmp.replace(final)
        logger.info(
            "registered source: tenant=%s source_id=%s kind=%s",
            config.tenant_id,
            config.source_id,
            config.kind.value,
        )
        # Drop any stale warm entry for this (tenant, source_id) so
        # the next get() rebuilds with the new config.
        with self._lock:
            self._warm.pop((config.tenant_id, config.source_id), None)
        return self.get(config.tenant_id, config.source_id)

    def get(self, tenant_id: str | None, source_id: str) -> Source:
        """Return the warm source, building it if cold.

        Marks the entry as most-recently-used. Reads the persisted
        config from disk on cold-warm — there's no in-memory config
        cache, so a hot-edit to ``<source_id>.json`` plus a registry
        evict will pick up the new value.
        """
        validate_source_id(source_id)
        key = (tenant_id, source_id)

        with self._lock:
            source = self._warm.get(key)
            if source is not None:
                self._warm.move_to_end(key)
                return source

            event = self._building.get(key)
            if event is None:
                event = threading.Event()
                self._building[key] = event
                build_owner = True
            else:
                build_owner = False

        if not build_owner:
            event.wait()
            return self.get(tenant_id, source_id)

        try:
            config = self._load_config(tenant_id, source_id)
            source = self._build_with_context(config)
        except Exception:
            with self._lock:
                self._building.pop(key, None)
            event.set()
            raise

        with self._lock:
            self._warm[key] = source
            self._warm.move_to_end(key)
            self._evict_if_needed()
            self._building.pop(key, None)
        event.set()
        return source

    def _build_with_context(self, config: SourceConfig) -> Source:
        """Construct a source with registry-derived context injected.

        The cloud OAuth kinds (GDrive, OneDrive, Notion) need a
        :class:`NangoClient` to talk to Nango. The default factory is
        context-free; this seam injects what the registry happens to
        have on hand (the Nango client passed in at construction).

        Kept inside the registry so adapters never reach back out to
        ``SourceRegistry`` — that would invert the dependency and
        tangle the lifecycle.
        """
        if config.kind in (
            SourceKind.GDRIVE,
            SourceKind.ONEDRIVE,
            SourceKind.NOTION,
        ):
            if self._nango_client is None:
                raise SourceError(
                    f"{config.kind.value!r} source {config.source_id!r} "
                    "requires Nango to be configured. Set "
                    "MEMOGRAPH_NANGO_BASE_URL + MEMOGRAPH_NANGO_SECRET_KEY "
                    "and restart the server."
                )
            from memograph.sources.nango_source import NangoBackedSource

            return NangoBackedSource(config, nango_client=self._nango_client)
        return self._factory(config)

    def _load_config(self, tenant_id: str | None, source_id: str) -> SourceConfig:
        path = self._config_path(tenant_id, source_id)
        if not path.exists():
            raise SourceError(
                f"source not found: tenant={tenant_id!r} source_id={source_id!r}"
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _json_to_config(raw)

    def get_config(self, tenant_id: str | None, source_id: str) -> SourceConfig | None:
        """Return the persisted config or None if it doesn't exist.

        Does NOT warm the source. Routes use this to answer GET
        requests without paying the construction cost.
        """
        try:
            return self._load_config(tenant_id, source_id)
        except SourceError:
            return None

    def evict(self, tenant_id: str | None, source_id: str) -> bool:
        """Drop a source from the warm cache. Returns True on hit.

        Does NOT delete the on-disk config; see :meth:`delete`.
        """
        with self._lock:
            removed = self._warm.pop((tenant_id, source_id), None)
        return removed is not None

    def delete(self, tenant_id: str | None, source_id: str) -> bool:
        """Evict + remove the on-disk config. Idempotent.

        Does NOT delete the source's materialized vault cache —
        operator policy decides whether to retain or wipe; the
        ``/api/v1/sources/{id}`` DELETE route does the wipe under
        the GDPR right-to-erasure path.
        """
        self.evict(tenant_id, source_id)
        path = self._config_path(tenant_id, source_id)
        if not path.exists():
            return False
        path.unlink()
        # If this was the active source, clear the marker too — but
        # do NOT auto-activate another source. The caller decides
        # whether the operator should pick a replacement.
        active = self.get_active(tenant_id)
        if active == source_id:
            self._active_path(tenant_id).unlink(missing_ok=True)
            with self._lock:
                self._active_cache[tenant_id] = None
        return True

    # --- listing ---

    def list_configs(self, tenant_id: str | None) -> list[SourceConfig]:
        """Every configured source for this tenant, in alphabetical order.

        Reads from disk; cheap (just directory listing + JSON parse).
        Listing does not warm the sources.
        """
        sources_dir = self._sources_dir(tenant_id)
        if not sources_dir.exists():
            return []
        configs = []
        for f in sorted(sources_dir.glob("*.json")):
            if f.name.startswith("_"):
                # _active.json and friends are not source configs.
                continue
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
                configs.append(_json_to_config(raw))
            except (OSError, json.JSONDecodeError, KeyError) as exc:
                # A corrupt config file shouldn't 500 the whole list.
                # Log and skip; the admin can inspect manually.
                logger.warning("skipping corrupt source config %s: %s", f, exc)
        return configs

    def warm_keys(self) -> Iterable[tuple[str | None, str]]:
        """Return (tenant_id, source_id) pairs currently warm in the LRU."""
        with self._lock:
            return list(self._warm.keys())

    # --- active-source selection ---

    def set_active(self, tenant_id: str | None, source_id: str) -> None:
        """Mark a source as the kernel's active vault for this tenant.

        Writes ``<sources_dir>/_active.json`` atomically and refreshes
        the in-memory cache. Multi-worker propagation is handled
        separately by a :class:`SwapCoordinator` (see
        :meth:`notify_remote_swap`) — the route layer publishes the
        event after this call returns.
        """
        validate_source_id(source_id)
        # Refuse to activate a non-existent source.
        if self.get_config(tenant_id, source_id) is None:
            raise SourceError(
                f"cannot activate unknown source: {source_id!r} "
                f"for tenant={tenant_id!r}"
            )
        sources_dir = self._sources_dir(tenant_id)
        sources_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "source_id": source_id,
                "activated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        tmp = self._active_path(tenant_id).with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self._active_path(tenant_id))
        with self._lock:
            self._active_cache[tenant_id] = source_id

    def get_active(self, tenant_id: str | None) -> str | None:
        """Return the active source_id or None if none is set.

        Reads from the in-memory cache first; falls through to disk
        on miss. The cache is invalidated by
        :meth:`notify_remote_swap` when a peer worker activates a
        different source, so multi-worker deployments see swaps
        within one Redis pub/sub round-trip.
        """
        with self._lock:
            cached = self._active_cache.get(tenant_id, _UNSET)
        if cached is not _UNSET:
            return cached  # type: ignore[return-value]
        value = self._read_active_from_disk(tenant_id)
        with self._lock:
            self._active_cache[tenant_id] = value
        return value

    def _read_active_from_disk(self, tenant_id: str | None) -> str | None:
        path = self._active_path(tenant_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw.get("source_id")
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("malformed _active.json at %s: %s", path, exc)
            return None

    def notify_remote_swap(self, tenant_id: str | None, source_id: str) -> None:
        """Invalidate the in-memory active-source cache for this tenant.

        Called by the :class:`SwapCoordinator` subscriber when another
        worker publishes a swap event. We deliberately do NOT trust
        the payload as authoritative — the on-disk ``_active.json``
        is canonical. We just clear the cache so the next read picks
        up the fresh value.

        Idempotent: calling on a cold cache, on an entry that already
        matches, or on a tenant the worker has never touched is all
        a no-op.
        """
        with self._lock:
            self._active_cache.pop(tenant_id, None)
        logger.debug(
            "registry cleared active-source cache for tenant=%s "
            "after remote swap to %s",
            tenant_id,
            source_id,
        )

    # --- internals ---

    def _evict_if_needed(self) -> None:
        # Caller holds self._lock.
        while len(self._warm) > self.max_warm:
            (tenant_id, source_id), _ = self._warm.popitem(last=False)
            logger.info(
                "LRU evicting source: tenant=%s source_id=%s",
                tenant_id,
                source_id,
            )

    def __iter__(self) -> Iterator[tuple[tuple[str | None, str], Source]]:
        with self._lock:
            return iter(list(self._warm.items()))


# --- JSON helpers ---


def _config_to_json(config: SourceConfig) -> str:
    """Serialise a :class:`SourceConfig` to disk JSON.

    The enum and datetime fields are coerced to plain types because
    :func:`json.dumps` doesn't handle them. We avoid a custom
    encoder class to keep this readable.
    """
    raw = asdict(config)
    raw["kind"] = config.kind.value
    raw["created_at"] = config.created_at.isoformat()
    return json.dumps(raw, indent=2, sort_keys=True)


def _json_to_config(raw: dict) -> SourceConfig:
    """Parse a JSON dict back into a :class:`SourceConfig`."""
    return SourceConfig(
        source_id=raw["source_id"],
        kind=SourceKind(raw["kind"]),
        display_name=raw["display_name"],
        tenant_id=raw.get("tenant_id"),
        params=raw.get("params", {}),
        created_at=datetime.fromisoformat(raw["created_at"]),
    )


__all__ = [
    "DEFAULT_MAX_WARM",
    "InvalidSourceIdError",
    "SourceFactory",
    "SourceRegistry",
    "default_source_factory",
    "validate_source_id",
]
