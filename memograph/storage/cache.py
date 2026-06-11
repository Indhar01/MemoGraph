"""Persistent JSON cache with schema versioning.

The on-disk format is::

    {
      "_schema_version": 1,
      "data": <payload>
    }

Loading honors both the versioned envelope and legacy (envelope-less) v0
payloads so existing caches keep working through one upgrade. Saves
always emit the current envelope; Phase 4 will drop legacy support.

If a cache file declares an unknown ``_schema_version`` (e.g. a future
release wrote it and the reader has been downgraded), ``load()`` raises
``CacheSchemaError`` rather than silently returning empty — corrupt or
stale caches should be a loud failure, not a quiet performance
regression.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1
"""Bump when the on-disk shape changes. Add a migration in ``_migrate``."""

_SCHEMA_KEY = "_schema_version"
_DATA_KEY = "data"


class CacheSchemaError(RuntimeError):
    """Raised when a cache file's schema version is unrecognized."""


class JsonCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[Any, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning(
                "cache file %s is not valid JSON; ignoring (will be "
                "regenerated on next save)",
                self.path,
            )
            return {}

        if not isinstance(raw, dict):
            logger.warning(
                "cache file %s has unexpected top-level type %s; ignoring",
                self.path,
                type(raw).__name__,
            )
            return {}

        # Versioned envelope
        if _SCHEMA_KEY in raw:
            version = raw.get(_SCHEMA_KEY)
            if version == CURRENT_SCHEMA_VERSION:
                data = raw.get(_DATA_KEY, {})
                return data if isinstance(data, dict) else {}
            return self._migrate(raw, version)

        # Legacy (v0): top-level dict is the payload itself.
        return raw

    def save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            _SCHEMA_KEY: CURRENT_SCHEMA_VERSION,
            _DATA_KEY: payload,
        }
        self.path.write_text(json.dumps(envelope), encoding="utf-8")

    def _migrate(self, raw: dict[str, Any], version: Any) -> dict[Any, Any]:
        """Hook for forward migrations. Currently a no-op since v1 is initial.

        When CURRENT_SCHEMA_VERSION rises past 1, dispatch on `version`
        here and return the migrated payload. Refusing unknown future
        versions is intentional — a downgraded reader silently ignoring
        a future cache would manifest as inexplicable cache misses.
        """
        raise CacheSchemaError(
            f"cache file {self.path} has unknown schema version {version!r}; "
            f"this build supports up to version {CURRENT_SCHEMA_VERSION}"
        )


__all__ = [
    "JsonCache",
    "CacheSchemaError",
    "CURRENT_SCHEMA_VERSION",
]
