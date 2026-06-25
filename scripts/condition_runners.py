"""Three condition runners for the MemoGraph paper evaluation.

Each runner takes the queries for a single session (and any prior-session history
needed for cross-session retrieval) and returns the model's response plus a per-call
log entry. Runners are pure-ish: they take an Anthropic client and a kernel (Cond C
only) so the orchestrator can wire up the right state.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from _paper_eval_helpers import GENERATOR_MODEL, Query

MAX_TOKENS = 1024
SYSTEM_BASE = (
    "You are a helpful AI assistant helping a software engineer with their projects. "
    "Answer their questions clearly and concretely."
)
SYSTEM_MEMOGRAPH = (
    SYSTEM_BASE
    + "\n\nYou have access to MemoGraph tools for persistent memory across sessions. "
    "**Before answering any non-greeting user message, you MUST first call "
    "`search_memories` at least once with a relevant query** — even if the question "
    "looks like it can be answered from general knowledge. The vault may contain prior "
    "user preferences, decisions, or context that change the right answer. Searching "
    "is cheap; missing context is expensive. Phrase the search query as the topic of "
    "the user's message (e.g. for 'set up a new developer's machine' search for "
    "'IDE editor preferences development tools'; for 'what database are we using' "
    "search for 'database choice'). If the first search returns nothing, try one more "
    "search with broader terms before answering.\n\n"
    "After establishing a new fact or preference (e.g. the user picks a library, IDE, "
    "or coding pattern), call `create_memory` to persist it. Use concise third-person "
    "titles like 'User chose FastAPI' or 'User uses VS Code'. Do NOT create a memory "
    "for a fact already returned by your earlier search; deduplication matters.\n\n"
    "When you write the `content` field of a new memory, link to related existing "
    "memories using [[Memory Title]] wikilink syntax. For example: 'The user adopted "
    "FastAPI as their web framework, building on [[User chose Python for backend]].' "
    "These wikilinks form the knowledge graph that makes retrieval more powerful, so "
    "use them whenever the new memory references a concept already captured in another "
    "memory you've created. Use the exact titles of prior memories returned by "
    "search_memories."
)

CONTEXT_PROMPT_TEMPLATE = (
    "Here are some excerpts from earlier sessions that may be relevant:\n\n"
    "{excerpts}\n\n"
    "Now answer the user's next message using this context if helpful."
)


@dataclass
class Exchange:
    """One (query, response) turn from a previously-completed session."""

    session_id: int
    query_idx: int
    query_text: str
    response_text: str


@dataclass
class CallLog:
    query_idx: int
    session_id: int
    condition: str
    response_text: str
    api_calls: int = 1
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    in_context_excerpts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    elapsed_ms: int = 0


def _strip_text(content_blocks: list[Any]) -> str:
    parts = []
    for b in content_blocks:
        if hasattr(b, "type") and b.type == "text":
            parts.append(b.text)
        elif isinstance(b, dict) and b.get("type") == "text":
            parts.append(b["text"])
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# Condition A: Baseline (no cross-session memory; within-session conversation only).
# ---------------------------------------------------------------------------


def run_baseline_session(client: Any, queries: list[Query]) -> list[CallLog]:
    """Run all queries of one session in a single fresh conversation, no system memory."""
    logs: list[CallLog] = []
    messages: list[dict[str, Any]] = []
    for q in queries:
        messages.append({"role": "user", "content": q.text})
        t0 = time.time()
        try:
            resp = client.messages.create(
                model=GENERATOR_MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_BASE,
                messages=messages,
            )
            text = _strip_text(resp.content)
            logs.append(
                CallLog(
                    query_idx=q.idx,
                    session_id=q.session_id,
                    condition="baseline",
                    response_text=text,
                    elapsed_ms=int((time.time() - t0) * 1000),
                )
            )
            messages.append({"role": "assistant", "content": text})
        except Exception as exc:  # noqa: BLE001
            logs.append(
                CallLog(
                    query_idx=q.idx,
                    session_id=q.session_id,
                    condition="baseline",
                    response_text="",
                    error=f"{type(exc).__name__}: {exc}",
                    elapsed_ms=int((time.time() - t0) * 1000),
                )
            )
            messages.append({"role": "assistant", "content": ""})
    return logs


# ---------------------------------------------------------------------------
# Condition B: In-context memory with TF-IDF curator over prior-session exchanges.
# ---------------------------------------------------------------------------


def _curate_excerpts(
    query_text: str, history: list[Exchange], k: int = 4
) -> list[Exchange]:
    """Return the top-k most relevant prior exchanges by TF-IDF cosine similarity."""
    if not history:
        return []
    docs = [f"Q: {h.query_text}\nA: {h.response_text}" for h in history]
    try:
        vec = TfidfVectorizer(stop_words="english", lowercase=True, max_features=4096)
        matrix = vec.fit_transform(docs + [query_text])
        sims = cosine_similarity(matrix[-1], matrix[:-1]).flatten()
    except ValueError:
        return history[-k:]
    order = sims.argsort()[::-1][:k]
    return [history[i] for i in order if sims[i] > 0.05]


def _format_excerpts(excerpts: list[Exchange]) -> str:
    chunks = []
    for ex in excerpts:
        chunks.append(
            f"--- Session {ex.session_id}, Query {ex.query_idx} ---\n"
            f"User: {ex.query_text}\n"
            f"Assistant: {ex.response_text[:600].rstrip()}"
        )
    return "\n\n".join(chunks)


def run_in_context_session(
    client: Any, queries: list[Query], history: list[Exchange], k: int = 4
) -> list[CallLog]:
    """Per-query TF-IDF curation prepended as a system note. Within-session messages persist."""
    logs: list[CallLog] = []
    messages: list[dict[str, Any]] = []
    # We re-prepend a fresh "context block" each query as a system-rolled user note,
    # since Anthropic Messages API has only one `system` field per call.
    for q in queries:
        excerpts = _curate_excerpts(q.text, history, k=k) if history else []
        if excerpts:
            ctx_block = CONTEXT_PROMPT_TEMPLATE.format(
                excerpts=_format_excerpts(excerpts)
            )
            user_content = f"{ctx_block}\n\nUser: {q.text}"
        else:
            user_content = q.text

        messages.append({"role": "user", "content": user_content})
        t0 = time.time()
        try:
            resp = client.messages.create(
                model=GENERATOR_MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_BASE,
                messages=messages,
            )
            text = _strip_text(resp.content)
            logs.append(
                CallLog(
                    query_idx=q.idx,
                    session_id=q.session_id,
                    condition="in_context",
                    response_text=text,
                    in_context_excerpts=[
                        {
                            "session_id": ex.session_id,
                            "query_idx": ex.query_idx,
                            "query_text": ex.query_text,
                            "response_excerpt": ex.response_text[:600],
                        }
                        for ex in excerpts
                    ],
                    elapsed_ms=int((time.time() - t0) * 1000),
                )
            )
            messages.append({"role": "assistant", "content": text})
        except Exception as exc:  # noqa: BLE001
            logs.append(
                CallLog(
                    query_idx=q.idx,
                    session_id=q.session_id,
                    condition="in_context",
                    response_text="",
                    error=f"{type(exc).__name__}: {exc}",
                    elapsed_ms=int((time.time() - t0) * 1000),
                )
            )
            messages.append({"role": "assistant", "content": ""})
    return logs


# ---------------------------------------------------------------------------
# Condition C: MemoGraph tools wired to a real MemoryKernel.
# ---------------------------------------------------------------------------


MEMOGRAPH_TOOLS = [
    {
        "name": "search_memories",
        "description": (
            "Search the persistent memory vault for relevant memories. Use this BEFORE "
            "answering any question that depends on past decisions, preferences, or "
            "established facts. Returns up to top_k memory titles + snippets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search query."},
                "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_memory",
        "description": (
            "Persist a new memory in the vault. Call this when the user establishes a "
            "new preference, decision, or fact (e.g. 'I'll use FastAPI'). Use a concise "
            "third-person title like 'User chose FastAPI'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "memory_type": {
                    "type": "string",
                    "enum": ["episodic", "semantic", "procedural", "fact"],
                    "default": "fact",
                },
            },
            "required": ["title", "content"],
        },
    },
]


def _dispatch_memograph_tool(
    kernel: Any, name: str, args: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Execute one tool call against the live kernel. Returns (text_result, log_entry).

    Uses the native kernel.search() path. As of v0.2.0 the kernel's HybridRetriever
    has a real BM25 ranker for the no-embedding case (memograph/core/retriever.py),
    so we no longer need the TF-IDF wrapper that was used in earlier paper revisions.
    """
    from memograph.core.enums import MemoryType
    from memograph.core.kernel import SearchOptions

    if name == "search_memories":
        query = args.get("query", "")
        top_k = int(args.get("top_k", 5))
        opts = SearchOptions(strategy="keyword", max_results=top_k)
        try:
            # MemoGraph kernel.remember() writes the markdown file but does NOT update
            # the in-memory graph; only ingest() reads files into the graph. Without
            # an explicit ingest before each search, memories created mid-run are
            # invisible to retrieval. This is a known MemoGraph issue we work around
            # in the harness; addressing it inside kernel.remember() is listed as
            # follow-up work in §6 of the paper.
            kernel.ingest()
            nodes = kernel.search(query, options=opts)
        except Exception as exc:  # noqa: BLE001
            return f"search error: {exc}", {
                "tool": name,
                "args": args,
                "error": str(exc),
            }
        if not nodes:
            return "(no memories matched)", {"tool": name, "args": args, "results": []}
        result_payload = []
        text_parts = []
        for n in nodes[:top_k]:
            snippet = (n.content or "").strip().replace("\n", " ")[:200]
            result_payload.append({"title": n.title, "snippet": snippet})
            text_parts.append(f"- {n.title}: {snippet}")
        return "\n".join(text_parts), {
            "tool": name,
            "args": args,
            "results": result_payload,
        }

    if name == "create_memory":
        title = args.get("title", "").strip()
        content = args.get("content", "").strip()
        if not title or not content:
            return "error: title and content are required", {
                "tool": name,
                "args": args,
                "error": "empty",
            }
        mt_str = args.get("memory_type", "fact")
        try:
            mt = MemoryType(mt_str)
        except ValueError:
            mt = MemoryType.FACT
        try:
            path = kernel.remember(title=title, content=content, memory_type=mt)
        except Exception as exc:  # noqa: BLE001
            return f"create error: {exc}", {
                "tool": name,
                "args": args,
                "error": str(exc),
            }
        return f"saved: {title}", {"tool": name, "args": args, "saved_path": str(path)}

    return f"error: unknown tool {name}", {
        "tool": name,
        "args": args,
        "error": "unknown_tool",
    }


def run_memograph_session(
    client: Any, queries: list[Query], kernel: Any
) -> list[CallLog]:
    """One session, persistent kernel across the whole condition. Tool-use loop per query."""
    logs: list[CallLog] = []
    messages: list[dict[str, Any]] = []
    for q in queries:
        messages.append({"role": "user", "content": q.text})
        api_calls = 0
        tool_log: list[dict[str, Any]] = []
        final_text = ""
        error: str | None = None
        t0 = time.time()
        try:
            while True:
                api_calls += 1
                resp = client.messages.create(
                    model=GENERATOR_MODEL,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_MEMOGRAPH,
                    tools=MEMOGRAPH_TOOLS,
                    messages=messages,
                )
                stop = resp.stop_reason
                blocks_for_assistant: list[dict[str, Any]] = []
                tool_results: list[dict[str, Any]] = []
                for block in resp.content:
                    btype = getattr(block, "type", None)
                    if btype == "text":
                        blocks_for_assistant.append(
                            {"type": "text", "text": block.text}
                        )
                    elif btype == "tool_use":
                        blocks_for_assistant.append(
                            {
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            }
                        )
                        tool_text, log_entry = _dispatch_memograph_tool(
                            kernel, block.name, block.input
                        )
                        tool_log.append(log_entry)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": tool_text,
                            }
                        )
                messages.append({"role": "assistant", "content": blocks_for_assistant})

                if stop == "tool_use" and tool_results:
                    messages.append({"role": "user", "content": tool_results})
                    if api_calls >= 6:
                        # Safety stop: too many tool roundtrips on one query.
                        final_text = (
                            _strip_text(blocks_for_assistant) or "(tool loop cap)"
                        )
                        error = "tool_loop_cap"
                        break
                    continue
                final_text = _strip_text(blocks_for_assistant)
                break
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

        logs.append(
            CallLog(
                query_idx=q.idx,
                session_id=q.session_id,
                condition="memograph",
                response_text=final_text,
                api_calls=api_calls,
                tool_calls=tool_log,
                error=error,
                elapsed_ms=int((time.time() - t0) * 1000),
            )
        )
        # If the last message in messages is an assistant with only tool_use and we
        # didn't get a final text turn, we still recorded what we had. The within-session
        # history should reflect that final assistant turn.
    return logs


# ---------------------------------------------------------------------------
# Logging helpers.
# ---------------------------------------------------------------------------


def write_session_log(path: Path, logs: list[CallLog]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for cl in logs:
            f.write(json.dumps(cl.__dict__, ensure_ascii=False) + "\n")
