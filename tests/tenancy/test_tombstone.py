"""Unit tests for the tenant deletion tombstone primitives."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memograph.storage.tombstone import (
    DEFAULT_GRACE_DAYS,
    TOMBSTONE_FILENAME,
    TOMBSTONE_SCHEMA_VERSION,
    Tombstone,
    TombstoneError,
    clear_tombstone,
    is_tombstoned,
    read_tombstone,
    tombstone_path,
    write_tombstone,
)


@pytest.fixture
def tenant_dir(tmp_path: Path) -> Path:
    d = tmp_path / "acme"
    d.mkdir()
    return d


def test_no_tombstone_initially(tenant_dir):
    assert is_tombstoned(tenant_dir) is False
    assert read_tombstone(tenant_dir) is None


def test_write_then_read_roundtrip(tenant_dir):
    tomb = write_tombstone(
        tenant_dir, requested_by="user-1", grace_days=3, reason="GDPR ticket #42"
    )
    assert is_tombstoned(tenant_dir)

    parsed = read_tombstone(tenant_dir)
    assert parsed == tomb
    assert parsed.requested_by == "user-1"
    assert parsed.reason == "GDPR ticket #42"
    assert parsed.schema_version == TOMBSTONE_SCHEMA_VERSION


def test_default_grace_period(tenant_dir):
    tomb = write_tombstone(tenant_dir, requested_by="u")
    delta = datetime.fromisoformat(tomb.delete_after) - datetime.fromisoformat(
        tomb.scheduled_at
    )
    assert delta == timedelta(days=DEFAULT_GRACE_DAYS)


def test_negative_grace_rejected(tenant_dir):
    with pytest.raises(ValueError):
        write_tombstone(tenant_dir, requested_by="u", grace_days=-1)


def test_double_write_refused(tenant_dir):
    write_tombstone(tenant_dir, requested_by="u", grace_days=1)
    with pytest.raises(TombstoneError):
        write_tombstone(tenant_dir, requested_by="u", grace_days=99)


def test_clear_removes_file(tenant_dir):
    write_tombstone(tenant_dir, requested_by="u")
    assert clear_tombstone(tenant_dir) is True
    assert is_tombstoned(tenant_dir) is False
    # Idempotent: second call returns False, doesn't raise.
    assert clear_tombstone(tenant_dir) is False


def test_clear_then_rewrite_succeeds(tenant_dir):
    write_tombstone(tenant_dir, requested_by="u", grace_days=1)
    clear_tombstone(tenant_dir)
    # Now we should be able to write a fresh one.
    again = write_tombstone(tenant_dir, requested_by="u", grace_days=99)
    assert again.delete_after > again.scheduled_at


def test_zero_grace_is_immediately_expired(tenant_dir):
    tomb = write_tombstone(tenant_dir, requested_by="u", grace_days=0)
    # delete_after is "now"; the reaper should treat this as expired.
    assert tomb.is_expired


def test_future_grace_not_expired(tenant_dir):
    tomb = write_tombstone(tenant_dir, requested_by="u", grace_days=7)
    assert tomb.is_expired is False


def test_malformed_tombstone_raises(tenant_dir):
    tombstone_path(tenant_dir).write_text("not json", encoding="utf-8")
    with pytest.raises(TombstoneError):
        read_tombstone(tenant_dir)


def test_wrong_schema_version_rejected(tenant_dir):
    tombstone_path(tenant_dir).write_text(
        json.dumps({"schema_version": 999}), encoding="utf-8"
    )
    with pytest.raises(TombstoneError):
        read_tombstone(tenant_dir)


def test_missing_required_fields_rejected(tenant_dir):
    tombstone_path(tenant_dir).write_text(
        json.dumps({"schema_version": TOMBSTONE_SCHEMA_VERSION}),
        encoding="utf-8",
    )
    with pytest.raises(TombstoneError):
        read_tombstone(tenant_dir)


def test_filename_is_underscored_not_dotted():
    """Defensive: tombstone must NOT be a dotfile because
    TenantStorage.list_tenants skips dot-prefixed entries (which would
    apply to files inside the dir as well — but only the dir itself
    matters for that pruner). Documenting the choice via this test."""
    assert TOMBSTONE_FILENAME == "_tombstone.json"
    assert not TOMBSTONE_FILENAME.startswith(".")


def test_is_expired_threshold_exact(tenant_dir):
    """A tombstone whose ``delete_after`` is in the past is expired."""
    delete_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    scheduled = delete_after - timedelta(days=7)
    Tombstone(
        schema_version=TOMBSTONE_SCHEMA_VERSION,
        scheduled_at=scheduled.isoformat(),
        delete_after=delete_after.isoformat(),
        requested_by="u",
    ).is_expired is True
