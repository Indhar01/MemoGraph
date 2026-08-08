"""Tests for the source adapter-registry seam (memograph/sources/adapter_registry.py).

This seam lets out-of-tree plugins (memograph-enterprise) register source
adapters by SourceKind without the public package importing them. These tests
assert the contract: LOCAL ships built-in, unknown kinds are unregistered, and
registration/override/reset behave.
"""

from __future__ import annotations

import pytest

from memograph.sources import adapter_registry
from memograph.sources.base import Source, SourceConfig, SourceError, SourceKind
from memograph.sources.registry import default_source_factory


@pytest.fixture(autouse=True)
def _reset_registry():
    adapter_registry._reset_for_tests()
    yield
    adapter_registry._reset_for_tests()


def test_local_is_builtin():
    assert adapter_registry.is_registered(SourceKind.LOCAL)


def test_s3_not_registered_by_default():
    # S3 is a plugin capability; the stock public package must not ship it.
    assert not adapter_registry.is_registered(SourceKind.S3)


def test_unregistered_kind_raises_clear_error():
    cfg = SourceConfig(
        source_id="x", kind=SourceKind.S3, display_name="x", params={"bucket": "b"}
    )
    with pytest.raises(SourceError, match="no adapter registered"):
        default_source_factory(cfg)


def test_register_and_dispatch():
    class _Stub(Source):
        async def list_documents(self):  # pragma: no cover
            if False:
                yield None

        async def read_document(self, doc_id):  # pragma: no cover
            raise NotImplementedError

        async def write_document(self, doc):  # pragma: no cover
            raise NotImplementedError

        async def watch(self):  # pragma: no cover
            if False:
                yield None

        async def materialize_to_vault(self, vault_path):  # pragma: no cover
            raise NotImplementedError

        async def health(self):  # pragma: no cover
            raise NotImplementedError

    adapter_registry.register_source_adapter(SourceKind.S3, _Stub)
    cfg = SourceConfig(
        source_id="x", kind=SourceKind.S3, display_name="x", params={"bucket": "b"}
    )
    built = default_source_factory(cfg)
    assert isinstance(built, _Stub)


def test_register_is_idempotent_without_override():
    calls = {"n": 0}

    def factory_a(config):  # pragma: no cover - not invoked
        calls["n"] += 1

    def factory_b(config):  # pragma: no cover
        calls["n"] += 1

    adapter_registry.register_source_adapter(SourceKind.NOTION, factory_a)
    adapter_registry.register_source_adapter(SourceKind.NOTION, factory_b)  # ignored
    assert adapter_registry.get_source_adapter(SourceKind.NOTION) is factory_a

    adapter_registry.register_source_adapter(
        SourceKind.NOTION, factory_b, override=True
    )
    assert adapter_registry.get_source_adapter(SourceKind.NOTION) is factory_b
