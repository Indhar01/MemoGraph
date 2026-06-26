"""Tests for the source audit log helpers."""

from __future__ import annotations

import json
from pathlib import Path

from memograph.sources import audit


class TestRecord:
    def test_writes_one_jsonl_line_per_call(self, tmp_path: Path) -> None:
        audit.record(
            sources_dir=tmp_path,
            action=audit.ACTION_CREATE,
            source_id="primary",
            source_kind="local",
            user_id="alice",
            tenant_id="tenant-a",
            request_id="req-001",
            after={"display_name": "Primary"},
        )
        audit.record(
            sources_dir=tmp_path,
            action=audit.ACTION_DELETE,
            source_id="primary",
            source_kind="local",
            user_id="alice",
            tenant_id="tenant-a",
            request_id="req-002",
        )
        log = tmp_path / "_audit.log"
        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["action"] == "source.create"
        assert first["user_id"] == "alice"
        assert first["request_id"] == "req-001"

    def test_creates_dir_if_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "deeply" / "nested"
        audit.record(
            sources_dir=target,
            action=audit.ACTION_CREATE,
            source_id="x",
            source_kind="local",
        )
        assert (target / "_audit.log").exists()

    def test_never_raises_on_io_error(self, tmp_path: Path, monkeypatch) -> None:
        # Audit failures must not propagate. Point the audit at an
        # impossible path and verify we don't blow up.
        bad = tmp_path / "file-not-dir"
        bad.write_text("oops")
        # Recording to a path whose parent is a file (not a dir)
        # would normally raise; record() must swallow the error.
        audit.record(
            sources_dir=bad / "below-the-file",
            action=audit.ACTION_CREATE,
            source_id="x",
            source_kind="local",
        )


class TestReadEntries:
    def test_returns_newest_first(self, tmp_path: Path) -> None:
        for i in range(3):
            audit.record(
                sources_dir=tmp_path,
                action=audit.ACTION_CREATE,
                source_id=f"s{i}",
                source_kind="local",
            )
        entries = audit.read_entries(tmp_path)
        assert [e["source_id"] for e in entries] == ["s2", "s1", "s0"]

    def test_respects_limit(self, tmp_path: Path) -> None:
        for i in range(5):
            audit.record(
                sources_dir=tmp_path,
                action=audit.ACTION_CREATE,
                source_id=f"s{i}",
                source_kind="local",
            )
        entries = audit.read_entries(tmp_path, limit=2)
        assert len(entries) == 2
        assert entries[0]["source_id"] == "s4"

    def test_empty_when_no_log(self, tmp_path: Path) -> None:
        assert audit.read_entries(tmp_path) == []

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        log = tmp_path / "_audit.log"
        log.write_text(
            '{"action": "source.create", "source_id": "good"}\n'
            "not json at all\n"
            '{"action": "source.delete", "source_id": "also-good"}\n',
            encoding="utf-8",
        )
        entries = audit.read_entries(tmp_path)
        ids = sorted(e["source_id"] for e in entries)
        assert ids == ["also-good", "good"]
