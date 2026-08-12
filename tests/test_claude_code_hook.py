"""Smoke tests for the Claude Code Stop-hook script.

These tests exercise the transcript-parsing path without spinning up Claude
Code itself: we synthesize a JSONL transcript on disk and pipe the hook
payload to the script via subprocess.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "claude_code_stop_hook.py"
)


def _write_transcript(tmp_path: Path, exchanges: list[tuple[str, str]]) -> Path:
    """Build a Claude-Code-style JSONL transcript at tmp_path/transcript.jsonl.

    The real format wraps each message as ``{"type": "user"|"assistant",
    "message": {"role": ..., "content": [...]}}`` — we mirror that here so
    the parser exercises the production path.
    """
    transcript = tmp_path / "transcript.jsonl"
    lines: list[str] = []
    for user_msg, ai_msg in exchanges:
        lines.append(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": user_msg}],
                    },
                }
            )
        )
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": ai_msg}],
                    },
                }
            )
        )
    transcript.write_text("\n".join(lines), encoding="utf-8")
    return transcript


def _run_hook(
    transcript: Path, vault: Path, mode: str, log: Path
) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"transcript_path": str(transcript)})
    env = {
        **os.environ,
        "MEMOGRAPH_VAULT": str(vault),
        "MEMOGRAPH_CAPTURE_MODE": mode,
        "MEMOGRAPH_HOOK_LOG": str(log),
    }
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    v = tmp_path / "vault"
    v.mkdir()
    return v


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "hook.log"


def test_hook_saves_substantive_turn_in_mid_mode(
    tmp_path: Path, vault: Path, log_path: Path
) -> None:
    transcript = _write_transcript(
        tmp_path,
        [
            (
                "What is the architectural difference between VaultGraph and VaultIndexer?",
                "VaultGraph is the in-memory adjacency structure. VaultIndexer is the "
                "file watcher that re-parses changed files and updates the graph. "
                "Indexer owns lifecycle; graph owns shape.",
            )
        ],
    )

    result = _run_hook(transcript, vault, "mid", log_path)
    assert result.returncode == 0, result.stderr

    saved_files = list(vault.rglob("*.md"))
    assert len(saved_files) == 1, f"expected 1 saved memory, got {saved_files}"
    content = saved_files[0].read_text(encoding="utf-8")
    assert "Layer 0 (Claude Code Stop hook" in content
    assert "harness-hook" in content
    assert "VaultIndexer" in content


def test_hook_skips_in_low_mode(tmp_path: Path, vault: Path, log_path: Path) -> None:
    transcript = _write_transcript(
        tmp_path,
        [
            (
                "What is the architectural difference between VaultGraph and VaultIndexer?",
                "VaultGraph is the in-memory adjacency structure. VaultIndexer is the "
                "file watcher that re-parses changed files and updates the graph.",
            )
        ],
    )

    result = _run_hook(transcript, vault, "low", log_path)
    assert result.returncode == 0
    assert list(vault.rglob("*.md")) == []
    if log_path.exists():
        assert "filter_skip" in log_path.read_text(encoding="utf-8")


def test_hook_saves_short_reply_in_high_mode(
    tmp_path: Path, vault: Path, log_path: Path
) -> None:
    transcript = _write_transcript(
        tmp_path,
        [("Is the migration safe for the 50M-row table?", "Yes, with the backfill.")],
    )

    result = _run_hook(transcript, vault, "high", log_path)
    assert result.returncode == 0
    assert len(list(vault.rglob("*.md"))) == 1


def test_hook_handles_missing_transcript_gracefully(
    tmp_path: Path, vault: Path, log_path: Path
) -> None:
    fake = tmp_path / "does_not_exist.jsonl"
    result = _run_hook(fake, vault, "mid", log_path)
    # Must not error out — hooks are advisory.
    assert result.returncode == 0
    assert list(vault.rglob("*.md")) == []


def test_hook_handles_empty_vault_env_gracefully(tmp_path: Path) -> None:
    transcript = _write_transcript(
        tmp_path,
        [("A reasonably long user query goes here.", "And a reasonably long reply.")],
    )
    payload = json.dumps({"transcript_path": str(transcript)})
    env = {k: v for k, v in os.environ.items() if k != "MEMOGRAPH_VAULT"}
    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    # Should exit 0, just log and skip.
    assert result.returncode == 0
