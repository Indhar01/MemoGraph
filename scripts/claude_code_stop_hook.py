#!/usr/bin/env python3
"""Tier-A Claude Code ``Stop`` hook for deterministic conversation capture.

This is the **only** path to *truly* autonomous capture: Claude Code fires
the ``Stop`` hook at the end of every turn regardless of what the LLM does
or forgets. The hook receives the transcript path on stdin (JSON), and
this script reads the last user/assistant pair, applies the configured
capture mode filter, and saves to the vault directly via the kernel.

Install: point ``~/.claude/settings.json`` at this script —

  {
    "hooks": {
      "Stop": [
        {
          "matcher": "",
          "hooks": [
            {
              "type": "command",
              "command": "python C:/path/to/MemoGraph/scripts/claude_code_stop_hook.py"
            }
          ]
        }
      ]
    }
  }

Env vars:
  MEMOGRAPH_VAULT          (required) — vault directory
  MEMOGRAPH_CAPTURE_MODE   (optional) — low | mid | high (default: mid)
  MEMOGRAPH_HOOK_LOG       (optional) — file path for diagnostic logging
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _log(msg: str) -> None:
    """Append a diagnostic line if MEMOGRAPH_HOOK_LOG is set; otherwise no-op.

    Hooks run silently — printing to stdout/stderr can pollute the user's
    terminal or trigger Claude Code error UI, so we route diagnostics to a
    user-controlled file instead.
    """
    log_path = os.environ.get("MEMOGRAPH_HOOK_LOG")
    if not log_path:
        return
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n")
    except OSError:
        pass


def _read_hook_input() -> dict[str, Any]:
    """Read the Claude Code hook payload from stdin (JSON)."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        _log(f"hook_input_decode_error: {e}")
        return {}


def _extract_last_exchange(transcript_path: Path) -> tuple[str, str]:
    """Return ``(last_user_message, last_assistant_message)`` from a JSONL transcript.

    Claude Code transcripts are JSONL: one JSON object per line. Messages
    have a ``role`` field (``"user"`` or ``"assistant"``) and a ``content``
    field that is either a string or a list of content blocks (text /
    tool_use / tool_result). We concatenate text blocks and ignore tool
    blocks — they are not part of the human-readable exchange.

    Returns empty strings if either side cannot be located. Caller decides
    whether to skip the save in that case.
    """
    if not transcript_path.exists():
        _log(f"transcript_not_found: {transcript_path}")
        return "", ""

    last_user = ""
    last_assistant = ""

    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Claude Code wraps message records in {"type": "user"/"assistant", "message": {...}}.
                msg = entry.get("message") if isinstance(entry, dict) else None
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue

                text = _flatten_content(msg.get("content"))
                if not text:
                    continue

                if role == "user":
                    last_user = text
                else:
                    last_assistant = text
    except OSError as e:
        _log(f"transcript_read_error: {e}")
        return "", ""

    return last_user, last_assistant


def _flatten_content(content: Any) -> str:
    """Join text blocks; skip tool_use / tool_result / image blocks."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text", "")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n\n".join(parts)


def main() -> int:
    """Run the hook. Returns 0 on success, non-zero on transient error.

    A non-zero exit code does NOT block Claude Code — Stop hooks are
    advisory. We exit 0 in nearly all cases (including filter-skip) so the
    user never sees a hook error from a normal "this turn wasn't worth
    saving" outcome.
    """
    payload = _read_hook_input()
    transcript_path_str = payload.get("transcript_path") or os.environ.get(
        "CLAUDE_TRANSCRIPT_PATH"
    )
    if not transcript_path_str:
        _log("no_transcript_path_provided")
        return 0

    vault_path = os.environ.get("MEMOGRAPH_VAULT")
    if not vault_path:
        _log("MEMOGRAPH_VAULT not set; skipping save")
        return 0

    # Import lazily so the hook does not pay import cost when MEMOGRAPH_VAULT
    # is missing (the common "user hasn't configured it yet" case).
    try:
        from memograph.core.enums import MemoryType
        from memograph.core.kernel import MemoryKernel
        from memograph.mcp.capture_filter import should_save
    except ImportError as e:
        _log(f"memograph_import_failed: {e}")
        return 0

    user_msg, assistant_msg = _extract_last_exchange(Path(transcript_path_str))
    if not user_msg or not assistant_msg:
        _log(
            f"incomplete_exchange: user_len={len(user_msg)} ai_len={len(assistant_msg)}"
        )
        return 0

    mode = os.environ.get("MEMOGRAPH_CAPTURE_MODE", "mid")
    decision = should_save(user_query=user_msg, ai_response=assistant_msg, mode=mode)

    if not decision.save:
        _log(f"filter_skip: {decision.reason} (mode={mode})")
        return 0

    try:
        kernel = MemoryKernel(vault_path)
    except Exception as e:
        _log(f"kernel_init_failed: {e}")
        return 0

    timestamp = datetime.now(timezone.utc)
    title = f"Conversation: {user_msg[:50]}..."
    content = (
        "**Saved By:** Layer 0 (Claude Code Stop hook — deterministic)\n\n"
        f"**Capture Mode:** {mode}\n"
        f"**Decision:** {decision.reason} (salience={decision.salience:.2f})\n\n"
        f"**User Query**\n\n{user_msg}\n\n"
        f"**AI Response**\n\n{assistant_msg}\n\n"
        f"**Transcript:** `{transcript_path_str}`\n\n"
        f"**Timestamp:** {timestamp.isoformat()}\n"
    )

    tags = list(decision.tags) + ["harness-hook", "layer0-deterministic"]

    try:
        path = kernel.remember(
            title=title,
            content=content,
            memory_type=MemoryType.EPISODIC,
            tags=tags,
            salience=decision.salience,
        )
        _log(f"saved: {path} (mode={mode}, reason={decision.reason})")
    except Exception as e:
        _log(f"save_failed: {e}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
