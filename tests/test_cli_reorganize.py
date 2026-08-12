"""Tests for `memograph reorganize` (Step 6).

Drives the HierarchyResolver + VaultStorage.move via the CLI. Dry-run by
default; --apply moves files. See docs/ADR_SELF_ORGANIZING_HIERARCHY.md.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from memograph.cli import main


@pytest.fixture
def flat_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    notes = [
        ("Python Async", "semantic", "async await coroutines"),
        ("Team Standup", "episodic", "we discussed goals"),
        ("Config Value", "fact", "timeout = 30"),
    ]
    for title, mtype, body in notes:
        slug = title.lower().replace(" ", "-")
        (vault / f"{slug}.md").write_text(
            f"---\nid: {slug}\ntitle: {title}\nmemory_type: {mtype}\n---\n\n{body}\n",
            encoding="utf-8",
        )
    return vault


class TestReorganizeCLI:
    def test_dry_run_prints_plan_no_moves(self, flat_vault, capsys):
        with patch(
            "sys.argv",
            [
                "memograph",
                "--vault",
                str(flat_vault),
                "reorganize",
                "--strategy",
                "by_type",
            ],
        ):
            main()
        out = capsys.readouterr().out
        assert "Planned moves" in out
        assert "semantic/python-async.md" in out
        assert "Dry-run only" in out
        # No files actually moved.
        assert (flat_vault / "python-async.md").exists()
        assert not (flat_vault / "semantic").exists()

    def test_apply_moves_files(self, flat_vault, capsys):
        with patch(
            "sys.argv",
            [
                "memograph",
                "--vault",
                str(flat_vault),
                "reorganize",
                "--strategy",
                "by_type",
                "--apply",
                "--yes",
            ],
        ):
            main()
        out = capsys.readouterr().out
        assert "Moved 3 file(s)" in out
        assert (flat_vault / "semantic" / "python-async.md").exists()
        assert (flat_vault / "episodic" / "team-standup.md").exists()
        assert (flat_vault / "fact" / "config-value.md").exists()
        assert not (flat_vault / "python-async.md").exists()

    def test_apply_preserves_retrieval(self, flat_vault, capsys):
        with patch(
            "sys.argv",
            [
                "memograph",
                "--vault",
                str(flat_vault),
                "reorganize",
                "--strategy",
                "by_type",
                "--apply",
                "--yes",
            ],
        ):
            main()
        capsys.readouterr()
        # After reorg, retrieval by id must still work via a fresh kernel.
        from memograph.core.kernel import MemoryKernel

        k = MemoryKernel(vault_path=str(flat_vault))
        k.ingest(force=True)
        assert k.graph.get("python-async") is not None
        results = k.retrieve_nodes(query="async coroutines", top_k=2, use_cache=False)
        assert results and results[0].id == "python-async"

    def test_flat_strategy_nothing_to_do(self, flat_vault, capsys):
        with patch(
            "sys.argv",
            [
                "memograph",
                "--vault",
                str(flat_vault),
                "reorganize",
                "--strategy",
                "flat",
            ],
        ):
            main()
        out = capsys.readouterr().out
        assert "Nothing to reorganize" in out

    def test_idempotent_after_apply(self, flat_vault, capsys):
        argv = [
            "memograph",
            "--vault",
            str(flat_vault),
            "reorganize",
            "--strategy",
            "by_type",
            "--apply",
            "--yes",
        ]
        with patch("sys.argv", argv):
            main()
        capsys.readouterr()
        # Second dry-run should find nothing.
        with patch(
            "sys.argv",
            [
                "memograph",
                "--vault",
                str(flat_vault),
                "reorganize",
                "--strategy",
                "by_type",
            ],
        ):
            main()
        out = capsys.readouterr().out
        assert "Nothing to reorganize" in out

    def test_json_format(self, flat_vault, capsys):
        with patch(
            "sys.argv",
            [
                "memograph",
                "--vault",
                str(flat_vault),
                "reorganize",
                "--strategy",
                "by_type",
                "--format",
                "json",
            ],
        ):
            main()
        out = capsys.readouterr().out
        import json as _json

        # The JSON object is the last block printed; find it.
        start = out.index("{")
        data = _json.loads(out[start:])
        assert data["strategy"] == "by_type"
        assert data["count"] == 3
        assert data["apply"] is False

    def test_apply_aborted_by_prompt(self, flat_vault, capsys):
        with patch(
            "sys.argv",
            [
                "memograph",
                "--vault",
                str(flat_vault),
                "reorganize",
                "--strategy",
                "by_type",
                "--apply",
            ],
        ), patch("builtins.input", return_value="n"):
            main()
        out = capsys.readouterr().out
        assert "Aborted" in out
        assert (flat_vault / "python-async.md").exists()  # not moved
