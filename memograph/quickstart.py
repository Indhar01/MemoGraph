"""``memograph quickstart`` — get a new user from install to wow in <60 s.

The command materialises a small, interconnected sample vault on
disk, ingests it, runs three illustrative queries, and prints
next-step pointers. Single-shot; no interactive prompts; no
network calls.

The sample vault is bundled with the package under
``memograph/data/sample_vault/``. We copy rather than symlink so
the user can edit and break things freely without needing to
reinstall.

This module is intentionally small and dependency-free (just
:class:`MemoryKernel` from the public API). It's the new user's
first experience with the project; any failure here is a
disproportionate hit to first-impression conversion.
"""

from __future__ import annotations

import shutil
import sys
from importlib import resources
from pathlib import Path

from memograph.core.kernel import MemoryKernel


_SAMPLE_QUERIES: list[tuple[str, str]] = [
    (
        "should I use async or threads",
        "Demonstrates hybrid retrieval: keyword 'async' and "
        "'threads' surface multiple memories, then graph traversal "
        "stitches them together.",
    ),
    (
        "lockfile",
        "Demonstrates graph depth: 'lockfile' is mentioned in one "
        "memory, but the relevant decision lives one wikilink hop "
        "away.",
    ),
    (
        "FastAPI dependency injection",
        "Demonstrates type-aware retrieval: surfaces the FastAPI "
        "memories with semantic understanding, even when the query "
        "wording differs from what's in the notes.",
    ),
]


def _sample_vault_source() -> Path:
    """Locate the bundled sample-vault directory inside the package.

    Uses :func:`importlib.resources.files` so this works whether
    the package is installed editable, from a wheel, or from a
    zip-imported environment (e.g. PEX).
    """
    return Path(str(resources.files("memograph") / "data" / "sample_vault"))


def materialise_vault(target: Path, *, force: bool = False) -> int:
    """Copy the bundled sample vault to ``target``.

    Returns the number of files copied. Refuses to overwrite a
    non-empty existing vault unless ``force=True`` — the user's
    real notes shouldn't be clobbered by a misclick.
    """
    target = target.expanduser().resolve()

    if target.exists() and any(target.iterdir()):
        if not force:
            raise FileExistsError(
                f"target {target} is not empty; pass --force to overwrite"
            )
        shutil.rmtree(target)

    target.mkdir(parents=True, exist_ok=True)
    source = _sample_vault_source()

    copied = 0
    for entry in source.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix != ".md":
            continue
        shutil.copy2(entry, target / entry.name)
        copied += 1
    return copied


def _run_mcp_bridge(vault_path: str, *, apply: bool, out) -> None:
    """Detect installed MCP clients and wire the quickstart vault.

    Preview-only by default. The user has to explicitly opt-in to
    writes via ``apply=True`` so the quickstart never silently
    mutates files outside its own target directory — a property
    that matters when the user inevitably runs ``--mcp`` to see
    what *would* happen before deciding.
    """
    print("─" * 60, file=out)
    print("🔌 MCP bridge — wiring this vault into your AI clients\n", file=out)
    try:
        from memograph.mcp_setup import MCPSetup
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  MCP setup unavailable: {exc}", file=out)
        return

    setup = MCPSetup(vault_path=vault_path)
    result = setup.quickstart_setup(vault_path, apply=apply)

    if not result["detected"]:
        print(
            "No MCP clients detected on this machine. Install Claude "
            "Desktop, Cursor, or Cline, then re-run with --mcp.",
            file=out,
        )
        print(
            "Manual setup snippets: docs/MCP_CLIENTS.md "
            "(15+ clients, every config-file path).",
            file=out,
        )
        return

    print(f"Detected: {', '.join(result['detected'])}\n", file=out)
    for action in result["actions"]:
        icon = {
            "would_write": "📝",
            "written": "✓",
            "skipped": "·",
            "error": "❌",
        }.get(action["status"], "?")
        print(f"  {icon} {action['client']}", file=out)
        print(f"     {action['config_path']}", file=out)
        print(f"     {action['message']}", file=out)
        print(file=out)

    if not apply:
        print(
            "Re-run with --mcp-apply to actually write the configs. "
            "After applying, restart your AI client.",
            file=out,
        )
    else:
        print(
            'All done. Open your AI client and ask: "Search my vault '
            'for python async."',
            file=out,
        )

    not_detected = result.get("not_detected") or []
    if not_detected:
        print(
            f"\nNot detected (skipped): {', '.join(not_detected)}",
            file=out,
        )


def run_quickstart(
    target: str | Path = "~/memograph-quickstart",
    *,
    force: bool = False,
    mcp: bool = False,
    mcp_apply: bool = False,
    out=sys.stdout,
) -> int:
    """End-to-end quickstart flow.

    1. Materialise the sample vault at ``target``.
    2. Build a :class:`MemoryKernel` against it and ingest.
    3. Run the three sample queries; print top results.
    4. Print next-step pointers.

    Returns 0 on success, non-zero exit code on a recognised
    failure mode (e.g. target not empty without ``--force``).
    """
    target_path = Path(str(target)).expanduser().resolve()

    print("🚀 MemoGraph quickstart\n", file=out)

    try:
        copied = materialise_vault(target_path, force=force)
    except FileExistsError as exc:
        print(f"❌ {exc}", file=out)
        print(
            "   re-run with --force to replace the existing vault, or "
            "pass --vault PATH to pick a different location.",
            file=out,
        )
        return 2

    print(f"✓ Sample vault created at {target_path}", file=out)
    print(f"  {copied} interconnected memories on Python development\n", file=out)

    kernel = MemoryKernel(str(target_path))
    stats = kernel.ingest(force=True)
    indexed = stats.get("total", stats.get("indexed", copied))
    print(f"✓ Indexed {indexed} memories into the graph\n", file=out)

    print("Sample queries — these run live against the vault:\n", file=out)
    for i, (query, why) in enumerate(_SAMPLE_QUERIES, 1):
        print(f'  [{i}] memograph --vault {target_path} search "{query}"', file=out)
        results = kernel.retrieve_nodes(query, top_k=3, depth=1)
        for j, node in enumerate(results[:3], 1):
            title = getattr(node, "title", "?")
            salience = getattr(node, "salience", 0.0)
            print(f"      {j}. {title}  (salience {salience:.2f})", file=out)
        print(f"      → {why}\n", file=out)

    print("Try it yourself:\n", file=out)
    print(
        f'  memograph --vault {target_path} search "any question"',
        file=out,
    )
    print(
        f"  memograph --vault {target_path} stats",
        file=out,
    )
    print(
        f"  memograph --vault {target_path} list",
        file=out,
    )
    print(file=out)

    mcp_bullet = (
        "  • Wire MemoGraph into your AI assistant — re-run with --mcp "
        "to do this automatically.\n"
        if not mcp
        else ""
    )
    print(
        "Next steps:\n"
        "  • Open the vault directory in any editor — the notes are plain "
        ".md files.\n"
        "  • Add your own notes; MemoGraph picks them up on the next "
        "ingest.\n"
        f"{mcp_bullet}"
        "  • Hosting it for a team? docs/HOSTING_GUIDE.md covers free "
        "options.",
        file=out,
    )

    if mcp:
        print(file=out)
        _run_mcp_bridge(str(target_path), apply=mcp_apply, out=out)

    return 0
