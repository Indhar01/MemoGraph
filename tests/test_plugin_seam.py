"""Tests for the public plugin seam (memograph/plugins.py).

The seam is the stable extension point the private enterprise layer plugs
into. These tests use a fake in-process plugin (via monkeypatched discovery)
so they need no external package installed. They assert the four properties
that keep the open-core boundary safe:

    1. A stock install with no plugins is a no-op.
    2. A discovered plugin's register(context) is called with the app.
    3. Activation is idempotent per app instance (test reloads won't double-fire).
    4. A broken plugin is isolated: it logs and is skipped, never crashing load.
"""

from __future__ import annotations

import pytest

from memograph import plugins


class _FakeApp:
    """Minimal stand-in for FastAPI: just needs a mutable .state."""

    class _State:
        pass

    def __init__(self) -> None:
        self.state = _FakeApp._State()


def test_no_plugins_is_noop(monkeypatch):
    monkeypatch.setattr(plugins, "discover_plugins", lambda: [])
    app = _FakeApp()
    active = plugins.load_plugins(app)  # type: ignore[arg-type]
    assert active == []


def test_plugin_register_is_called_with_context(monkeypatch):
    seen = {}

    def fake_register(context):
        seen["app"] = context.app
        seen["vault"] = context.extras.get("vault_path")
        context.app.state.plugin_touched = True

    monkeypatch.setattr(
        plugins, "discover_plugins", lambda: [("fake", fake_register)]
    )
    app = _FakeApp()
    active = plugins.load_plugins(app, extras={"vault_path": "/tmp/v"})  # type: ignore[arg-type]

    assert active == ["fake"]
    assert seen["app"] is app
    assert seen["vault"] == "/tmp/v"
    assert app.state.plugin_touched is True


def test_activation_is_idempotent(monkeypatch):
    calls = {"n": 0}

    def fake_register(context):
        calls["n"] += 1

    monkeypatch.setattr(
        plugins, "discover_plugins", lambda: [("fake", fake_register)]
    )
    app = _FakeApp()
    first = plugins.load_plugins(app)  # type: ignore[arg-type]
    second = plugins.load_plugins(app)  # type: ignore[arg-type]

    assert first == ["fake"]
    assert second == ["fake"]  # same list returned
    assert calls["n"] == 1  # register fired exactly once


def test_broken_plugin_is_isolated(monkeypatch):
    def good(context):
        context.app.state.good_ran = True

    def bad(context):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        plugins,
        "discover_plugins",
        lambda: [("bad", bad), ("good", good)],
    )
    app = _FakeApp()
    active = plugins.load_plugins(app)  # type: ignore[arg-type]

    # bad is skipped; good still activates.
    assert active == ["good"]
    assert getattr(app.state, "good_ran", False) is True


def test_discover_plugins_never_raises():
    # Real discovery against the installed environment must not raise even
    # if no plugins are present.
    result = plugins.discover_plugins()
    assert isinstance(result, list)
