"""Tests for the MCP quickstart bridge (``memograph quickstart --mcp``).

The bridge is the second-most-important first-impression surface
after the quickstart itself: it's what turns "I see the demo" into
"my AI assistant uses this." Failing silently here means the
funnel breaks at the activation step.

Coverage areas:

- Preview mode (``apply=False``) never touches the filesystem.
- Apply mode writes the expected config snippet and deep-merges
  with existing servers rather than clobbering them.
- The result dict shape is stable (the quickstart CLI prints it).
- Clients without a config directory present are skipped, not
  hallucinated into existence.
- Cursor + Claude Desktop + Cline + VS Code Cline get the right
  per-client config shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


from memograph.mcp_setup import MCPClient, MCPSetup


# ---------------------------------------------------- helpers / fixtures


def _setup_with_fake_clients(
    tmp_path: Path, *, detected: list[str] | None = None
) -> MCPSetup:
    """Build an MCPSetup whose detected clients all live under tmp_path.

    Lets each test control exactly which clients are 'installed' and
    where their config files go, without writing into the real user's
    home dir.
    """
    detected = detected or ["Claude Desktop", "Cursor", "Cline CLI"]
    setup = MCPSetup(vault_path=str(tmp_path / "vault"))

    fake_clients = []
    config_paths = {
        "Claude Desktop": tmp_path / "claude" / "claude_desktop_config.json",
        "Cursor": tmp_path / ".cursor" / "mcp.json",
        "Cline CLI": tmp_path / ".cline" / "mcp_settings.json",
        "VS Code Cline Extension": tmp_path / "code-user" / "settings.json",
    }
    for name, path in config_paths.items():
        is_detected = name in detected
        if is_detected:
            path.parent.mkdir(parents=True, exist_ok=True)
        fake_clients.append(MCPClient(name, path, detected=is_detected))

    setup.clients = fake_clients
    return setup


# --------------------------------------------- preview mode is read-only


def test_preview_mode_writes_no_files(tmp_path: Path):
    setup = _setup_with_fake_clients(tmp_path)
    result = setup.quickstart_setup(str(tmp_path / "vault"), apply=False)

    # All actions are 'would_write'
    statuses = {a["status"] for a in result["actions"]}
    assert statuses == {"would_write"}

    # No config files materialized
    for action in result["actions"]:
        assert not Path(
            action["config_path"]
        ).exists(), f"preview mode wrote {action['config_path']}"


def test_preview_returns_per_client_action(tmp_path: Path):
    setup = _setup_with_fake_clients(tmp_path, detected=["Claude Desktop", "Cursor"])
    result = setup.quickstart_setup(str(tmp_path / "vault"), apply=False)
    names = {a["client"] for a in result["actions"]}
    assert names == {"Claude Desktop", "Cursor"}


def test_undetected_clients_appear_in_not_detected(tmp_path: Path):
    setup = _setup_with_fake_clients(tmp_path, detected=["Cursor"])
    result = setup.quickstart_setup(str(tmp_path / "vault"), apply=False)
    assert result["detected"] == ["Cursor"]
    # The other three known clients should be in not_detected.
    assert "Claude Desktop" in result["not_detected"]
    assert "Cline CLI" in result["not_detected"]


# --------------------------------------------- apply mode writes correctly


def test_apply_mode_writes_claude_desktop_config(tmp_path: Path):
    setup = _setup_with_fake_clients(tmp_path, detected=["Claude Desktop"])
    vault = str(tmp_path / "vault")
    result = setup.quickstart_setup(vault, apply=True)

    [action] = result["actions"]
    assert action["status"] == "written"
    path = Path(action["config_path"])
    assert path.exists()

    config = json.loads(path.read_text(encoding="utf-8"))
    server = config["mcpServers"]["memograph"]
    assert server["command"] == "python"
    assert server["args"] == ["-m", "memograph.mcp.run_server"]
    assert server["env"]["MEMOGRAPH_VAULT"] == vault


def test_apply_mode_writes_cursor_config(tmp_path: Path):
    """Cursor uses the same ``mcpServers`` shape as Claude Desktop but
    lives at a different path. Without a Cursor branch in
    _configure_client the snippet would never get written there."""
    setup = _setup_with_fake_clients(tmp_path, detected=["Cursor"])
    vault = str(tmp_path / "vault")
    result = setup.quickstart_setup(vault, apply=True)

    [action] = result["actions"]
    assert action["status"] == "written"
    config = json.loads(Path(action["config_path"]).read_text(encoding="utf-8"))
    assert config["mcpServers"]["memograph"]["env"]["MEMOGRAPH_VAULT"] == vault


def test_apply_mode_writes_cline_config_with_mcp_servers_shape(tmp_path: Path):
    """Cline uses a nested ``mcp.servers`` shape, not Claude Desktop's
    flat ``mcpServers``. The wrong shape means Cline ignores the
    server silently — verify the right one ships."""
    setup = _setup_with_fake_clients(tmp_path, detected=["Cline CLI"])
    vault = str(tmp_path / "vault")
    result = setup.quickstart_setup(vault, apply=True)

    [action] = result["actions"]
    assert action["status"] == "written"
    config = json.loads(Path(action["config_path"]).read_text(encoding="utf-8"))
    assert "mcp" in config
    assert "servers" in config["mcp"]
    assert "memograph" in config["mcp"]["servers"]


# --------------------------------------------- merge preserves existing servers


def test_apply_mode_merges_with_existing_claude_config(tmp_path: Path):
    """The most important behavior under apply: a user with other MCP
    servers already configured doesn't lose them when MemoGraph wires
    itself in."""
    setup = _setup_with_fake_clients(tmp_path, detected=["Claude Desktop"])
    existing_path = tmp_path / "claude" / "claude_desktop_config.json"
    existing_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "another-server": {
                        "command": "node",
                        "args": ["other.js"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    setup.quickstart_setup(str(tmp_path / "vault"), apply=True)
    merged = json.loads(existing_path.read_text(encoding="utf-8"))

    assert (
        "another-server" in merged["mcpServers"]
    ), "merge clobbered the user's existing MCP server"
    assert "memograph" in merged["mcpServers"], "merge failed to add MemoGraph"


def test_apply_mode_idempotent(tmp_path: Path):
    """Running apply twice should produce the same config — no
    duplicate entries, no growing config file."""
    setup = _setup_with_fake_clients(tmp_path, detected=["Claude Desktop"])
    vault = str(tmp_path / "vault")
    setup.quickstart_setup(vault, apply=True)
    first = (tmp_path / "claude" / "claude_desktop_config.json").read_text(
        encoding="utf-8"
    )

    # Re-detect (the file now exists)
    setup = _setup_with_fake_clients(tmp_path, detected=["Claude Desktop"])
    # Restore the previous content; the fake setup overwrites the
    # parent dir mtime but not the file.
    (tmp_path / "claude" / "claude_desktop_config.json").write_text(
        first, encoding="utf-8"
    )
    setup.quickstart_setup(vault, apply=True)
    second = (tmp_path / "claude" / "claude_desktop_config.json").read_text(
        encoding="utf-8"
    )

    assert json.loads(first) == json.loads(second)


# --------------------------------------------- error handling


def test_apply_mode_records_failure_per_client(tmp_path: Path):
    """One client failing to write should not stop the others. The
    failure surfaces as an 'error' status with the message."""
    setup = _setup_with_fake_clients(tmp_path, detected=["Claude Desktop"])

    def boom(*_a, **_k):
        raise OSError("disk full")

    with patch.object(setup, "_configure_client", side_effect=boom):
        result = setup.quickstart_setup(str(tmp_path / "vault"), apply=True)

    [action] = result["actions"]
    assert action["status"] == "error"
    assert "disk full" in action["message"]


# --------------------------------------------- result shape contract


def test_result_dict_has_stable_keys(tmp_path: Path):
    """The CLI prints these — adding/removing top-level keys is a
    breaking change to the user-visible output."""
    setup = _setup_with_fake_clients(tmp_path, detected=[])
    result = setup.quickstart_setup(str(tmp_path / "vault"), apply=False)
    assert set(result.keys()) == {"detected", "actions", "not_detected"}
