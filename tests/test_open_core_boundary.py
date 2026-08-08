"""Open-core boundary guard.

The public ``memograph`` package must NEVER import the private product package
(``memograph_enterprise`` / ``memograph.enterprise``). Enterprise features
attach at runtime through the ``memograph.plugins`` entry-point seam
(``register(context)``), so a stock ``pip install memograph`` with no plugin
installed imports nothing private.

This test fails loudly if any public module gains a forbidden import, catching
the most common open-core mistake (a direct import creeping in) BEFORE it ships.
See docs/PUBLIC_VS_PRIVATE_SPLIT.md.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# Namespaces reserved for the private product layer. The public package must
# not statically import any of these.
_FORBIDDEN_PREFIXES = (
    "memograph_enterprise",
    "memograph.enterprise",
)

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent / "memograph"


def _python_files() -> list[pathlib.Path]:
    return [
        p
        for p in _PACKAGE_ROOT.rglob("*.py")
        # Skip vendored / build artifacts if any ever appear.
        if "node_modules" not in p.parts and "__pycache__" not in p.parts
    ]


def _imported_modules(tree: ast.AST) -> list[str]:
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Ignore relative imports (node.level > 0); they can't reach the
            # private top-level package. Absolute ImportFrom has a module name.
            if node.level == 0 and node.module:
                mods.append(node.module)
    return mods


def _is_forbidden(module: str) -> bool:
    return any(
        module == prefix or module.startswith(prefix + ".")
        for prefix in _FORBIDDEN_PREFIXES
    )


def test_public_package_never_imports_private():
    offenders: list[str] = []
    for py in _python_files():
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover
            pytest.fail(f"could not parse {py}: {exc}")
        for module in _imported_modules(tree):
            if _is_forbidden(module):
                rel = py.relative_to(_PACKAGE_ROOT.parent)
                offenders.append(f"{rel} imports private module '{module}'")

    assert not offenders, (
        "Public package must not import the private product layer "
        "(use the memograph.plugins entry-point seam instead):\n  "
        + "\n  ".join(offenders)
    )


def test_plugin_seam_exists():
    """The seam the private layer attaches through must remain importable."""
    from memograph.plugins import AppContext, load_plugins

    assert callable(load_plugins)
    assert AppContext is not None
