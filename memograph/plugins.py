"""Plugin seam for MemoGraph.

This module is the single, stable extension point through which optional
out-of-tree packages (e.g. the private ``memograph-enterprise`` layer) attach
behavior to a running MemoGraph web application — without the public package
ever importing them.

Design contract
---------------

- The public package NEVER imports any plugin package directly. Discovery is
  by ``importlib.metadata`` entry points in the ``memograph.plugins`` group.
- A plugin is a zero-arg-importable callable ``register(context)`` where
  ``context`` is an :class:`AppContext`. The callable attaches whatever it
  needs to ``context.app`` (routes, middleware, instrumentation, ...).
- Discovery and activation are best-effort: a broken or missing plugin logs
  a warning and is skipped. A stock ``pip install memograph`` with no plugins
  installed sees this seam as a no-op.
- Idempotent: :func:`load_plugins` guards against double-activation on the
  same app instance (important for test reloads).

Entry-point declaration (in the *plugin* package's ``pyproject.toml``)::

    [project.entry-points."memograph.plugins"]
    my_plugin = "my_pkg.plugins:register"

The public web server calls :func:`load_plugins` once, late in
``create_app``, after the app, kernel, and core routes exist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("memograph.plugins")

# Entry-point group plugins register under.
PLUGIN_GROUP = "memograph.plugins"

# Marker attribute set on an app once plugins have been loaded, so repeated
# create_app calls / importlib.reload in tests don't double-activate.
_LOADED_FLAG = "_memograph_plugins_loaded"


@dataclass
class AppContext:
    """Everything a plugin is allowed to touch, in one object.

    Passing a single context (rather than the raw ``app``) means we can widen
    the surface later — add a kernel handle, a source registry, a hook bus —
    without breaking the ``register(context)`` signature every plugin depends
    on. That signature is the load-bearing stable contract.
    """

    app: "FastAPI"
    # Free-form key/value bag for future seams (kernel, registries, config).
    # Kept generic on purpose so the contract stays stable as seams grow.
    extras: dict[str, Any] = field(default_factory=dict)


def discover_plugins() -> list[tuple[str, Callable[[AppContext], None]]]:
    """Return ``(name, register_callable)`` for each installed plugin.

    Never raises: an entry point that fails to load is logged and skipped so a
    single bad plugin can't take down the whole server.
    """
    found: list[tuple[str, Callable[[AppContext], None]]] = []
    try:
        eps = entry_points()
        # Python 3.10+ selectable API; the group kwarg is available on 3.10
        # via the compatibility shim and natively on 3.12.
        group = eps.select(group=PLUGIN_GROUP) if hasattr(eps, "select") else []
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Plugin discovery failed: %s", exc)
        return found

    for ep in group:
        try:
            register = ep.load()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load plugin %r: %s", ep.name, exc)
            continue
        if not callable(register):
            logger.warning(
                "Plugin %r entry point is not callable; skipping", ep.name
            )
            continue
        found.append((ep.name, register))
    return found


def load_plugins(app: "FastAPI", extras: dict[str, Any] | None = None) -> list[str]:
    """Discover and activate all installed MemoGraph plugins against ``app``.

    Returns the list of plugin names that activated successfully. Idempotent
    per app instance. Safe to call when no plugins are installed (returns []).
    """
    if getattr(app.state, _LOADED_FLAG, False):
        return list(getattr(app.state, "_memograph_active_plugins", []))

    context = AppContext(app=app, extras=extras or {})
    activated: list[str] = []
    for name, register in discover_plugins():
        try:
            register(context)
        except Exception as exc:  # noqa: BLE001
            logger.error("Plugin %r failed during activation: %s", name, exc)
            continue
        activated.append(name)
        logger.info("Activated MemoGraph plugin: %s", name)

    setattr(app.state, _LOADED_FLAG, True)
    setattr(app.state, "_memograph_active_plugins", activated)
    if not activated:
        logger.debug("No MemoGraph plugins installed (seam is a no-op).")
    return activated


__all__ = ["AppContext", "PLUGIN_GROUP", "discover_plugins", "load_plugins"]
