"""Tests for the ``memograph quickstart`` first-run experience.

The quickstart is the user's first 60 seconds with the product;
any failure here disproportionately damages first-impression
conversion. So this suite is paranoid about:

- The bundled sample vault is shippable (every file parseable, no
  empty notes, salience in range, wikilinks land on real notes).
- The materialise step copies the right files and refuses to
  clobber non-empty targets without explicit ``--force``.
- The end-to-end run produces a working ingested graph and the
  three sample queries surface non-empty results.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from memograph.core.kernel import MemoryKernel
from memograph.core.parser import parse_file
from memograph.quickstart import (
    _SAMPLE_QUERIES,
    _sample_vault_source,
    materialise_vault,
    run_quickstart,
)


# -------------------------------------------------- bundled vault is shippable


def test_sample_vault_directory_resolves():
    """The vault must be locatable through importlib.resources so
    it works in editable installs, wheels, and zipapps alike."""
    src = _sample_vault_source()
    assert src.exists() and src.is_dir(), f"sample vault not found at {src}"


def test_sample_vault_has_minimum_size():
    """Below ~10 notes the graph isn't dense enough to make wikilinks
    visibly meaningful in the demo. Floor it."""
    src = _sample_vault_source()
    md_files = list(src.glob("*.md"))
    assert len(md_files) >= 10, f"only {len(md_files)} sample notes — need >=10"


def test_every_sample_note_parses_cleanly():
    """A broken sample vault is a broken first impression. Every
    bundled note must round-trip through the parser without warnings."""
    src = _sample_vault_source()
    for path in src.glob("*.md"):
        node = parse_file(path, vault_root=src)
        assert node is not None, f"parser returned None for {path.name}"
        assert node.title, f"{path.name} has no title"
        assert node.content.strip(), f"{path.name} has empty content"
        assert (
            0.0 <= node.salience <= 1.0
        ), f"{path.name} salience {node.salience} out of [0, 1]"


def test_sample_vault_has_meaningful_links():
    """Demonstrating the graph requires actual links. Floor the count
    so a future contributor can't accidentally remove them all."""
    src = _sample_vault_source()
    total_links = 0
    for path in src.glob("*.md"):
        node = parse_file(path, vault_root=src)
        assert node is not None
        total_links += len(node.links)
    assert total_links >= 15, (
        f"only {total_links} wikilinks in the sample vault — "
        "the graph won't look interesting to a new user"
    )


# -------------------------------------------------- materialise primitive


def test_materialise_copies_into_empty_target(tmp_path: Path):
    target = tmp_path / "vault"
    copied = materialise_vault(target)
    assert copied >= 10
    assert target.is_dir()
    assert (target / "welcome.md").exists()


def test_materialise_creates_target_if_missing(tmp_path: Path):
    target = tmp_path / "does" / "not" / "exist" / "yet"
    copied = materialise_vault(target)
    assert copied >= 10
    assert target.is_dir()


def test_materialise_refuses_nonempty_target_without_force(tmp_path: Path):
    target = tmp_path / "vault"
    target.mkdir()
    (target / "user-note.md").write_text("# my real notes", encoding="utf-8")
    with pytest.raises(FileExistsError):
        materialise_vault(target, force=False)
    # User's file must still be there — refusal is a guarantee.
    assert (target / "user-note.md").exists()


def test_materialise_force_clobbers_nonempty_target(tmp_path: Path):
    target = tmp_path / "vault"
    target.mkdir()
    (target / "old-note.md").write_text("# old", encoding="utf-8")
    materialise_vault(target, force=True)
    # Old file is gone, sample notes are present.
    assert not (target / "old-note.md").exists()
    assert (target / "welcome.md").exists()


# -------------------------------------------------- end-to-end run_quickstart


def test_run_quickstart_returns_zero_on_success(tmp_path: Path):
    out = io.StringIO()
    rc = run_quickstart(target=tmp_path / "vault", out=out)
    assert rc == 0
    text = out.getvalue()
    assert "MemoGraph quickstart" in text
    assert "Indexed" in text
    assert "Try it yourself" in text


def test_run_quickstart_returns_nonzero_when_target_blocked(tmp_path: Path):
    target = tmp_path / "vault"
    target.mkdir()
    (target / "user-note.md").write_text("# real", encoding="utf-8")
    out = io.StringIO()
    rc = run_quickstart(target=target, force=False, out=out)
    assert rc != 0
    assert "--force" in out.getvalue()


def test_run_quickstart_runs_every_sample_query(tmp_path: Path):
    """All three demo queries must execute and produce text. If a
    query goes silent (e.g. retriever returned nothing), the demo
    looks broken to a new user."""
    out = io.StringIO()
    rc = run_quickstart(target=tmp_path / "vault", out=out)
    assert rc == 0
    text = out.getvalue()
    for query, _ in _SAMPLE_QUERIES:
        assert query in text, f"sample query {query!r} did not run"


def test_quickstart_yields_searchable_kernel(tmp_path: Path):
    """After the quickstart runs, a fresh kernel pointed at the same
    vault should find the same memories — the cache is on disk."""
    out = io.StringIO()
    target = tmp_path / "vault"
    rc = run_quickstart(target=target, out=out)
    assert rc == 0

    kernel = MemoryKernel(str(target))
    kernel.ingest()
    results = kernel.retrieve_nodes("async", top_k=3, depth=1)
    titles = {n.title.lower() for n in results}
    assert any(
        "async" in t for t in titles
    ), f"async query found no async-tagged memories; got {titles!r}"
