"""Tests for Phase 1.3 cache schema versioning.

Round-trip semantics, legacy v0 acceptance, malformed-input tolerance,
and unknown-future-version rejection.
"""

from __future__ import annotations

import json

import pytest

from memograph.storage.cache import (
    CURRENT_SCHEMA_VERSION,
    CacheSchemaError,
    JsonCache,
)


def test_save_emits_envelope(tmp_path):
    cache = JsonCache(tmp_path / "c.json")
    cache.save({"a": 1, "b": [1, 2, 3]})
    raw = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    assert raw == {
        "_schema_version": CURRENT_SCHEMA_VERSION,
        "data": {"a": 1, "b": [1, 2, 3]},
    }


def test_round_trip(tmp_path):
    cache = JsonCache(tmp_path / "c.json")
    payload = {"x": "y", "n": 42}
    cache.save(payload)
    assert cache.load() == payload


def test_legacy_v0_payload_loaded_as_is(tmp_path):
    legacy = {"foo": "bar", "n": 1}
    (tmp_path / "c.json").write_text(json.dumps(legacy), encoding="utf-8")
    assert JsonCache(tmp_path / "c.json").load() == legacy


def test_missing_file_returns_empty(tmp_path):
    assert JsonCache(tmp_path / "missing.json").load() == {}


def test_corrupt_json_returns_empty(tmp_path):
    (tmp_path / "c.json").write_text("{not valid json", encoding="utf-8")
    assert JsonCache(tmp_path / "c.json").load() == {}


def test_non_dict_top_level_returns_empty(tmp_path):
    (tmp_path / "c.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert JsonCache(tmp_path / "c.json").load() == {}


def test_unknown_future_version_raises(tmp_path):
    future = {"_schema_version": CURRENT_SCHEMA_VERSION + 99, "data": {"a": 1}}
    (tmp_path / "c.json").write_text(json.dumps(future), encoding="utf-8")
    with pytest.raises(CacheSchemaError, match="unknown schema version"):
        JsonCache(tmp_path / "c.json").load()


def test_data_key_missing_in_envelope_returns_empty(tmp_path):
    # Versioned but missing "data" — treat as empty rather than crash.
    bad = {"_schema_version": CURRENT_SCHEMA_VERSION}
    (tmp_path / "c.json").write_text(json.dumps(bad), encoding="utf-8")
    assert JsonCache(tmp_path / "c.json").load() == {}
