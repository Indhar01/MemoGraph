"""Tests for the open-core seam prep (extraction manifest steps 2-3).

- memograph.core.identity: neutral identity provider seam.
- AppContext widening: kernel handle + vault_path helper + override_auth.
- action_logger uses the seam (no direct auth import).

See docs/EXTRACTION_MANIFEST.md.
"""

from __future__ import annotations

import pytest

from memograph.core import identity


@pytest.fixture(autouse=True)
def _reset_identity_provider():
    # Ensure a clean provider around each test (auth import may have set one).
    identity.set_identity_provider(None)
    yield
    identity.set_identity_provider(None)


class TestIdentitySeam:
    def test_default_is_anonymous(self):
        assert identity.current_identity() == (None, None)

    def test_provider_is_used(self):
        identity.set_identity_provider(lambda: ("user-1", "acme"))
        assert identity.current_identity() == ("user-1", "acme")

    def test_reset_to_anonymous(self):
        identity.set_identity_provider(lambda: ("u", "t"))
        identity.set_identity_provider(None)
        assert identity.current_identity() == (None, None)

    def test_broken_provider_degrades_to_anonymous(self):
        def boom():
            raise RuntimeError("provider exploded")

        identity.set_identity_provider(boom)
        # Must not raise; audited operations should never fail on identity.
        assert identity.current_identity() == (None, None)


class TestActionLoggerUsesSeam:
    def test_identity_from_context_reads_seam(self):
        from memograph.core.action_logger import _identity_from_context

        identity.set_identity_provider(lambda: ("user-42", "tenant-x"))
        assert _identity_from_context() == ("user-42", "tenant-x")

    def test_action_logger_does_not_import_auth_directly(self):
        # The core action_logger source must not statically import the
        # (soon-private) web auth module.
        import pathlib

        src = pathlib.Path("memograph/core/action_logger.py").read_text(
            encoding="utf-8"
        )
        assert "from memograph.web.backend.auth import" not in src


class TestAppContextWidening:
    def test_kernel_field_and_vault_path_helper(self):
        from unittest.mock import MagicMock

        from memograph.plugins import AppContext

        app = MagicMock()
        app.state.vault_path = None
        kernel = MagicMock()
        kernel.vault_path = "/tmp/my-vault"
        ctx = AppContext(app=app, kernel=kernel)
        assert ctx.kernel is kernel
        assert ctx.vault_path == "/tmp/my-vault"

    def test_vault_path_falls_back_to_extras(self):
        from unittest.mock import MagicMock

        from memograph.plugins import AppContext

        app = MagicMock()
        app.state.vault_path = None
        ctx = AppContext(app=app, extras={"vault_path": "/from/extras"})
        assert ctx.vault_path == "/from/extras"

    def test_backward_compat_construction(self):
        # Old call sites pass only app (+extras); kernel defaults to None.
        from unittest.mock import MagicMock

        from memograph.plugins import AppContext

        ctx = AppContext(app=MagicMock(), extras={"vault_path": "x"})
        assert ctx.kernel is None

    def test_load_plugins_accepts_kernel_kwarg(self):
        # Widened signature must remain callable with no plugins installed.
        from unittest.mock import MagicMock

        from memograph.plugins import load_plugins

        app = MagicMock()
        app.state = MagicMock()
        # No plugins installed -> returns [] and doesn't raise.
        result = load_plugins(app, extras={"vault_path": "x"}, kernel=MagicMock())
        assert result == [] or isinstance(result, list)
