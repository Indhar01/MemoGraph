import argparse
import itertools
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib import error, request

# Fix Windows console encoding for Unicode characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        # Fallback for older Python versions or if reconfigure fails
        import codecs

        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

from .core.assistant import build_answer_prompt, retrieve_cited_context, run_answer
from .core.enums import MemoryType
from .core.kernel import MemoryKernel
from .cli_helpers import (
    run_update_command,
    run_delete_command,
    run_list_command,
    run_search_command,
)
from .cli_batch_helpers import (
    run_batch_create_command,
    run_batch_update_command,
    run_batch_delete_command,
)
from .cli_infrastructure_helpers import (
    run_export_command,
    run_import_backup_command,
    run_backup_command,
    run_config_command,
    run_stats_command,
)


class Spinner:
    """Simple terminal spinner for showing progress during LLM requests."""

    def __init__(self, message: str = "Thinking"):
        self.message = message
        self.spinner_chars = itertools.cycle(
            ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        )
        self.stop_spinner = False
        self.spinner_thread: threading.Thread | None = None

    def _spin(self):
        """Run the spinner animation in a separate thread."""
        while not self.stop_spinner:
            sys.stdout.write(f"\r{next(self.spinner_chars)} {self.message}...")
            sys.stdout.flush()
            time.sleep(0.1)
        # Clear the spinner line
        sys.stdout.write("\r" + " " * (len(self.message) + 10) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        """Start the spinner when entering context."""
        self.stop_spinner = False
        self.spinner_thread = threading.Thread(target=self._spin, daemon=True)
        self.spinner_thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop the spinner when exiting context."""
        self.stop_spinner = True
        if self.spinner_thread:
            self.spinner_thread.join(timeout=0.5)


def _generate_conversation_title(
    query: str,
    answer: str,
    provider: str,
    model: str | None,
    base_url: str | None,
) -> str:
    """
    Generate a concise title for the conversation using LLM.

    Falls back to truncated query if LLM fails.
    """
    try:
        summarization_prompt = (
            f"Generate a concise 5-7 word title for this conversation. "
            f"Only respond with the title, nothing else.\n\n"
            f"Question: {query}\n"
            f"Answer: {answer[:200]}..."
        )

        # Use the same provider/model but with shorter response
        title = run_answer(
            provider=provider,
            prompt=summarization_prompt,
            model=model,
            max_tokens=50,
            temperature=0.3,
            base_url=base_url,
        )

        # Clean up the title
        title = title.strip().strip('"').strip("'")

        # Ensure it's not too long
        if len(title) > 80:
            title = title[:77] + "..."

        return title
    except Exception:
        # Fallback to truncated query
        return query[:50] + ("..." if len(query) > 50 else "")


def _run_ask(kernel: MemoryKernel, args) -> None:
    if args.provider == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Set ANTHROPIC_API_KEY or use --provider ollama.")

    # Track conversation for combined mode
    conversation_history = []
    conversation_started = None

    def ask_once(query_text: str) -> None:
        nonlocal conversation_started

        if conversation_started is None:
            conversation_started = datetime.now()

        context, sources = retrieve_cited_context(
            kernel=kernel,
            query=query_text,
            tags=args.tags,
            depth=args.depth,
            top_k=args.top_k,
            token_limit=args.token_limit,
        )
        prompt = build_answer_prompt(context=context, query=query_text)

        try:
            # Determine if we should stream (only for Ollama)
            should_stream = (
                args.provider == "ollama" and args.stream and not args.no_spinner
            )

            if should_stream:
                # Streaming mode: show spinner for connection, then stream tokens
                with Spinner("Connecting to Ollama"):
                    # Brief pause to show spinner
                    time.sleep(0.5)

                # Clear spinner and start streaming
                sys.stdout.write("\r" + " " * 50 + "\r")
                sys.stdout.flush()

                # Define callback to print tokens as they arrive
                def print_token(token: str):
                    sys.stdout.write(token)
                    sys.stdout.flush()

                answer = run_answer(
                    provider=args.provider,
                    prompt=prompt,
                    model=args.model,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    base_url=args.base_url,
                    timeout=args.ollama_timeout,
                    stream=True,
                    stream_callback=print_token,
                )
                print()  # New line after streaming

            elif not args.no_spinner:
                # Non-streaming with spinner
                with Spinner("Thinking"):
                    answer = run_answer(
                        provider=args.provider,
                        prompt=prompt,
                        model=args.model,
                        max_tokens=args.max_tokens,
                        temperature=args.temperature,
                        base_url=args.base_url,
                        timeout=getattr(args, "ollama_timeout", 600),
                        stream=False,
                    )
            else:
                # No spinner, no streaming
                answer = run_answer(
                    provider=args.provider,
                    prompt=prompt,
                    model=args.model,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    base_url=args.base_url,
                    timeout=getattr(args, "ollama_timeout", 600),
                    stream=False,
                )
        except Exception as exc:
            print(f"\nLLM error: {exc}")
            return

        if args.show_context:
            print("=== Retrieved Context ===")
            print(context)
            print()

        # Only print answer if we didn't already stream it
        if should_stream:
            pass  # Answer was already streamed to stdout
        else:
            print("=== Answer ===")
            print(answer)

        if sources and not args.no_citations:
            print("\n=== Sources ===")
            for src in sources:
                tags_str = ", ".join(src.tags) if src.tags else "-"
                print(
                    f"[{src.source_id}] {src.title} (id={src.node_id}, type={src.memory_type}, tags={tags_str})"
                )

        # Save conversations if enabled
        if args.save_chat and args.chat:
            # Store in history for combined mode
            conversation_history.append(
                {
                    "question": query_text,
                    "answer": answer,
                    "sources": sources,
                    "timestamp": datetime.now(),
                }
            )

            # Save based on mode
            if args.save_mode == "separate":
                _save_conversation_separate(
                    kernel=kernel,
                    query=query_text,
                    answer=answer,
                    sources=sources,
                    tags=args.tags,
                    provider=args.provider,
                    model=args.model,
                    base_url=args.base_url,
                    auto_title=args.auto_title,
                )
            elif args.save_mode == "combined":
                # Don't save yet, wait for chat end
                pass
            elif args.save_mode == "both":
                # Save separately immediately
                _save_conversation_separate(
                    kernel=kernel,
                    query=query_text,
                    answer=answer,
                    sources=sources,
                    tags=args.tags,
                    provider=args.provider,
                    model=args.model,
                    base_url=args.base_url,
                    auto_title=args.auto_title,
                )

    if args.chat:
        print("Interactive chat mode. Type 'exit' or 'quit' to stop.")
        while True:
            query_text = input("you> ").strip()
            if not query_text:
                continue
            if query_text.lower() in {"exit", "quit"}:
                print("bye")

                # Save combined conversation if needed
                if (
                    args.save_chat
                    and conversation_history
                    and args.save_mode in ["combined", "both"]
                ):
                    _save_conversation_combined(
                        kernel=kernel,
                        conversation_history=conversation_history,
                        tags=args.tags,
                        provider=args.provider,
                        model=args.model,
                        base_url=args.base_url,
                        auto_title=args.auto_title,
                    )
                break
            ask_once(query_text)
            print()
        return

    if not args.query:
        raise RuntimeError("Provide --query for non-chat mode.")
    ask_once(args.query)


def _save_conversation_separate(
    kernel: MemoryKernel,
    query: str,
    answer: str,
    sources,
    tags: list[str] | None,
    provider: str,
    model: str | None,
    base_url: str | None,
    auto_title: bool,
) -> None:
    """Save question and answer as separate memory entries."""
    try:
        # Generate title if auto_title enabled
        if auto_title:
            title = _generate_conversation_title(
                query, answer, provider, model, base_url
            )
        else:
            title = query[:50] + ("..." if len(query) > 50 else "")

        # Format sources for content
        sources_text = ""
        if sources:
            sources_text = "\n\n**Sources:**\n" + "\n".join(
                f"- [{src.source_id}] {src.title}" for src in sources
            )

        # Save question
        kernel.remember(
            title=f"Q: {title}",
            content=query,
            memory_type=MemoryType.EPISODIC,
            tags=["chat", "question"] + (tags or []),
            salience=0.5,
        )

        # Save answer
        kernel.remember(
            title=f"A: {title}",
            content=f"{answer}{sources_text}",
            memory_type=MemoryType.EPISODIC,
            tags=["chat", "answer"] + (tags or []),
            salience=0.6,
        )

    except Exception as e:
        print(f"\nWarning: Failed to save conversation: {e}")


def _save_conversation_combined(
    kernel: MemoryKernel,
    conversation_history: list,
    tags: list[str] | None,
    provider: str,
    model: str | None,
    base_url: str | None,
    auto_title: bool,
) -> None:
    """Save entire conversation thread as a single memory entry."""
    try:
        if not conversation_history:
            return

        # Generate title based on first exchange
        first_q = conversation_history[0]["question"]
        first_a = conversation_history[0]["answer"]

        if auto_title:
            title = _generate_conversation_title(
                first_q, first_a, provider, model, base_url
            )
        else:
            title = first_q[:50] + ("..." if len(first_q) > 50 else "")

        # Build conversation content
        content_parts = []
        for idx, exchange in enumerate(conversation_history, 1):
            content_parts.append(f"**Turn {idx}**")
            content_parts.append(f"You: {exchange['question']}")
            content_parts.append(f"Assistant: {exchange['answer']}")

            if exchange["sources"]:
                sources_text = "Sources: " + ", ".join(
                    f"[{src.source_id}] {src.title}" for src in exchange["sources"]
                )
                content_parts.append(sources_text)

            content_parts.append("")  # Empty line between exchanges

        conversation_content = "\n".join(content_parts)

        # Save combined conversation
        kernel.remember(
            title=f"Chat: {title}",
            content=conversation_content,
            memory_type=MemoryType.EPISODIC,
            tags=["chat", "conversation", "thread"] + (tags or []),
            salience=0.7,
            meta={
                "exchange_count": len(conversation_history),
                "started": conversation_history[0]["timestamp"].isoformat(),
                "ended": conversation_history[-1]["timestamp"].isoformat(),
            },
        )

        print(
            f"\n✓ Saved conversation with {len(conversation_history)} exchanges to vault"
        )

    except Exception as e:
        print(f"\nWarning: Failed to save combined conversation: {e}")


def _run_doctor(args) -> None:
    print("=== MemoGraph Doctor ===")
    vault = MemoryKernel(args.vault)
    stats = vault.ingest(force=False)
    print(f"vault: {vault.vault_path}")
    print(
        f"indexed: {stats['indexed']} | skipped: {stats['skipped']} | total: {stats['total']}"
    )

    anth_key = os.environ.get("ANTHROPIC_API_KEY")
    print(f"claude_api_key: {'present' if anth_key else 'missing'}")

    ollama_url = (
        args.ollama_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434"
    ).rstrip("/")
    tags_url = f"{ollama_url}/api/tags"
    try:
        req = request.Request(tags_url, method="GET")
        with request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        models = payload.get("models", [])
        print(f"ollama: reachable ({len(models)} models) @ {ollama_url}")
    except error.URLError as exc:
        print(f"ollama: unreachable @ {ollama_url} ({exc})")


def main():
    from . import __version__

    parser = argparse.ArgumentParser(
        description="MemoGraph CLI - AI-Powered Knowledge Management"
    )
    parser.add_argument(
        "--version", action="version", version=f"memograph {__version__}"
    )
    parser.add_argument("--vault", default="~/my-vault", help="Path to memory vault")

    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Index all markdown memories")
    ingest_parser.add_argument("--force", action="store_true", help="Reindex all files")

    remember_parser = subparsers.add_parser("remember", help="Create a new memory note")
    remember_parser.add_argument(
        "--title", help="Memory title (will prompt if not provided)"
    )
    remember_parser.add_argument(
        "--content", help="Memory content (will prompt if not provided)"
    )
    remember_parser.add_argument(
        "--type",
        choices=[member.value for member in MemoryType],
        default=MemoryType.FACT.value,
        help="Memory type",
    )
    remember_parser.add_argument(
        "--tags",
        nargs="*",
        default=[],
        help="Tags (with or without # prefix)",
    )
    remember_parser.add_argument(
        "--salience",
        type=float,
        default=0.5,
        help="Memory salience/importance (0.0 to 1.0, default: 0.5)",
    )

    context_parser = subparsers.add_parser(
        "context", help="Build context window for a query"
    )
    context_parser.add_argument("--query", required=True, help="Query text")
    context_parser.add_argument(
        "--tags", nargs="*", default=[], help="Optional tag filter"
    )
    context_parser.add_argument(
        "--depth", type=int, default=2, help="Graph traversal depth"
    )
    context_parser.add_argument(
        "--top-k", type=int, default=8, help="Max memories to return"
    )
    context_parser.add_argument(
        "--token-limit", type=int, default=2048, help="Compression token limit"
    )

    ask_parser = subparsers.add_parser(
        "ask", help="Ask an LLM with retrieved memory context"
    )
    ask_parser.add_argument(
        "--provider",
        choices=["claude", "ollama"],
        default="ollama",
        help="LLM provider",
    )
    ask_parser.add_argument("--query", help="Question text (omit in --chat mode)")
    ask_parser.add_argument("--chat", action="store_true", help="Interactive chat mode")
    ask_parser.add_argument("--tags", nargs="*", default=[], help="Optional tag filter")
    ask_parser.add_argument(
        "--depth", type=int, default=2, help="Graph traversal depth"
    )
    ask_parser.add_argument(
        "--top-k", type=int, default=8, help="Max memories to retrieve"
    )
    ask_parser.add_argument(
        "--token-limit", type=int, default=2048, help="Context compression budget"
    )
    ask_parser.add_argument("--model", default=None, help="Provider-specific model")
    ask_parser.add_argument(
        "--base-url", default=None, help="Provider base URL override"
    )
    ask_parser.add_argument(
        "--max-tokens", type=int, default=1024, help="Max generated tokens"
    )
    ask_parser.add_argument(
        "--temperature", type=float, default=0.1, help="Sampling temperature"
    )
    ask_parser.add_argument(
        "--show-context", action="store_true", help="Print context sent to LLM"
    )
    ask_parser.add_argument(
        "--no-citations", action="store_true", help="Hide source list output"
    )
    ask_parser.add_argument(
        "--save-chat",
        action="store_true",
        default=True,
        help="Save chat conversations to vault (default: True)",
    )
    ask_parser.add_argument(
        "--no-save-chat",
        dest="save_chat",
        action="store_false",
        help="Disable saving chat conversations",
    )
    ask_parser.add_argument(
        "--save-mode",
        choices=["separate", "combined", "both"],
        default="both",
        help="How to save conversations: 'separate' (Q&A pairs), 'combined' (full thread), 'both' (default: both)",
    )
    ask_parser.add_argument(
        "--auto-title",
        action="store_true",
        default=True,
        help="Auto-generate conversation titles using LLM (default: True)",
    )
    ask_parser.add_argument(
        "--no-auto-title",
        dest="auto_title",
        action="store_false",
        help="Disable automatic title generation",
    )
    ask_parser.add_argument(
        "--no-spinner",
        action="store_true",
        help="Disable spinner animation during LLM requests",
    )
    ask_parser.add_argument(
        "--ollama-timeout",
        type=int,
        default=600,
        help="Ollama request timeout in seconds (default: 600, env: OLLAMA_TIMEOUT)",
    )
    ask_parser.add_argument(
        "--stream",
        action="store_true",
        default=True,
        help="Enable token streaming for Ollama (default: True)",
    )
    ask_parser.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        help="Disable token streaming, wait for complete response",
    )

    import_parser = subparsers.add_parser(
        "import", help="Import documents (TXT, PDF, DOCX) and convert to markdown"
    )
    import_parser.add_argument("path", help="File or folder to import")
    import_parser.add_argument(
        "--type",
        choices=[member.value for member in MemoryType],
        default=MemoryType.EPISODIC.value,
        help="Memory type for imported documents (default: episodic)",
    )
    import_parser.add_argument(
        "--salience",
        type=float,
        default=0.7,
        help="Importance score 0.0-1.0 (default: 0.7)",
    )
    import_parser.add_argument(
        "--tags",
        nargs="*",
        default=[],
        help="Tags to add to imported documents",
    )
    import_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files in vault",
    )
    import_parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively import from subdirectories",
    )
    import_parser.add_argument(
        "--auto-ingest",
        action="store_true",
        help="Automatically run ingest after import",
    )
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview files that would be imported without actually importing",
    )

    quickstart_parser = subparsers.add_parser(
        "quickstart",
        help=(
            "Materialise a sample vault, ingest it, run sample queries — "
            "the fastest way to see what MemoGraph does"
        ),
    )
    quickstart_parser.add_argument(
        "--target",
        default="~/memograph-quickstart",
        help=("Where to create the sample vault " "(default: ~/memograph-quickstart)"),
    )
    quickstart_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace the target directory if it already has files in it",
    )
    quickstart_parser.add_argument(
        "--mcp",
        action="store_true",
        help=(
            "After the demo runs, detect installed MCP clients (Claude "
            "Desktop, Cursor, Cline) and preview the config snippet that "
            "would wire the quickstart vault into each. Read-only — pass "
            "--mcp-apply to actually write the configs."
        ),
    )
    quickstart_parser.add_argument(
        "--mcp-apply",
        action="store_true",
        help=(
            "Write MCP server configs to detected client config files. "
            "Implies --mcp. Restart your AI client after."
        ),
    )

    doctor_parser = subparsers.add_parser(
        "doctor", help="Run environment and integration diagnostics"
    )
    doctor_parser.add_argument(
        "--ollama-url", default=None, help="Override Ollama base URL"
    )

    setup_mcp_parser = subparsers.add_parser(
        "setup-mcp", help="Interactive MCP setup wizard"
    )
    setup_mcp_parser.add_argument(
        "--vault-path", default=None, help="Default vault path for setup (optional)"
    )

    subparsers.add_parser("verify-mcp", help="Verify MCP setup and configuration")

    suggest_tags_parser = subparsers.add_parser(
        "suggest-tags", help="Suggest tags for a note file using AI analysis"
    )
    suggest_tags_parser.add_argument(
        "file_path", help="Path to the note file to analyze"
    )
    suggest_tags_parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.3,
        help="Minimum confidence score (0.0-1.0, default: 0.3)",
    )
    suggest_tags_parser.add_argument(
        "--max-suggestions",
        type=int,
        default=5,
        help="Maximum number of suggestions (default: 5)",
    )
    suggest_tags_parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply suggestions by adding them to the file",
    )

    suggest_links_parser = subparsers.add_parser(
        "suggest-links", help="Suggest wikilinks for a note file using AI analysis"
    )
    suggest_links_parser.add_argument(
        "file_path", help="Path to the note file to analyze"
    )
    suggest_links_parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.4,
        help="Minimum confidence score (0.0-1.0, default: 0.4)",
    )
    suggest_links_parser.add_argument(
        "--max-suggestions",
        type=int,
        default=10,
        help="Maximum number of suggestions (default: 10)",
    )
    suggest_links_parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply suggestions by adding wikilinks to the file",
    )
    suggest_links_parser.add_argument(
        "--show-bidirectional",
        action="store_true",
        help="Show which suggestions are bidirectional (both should link)",
    )

    detect_gaps_parser = subparsers.add_parser(
        "detect-gaps", help="Detect knowledge gaps in the vault"
    )

    update_parser = subparsers.add_parser(
        "update", help="Update existing memory/memories"
    )

    # Target selection (mutually exclusive)
    target_group = update_parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "memory_id", nargs="?", help="Memory ID to update (e.g., abc-123)"
    )
    target_group.add_argument(
        "--filter", action="store_true", help="Update multiple memories using filters"
    )

    # Update fields
    update_parser.add_argument("--title", help="New title")
    update_parser.add_argument("--content", help="New content")
    update_parser.add_argument(
        "--type",
        choices=[member.value for member in MemoryType],
        help="New memory type",
    )
    update_parser.add_argument("--salience", type=float, help="New salience (0.0-1.0)")
    update_parser.add_argument("--add-tags", nargs="*", help="Tags to add")
    update_parser.add_argument("--remove-tags", nargs="*", help="Tags to remove")
    update_parser.add_argument("--set-tags", nargs="*", help="Replace all tags")

    # Filter options (when --filter is used)
    update_parser.add_argument("--filter-tags", nargs="*", help="Filter by tags")
    update_parser.add_argument(
        "--filter-type",
        choices=[member.value for member in MemoryType],
        help="Filter by memory type",
    )
    update_parser.add_argument(
        "--filter-min-salience", type=float, help="Filter by minimum salience"
    )
    update_parser.add_argument(
        "--filter-max-salience", type=float, help="Filter by maximum salience"
    )

    # Safety options
    update_parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without applying"
    )
    update_parser.add_argument(
        "--confirm", action="store_true", help="Skip confirmation prompt"
    )

    delete_parser = subparsers.add_parser(
        "delete", help="Delete existing memory/memories"
    )

    # Target selection (mutually exclusive)
    delete_target_group = delete_parser.add_mutually_exclusive_group(required=True)
    delete_target_group.add_argument(
        "memory_id", nargs="?", help="Memory ID to delete (e.g., abc-123)"
    )
    delete_target_group.add_argument(
        "--filter", action="store_true", help="Delete multiple memories using filters"
    )

    # Filter options (when --filter is used)
    delete_parser.add_argument("--filter-tags", nargs="*", help="Filter by tags")
    delete_parser.add_argument(
        "--filter-type",
        choices=[member.value for member in MemoryType],
        help="Filter by memory type",
    )
    delete_parser.add_argument(
        "--filter-min-salience", type=float, help="Filter by minimum salience"
    )
    delete_parser.add_argument(
        "--filter-max-salience", type=float, help="Filter by maximum salience"
    )

    # Safety options
    delete_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview deletions without removing files",
    )
    delete_parser.add_argument(
        "--confirm", action="store_true", help="Skip confirmation prompt"
    )

    list_parser = subparsers.add_parser(
        "list", help="List memories with filtering and formatting options"
    )

    # Filter options
    list_parser.add_argument(
        "--tags",
        nargs="*",
        default=[],
        help="Filter by tags (space-separated, e.g., --tags python docker)",
    )
    list_parser.add_argument(
        "--type",
        choices=[member.value for member in MemoryType],
        help="Filter by memory type",
    )
    list_parser.add_argument(
        "--min-salience", type=float, help="Filter by minimum salience"
    )
    list_parser.add_argument(
        "--max-salience", type=float, help="Filter by maximum salience"
    )

    # Sorting options
    list_parser.add_argument(
        "--sort-by",
        choices=["title", "salience", "type", "created", "modified"],
        help="Sort by field",
    )
    list_parser.add_argument(
        "--reverse", action="store_true", help="Sort in descending order"
    )

    # Pagination options
    list_parser.add_argument("--limit", type=int, help="Maximum number of results")
    list_parser.add_argument("--offset", type=int, help="Number of results to skip")

    # Output format
    list_parser.add_argument(
        "--format",
        choices=["table", "json", "csv", "ids"],
        default="table",
        help="Output format (default: table)",
    )

    search_parser = subparsers.add_parser(
        "search", help="Search memories using various strategies"
    )

    # Query parameter
    search_parser.add_argument("query", help="Search query string")

    # Search strategy
    search_parser.add_argument(
        "--strategy",
        choices=["keyword", "semantic", "hybrid", "graph"],
        default="hybrid",
        help="Search strategy (default: hybrid)",
    )

    # Result options
    search_parser.add_argument(
        "--limit", type=int, default=10, help="Maximum number of results (default: 10)"
    )
    search_parser.add_argument(
        "--min-salience", type=float, help="Minimum salience threshold"
    )
    search_parser.add_argument(
        "--depth", type=int, default=2, help="Graph traversal depth (default: 2)"
    )

    # Scoring options
    search_parser.add_argument(
        "--boost-recent", action="store_true", help="Apply recency boost to scoring"
    )
    search_parser.add_argument(
        "--keyword-weight", type=float, help="Weight for keyword scoring (0.0-1.0)"
    )
    search_parser.add_argument(
        "--semantic-weight", type=float, help="Weight for semantic scoring (0.0-1.0)"
    )

    # Output format
    search_parser.add_argument(
        "--format",
        choices=["table", "json", "detailed"],
        default="table",
        help="Output format (default: table)",
    )
    search_parser.add_argument(
        "--show-scores", action="store_true", help="Show relevance scores in output"
    )
    search_parser.add_argument(
        "--show-snippets", action="store_true", help="Show content snippets in output"
    )

    detect_gaps_parser.add_argument(
        "--min-severity",
        type=float,
        default=0.3,
        help="Minimum severity threshold (0.0-1.0, default: 0.3)",
    )
    detect_gaps_parser.add_argument(
        "--max-gaps",
        type=int,
        default=20,
        help="Maximum number of gaps to return (default: 20)",
    )
    detect_gaps_parser.add_argument(
        "--gap-types",
        nargs="*",
        choices=["missing_topic", "weak_coverage", "isolated_note", "missing_link"],
        help="Specific gap types to detect (optional)",
    )
    detect_gaps_parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    analyze_knowledge_parser = subparsers.add_parser(
        "analyze-knowledge", help="Perform comprehensive knowledge base analysis"
    )
    analyze_knowledge_parser.add_argument(
        "--no-gaps",
        action="store_true",
        help="Exclude gap detection from analysis",
    )
    analyze_knowledge_parser.add_argument(
        "--no-clusters",
        action="store_true",
        help="Exclude topic clustering from analysis",
    )
    analyze_knowledge_parser.add_argument(
        "--no-paths",
        action="store_true",
        help="Exclude learning path suggestions from analysis",
    )
    analyze_knowledge_parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    # Phase 2: Batch Operations
    batch_create_parser = subparsers.add_parser(
        "batch-create", help="Create multiple memories from JSON or CSV file"
    )
    batch_create_parser.add_argument(
        "input_file", help="Path to JSON or CSV file containing memories"
    )
    batch_create_parser.add_argument(
        "--format",
        choices=["json", "csv"],
        help="Input file format (auto-detected if not specified)",
    )
    batch_create_parser.add_argument(
        "--dry-run", action="store_true", help="Preview memories without creating them"
    )
    batch_create_parser.add_argument(
        "--auto-ingest",
        action="store_true",
        help="Automatically run ingest after creation",
    )

    batch_update_parser = subparsers.add_parser(
        "batch-update", help="Update multiple memories from file or by filter"
    )
    batch_update_parser.add_argument(
        "--input-file", help="Path to JSON/CSV file with updates"
    )
    batch_update_parser.add_argument("--filter-tags", nargs="*", help="Filter by tags")
    batch_update_parser.add_argument(
        "--filter-type",
        choices=[member.value for member in MemoryType],
        help="Filter by memory type",
    )
    batch_update_parser.add_argument(
        "--set-salience", type=float, help="Set salience for all matched memories"
    )
    batch_update_parser.add_argument(
        "--add-tags", nargs="*", help="Add tags to all matched memories"
    )
    batch_update_parser.add_argument(
        "--dry-run", action="store_true", help="Preview updates without applying"
    )
    batch_update_parser.add_argument(
        "--confirm", action="store_true", help="Skip confirmation prompt"
    )

    batch_delete_parser = subparsers.add_parser(
        "batch-delete", help="Delete multiple memories from file or by filter"
    )
    batch_delete_parser.add_argument(
        "--input-file", help="Path to file with memory IDs (one per line)"
    )
    batch_delete_parser.add_argument("--filter-tags", nargs="*", help="Filter by tags")
    batch_delete_parser.add_argument(
        "--filter-type",
        choices=[member.value for member in MemoryType],
        help="Filter by memory type",
    )
    batch_delete_parser.add_argument(
        "--older-than", help="Delete memories older than N days (e.g., '90d')"
    )
    batch_delete_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview deletions without removing files",
    )
    batch_delete_parser.add_argument(
        "--confirm", action="store_true", help="Skip confirmation prompt"
    )

    # Phase 3: Infrastructure
    export_parser = subparsers.add_parser(
        "export", help="Export vault to JSON, CSV, or markdown archive"
    )
    export_parser.add_argument("--output", required=True, help="Output file path")
    export_parser.add_argument(
        "--format",
        choices=["json", "csv", "markdown", "zip"],
        default="json",
        help="Export format (default: json)",
    )
    export_parser.add_argument(
        "--filter-tags", nargs="*", help="Export only memories with these tags"
    )
    export_parser.add_argument(
        "--compress", action="store_true", help="Compress output (for json/csv)"
    )

    import_backup_parser = subparsers.add_parser(
        "import-backup", help="Import memories from backup file"
    )
    import_backup_parser.add_argument(
        "backup_file", help="Path to backup file (JSON or ZIP)"
    )
    import_backup_parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge with existing vault (default: replace)",
    )
    import_backup_parser.add_argument(
        "--skip-duplicates",
        action="store_true",
        help="Skip memories that already exist",
    )

    backup_parser = subparsers.add_parser("backup", help="Create vault backup")
    backup_parser.add_argument(
        "--destination", required=True, help="Backup destination directory"
    )
    backup_parser.add_argument(
        "--compress",
        action="store_true",
        default=True,
        help="Compress backup (default: True)",
    )
    backup_parser.add_argument(
        "--keep", type=int, default=10, help="Number of backups to keep (default: 10)"
    )

    config_parser = subparsers.add_parser(
        "config", help="Manage configuration settings"
    )
    config_subparsers = config_parser.add_subparsers(
        dest="config_command", required=True
    )

    config_set_parser = config_subparsers.add_parser(
        "set", help="Set configuration value"
    )
    config_set_parser.add_argument("key", help="Configuration key")
    config_set_parser.add_argument("value", help="Configuration value")

    config_get_parser = config_subparsers.add_parser(
        "get", help="Get configuration value"
    )
    config_get_parser.add_argument("key", help="Configuration key")

    config_subparsers.add_parser("list", help="List all configuration")

    config_profile_parser = config_subparsers.add_parser(
        "profile", help="Manage profiles"
    )
    config_profile_parser.add_argument(
        "action", choices=["create", "use", "list", "delete"]
    )
    config_profile_parser.add_argument("name", nargs="?", help="Profile name")

    stats_parser = subparsers.add_parser(
        "stats", help="Show vault statistics and insights"
    )
    stats_parser.add_argument(
        "--detailed", action="store_true", help="Show detailed statistics"
    )
    stats_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    args = parser.parse_args()
    kernel = MemoryKernel(args.vault)

    if args.command == "ingest":
        print(kernel.ingest(force=args.force))
        return

    if args.command == "remember":
        # Interactive mode: prompt for missing required fields
        title = args.title
        if not title:
            title = input("Enter memory title: ").strip()
            if not title:
                print("Error: Title is required")
                return

        content = args.content
        if not content:
            print("Enter memory content (press Ctrl+D or Ctrl+Z when done):")
            lines = []
            try:
                while True:
                    line = input()
                    lines.append(line)
            except EOFError:
                pass
            content = "\n".join(lines).strip()
            if not content:
                print("Error: Content is required")
                return

        path = kernel.remember(
            title=title,
            content=content,
            memory_type=MemoryType(args.type),
            tags=args.tags,
            salience=args.salience,
        )
        print(f"Created memory: {path}")
        return

    if args.command == "context":
        context = kernel.context_window(
            query=args.query,
            tags=args.tags,
            depth=args.depth,
            top_k=args.top_k,
            token_limit=args.token_limit,
        )
        print(context)
        return

    if args.command == "ask":
        _run_ask(kernel, args)
        return

    if args.command == "import":
        from .importers.documents import DocumentImporter

        importer = DocumentImporter(args.vault)
        source_path = Path(args.path)

        if args.dry_run:
            # Dry run mode - just list files that would be imported
            if source_path.is_file():
                print(f"Would import: {source_path.name}")
            elif source_path.is_dir():
                if args.recursive:
                    files = list(source_path.rglob("*"))
                else:
                    files = list(source_path.glob("*"))

                supported = [
                    f
                    for f in files
                    if f.is_file()
                    and f.suffix.lower() in [".txt", ".pdf", ".docx", ".doc"]
                ]

                print(f"\nFound {len(supported)} files to import:")
                for f in supported:
                    print(f"  - {f.name}")
            else:
                print(f"Error: {source_path} not found")
            return

        # Actual import
        if source_path.is_file():
            # Import single file
            success, message = importer.import_file(
                str(source_path),
                memory_type=args.type,
                salience=args.salience,
                tags=args.tags,
                overwrite=args.overwrite,
            )
            if success:
                print(f"✓ {message}")
            else:
                print(f"✗ {message}")
                return

        elif source_path.is_dir():
            # Import folder
            print(f"\nImporting documents from: {source_path}")
            print(f"Target vault: {kernel.vault_path}\n")

            results = importer.import_folder(
                str(source_path),
                memory_type=args.type,
                salience=args.salience,
                tags=args.tags,
                overwrite=args.overwrite,
                recursive=args.recursive,
            )

            # Print summary
            print(f"\n{'=' * 50}")
            print("Import Summary:")
            print(f"  ✓ Success: {results['success']}")
            print(f"  ⊘ Skipped: {results['skipped']}")
            print(f"  ✗ Failed: {results['failed']}")

            if results["errors"]:
                print("\nErrors:")
                for error in results["errors"]:
                    print(f"  - {error}")

        else:
            print(f"Error: {source_path} not found")
            return

        # Auto-ingest if requested
        if args.auto_ingest and (
            results["success"] if source_path.is_dir() else success
        ):
            print(f"\n{'=' * 50}")
            print("Running ingest...")
            stats = kernel.ingest()
            print(f"✓ Indexed {stats['indexed']} files")
            print(f"  Total memories in vault: {stats['total']}")
        else:
            print(f"\n{'=' * 50}")
            print(f"Remember to run: memograph --vault {args.vault} ingest")

        return

    if args.command == "quickstart":
        from .quickstart import run_quickstart

        rc = run_quickstart(
            target=args.target,
            force=args.force,
            mcp=args.mcp or args.mcp_apply,
            mcp_apply=args.mcp_apply,
        )
        if rc != 0:
            sys.exit(rc)
        return

    if args.command == "doctor":
        _run_doctor(args)
        return

    if args.command == "setup-mcp":
        from .mcp_setup import MCPSetup

        setup = MCPSetup(vault_path=args.vault_path or args.vault)
        setup.interactive_setup()
        return

    if args.command == "verify-mcp":
        from .mcp_setup import MCPSetup

        setup = MCPSetup(vault_path=args.vault)
        results = setup.verify_setup()
        setup.print_verification_results(results)
        return

    if args.command == "suggest-tags":
        import asyncio
        import re
        from pathlib import Path

        from .ai.auto_tagger import AutoTagger

        async def _suggest():
            file_path = Path(args.file_path)

            if not file_path.exists():
                print(f"Error: File not found: {file_path}")
                return

            if file_path.suffix.lower() not in [".md", ".txt"]:
                print(
                    f"Warning: File type {file_path.suffix} may not be optimal. Expected .md or .txt"
                )

            # Read file content
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception as e:
                print(f"Error reading file: {e}")
                return

            # Extract existing tags
            existing_tags = re.findall(r"#(\w+)", content)

            # Create tagger and get suggestions
            tagger = AutoTagger(kernel, args.min_confidence, args.max_suggestions)
            suggestions = await tagger.suggest_tags(
                content, file_path.stem, existing_tags
            )

            if not suggestions:
                print("\nNo tag suggestions found.")
                return

            # Display suggestions
            print(f"\n=== Tag Suggestions for: {file_path.name} ===\n")
            for i, s in enumerate(suggestions, 1):
                bar = "=" * int(s.confidence * 10)
                print(f"{i}. #{s.tag} {bar} {s.confidence:.0%}")
                print(f"   {s.reason} ({s.source})\n")

            # Apply if requested
            if args.apply:
                tags_line = " ".join(f"#{s.tag}" for s in suggestions)
                new_content = content.rstrip() + f"\n\n{tags_line}\n"
                try:
                    file_path.write_text(new_content, encoding="utf-8")
                    print(f"\n[OK] Applied {len(suggestions)} tags to {file_path.name}")
                except Exception as e:
                    print(f"\n[ERROR] Failed to apply tags: {e}")

        asyncio.run(_suggest())
        return

    if args.command == "suggest-links":
        import asyncio
        import re
        from pathlib import Path

        from .ai.link_suggester import LinkSuggester

        async def _suggest_links():
            file_path = Path(args.file_path)

            if not file_path.exists():
                print(f"Error: File not found: {file_path}")
                return

            if file_path.suffix.lower() not in [".md", ".txt"]:
                print(
                    f"Warning: File type {file_path.suffix} may not be optimal. Expected .md or .txt"
                )

            # Read file content
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception as e:
                print(f"Error reading file: {e}")
                return

            # Extract existing wikilinks
            existing_links_pattern = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
            existing_links = existing_links_pattern.findall(content)

            # Create suggester and get suggestions
            suggester = LinkSuggester(kernel, args.min_confidence, args.max_suggestions)
            suggestions = await suggester.suggest_links(
                content=content, title=file_path.stem, existing_links=existing_links
            )

            if not suggestions:
                print("\nNo link suggestions found.")
                return

            # Display suggestions
            print(f"\n=== Link Suggestions for: {file_path.name} ===\n")
            for i, s in enumerate(suggestions, 1):
                bar = "=" * int(s.confidence * 10)
                bidirectional_marker = (
                    " ⟷" if (args.show_bidirectional and s.bidirectional) else ""
                )
                print(
                    f"{i}. [[{s.target_title}]] {bar} {s.confidence:.0%}{bidirectional_marker}"
                )
                print(f"   {s.reason} ({s.source})\n")

            # Apply if requested
            if args.apply:
                # Add wikilinks at the end of the file
                links_line = " ".join(f"[[{s.target_title}]]" for s in suggestions)
                new_content = (
                    content.rstrip() + f"\n\n## Suggested Links\n{links_line}\n"
                )
                try:
                    file_path.write_text(new_content, encoding="utf-8")
                    print(
                        f"\n✓ Applied {len(suggestions)} link suggestions to {file_path.name}"
                    )
                except Exception as e:
                    print(f"\n✗ Failed to apply links: {e}")

        asyncio.run(_suggest_links())
        return

    if args.command == "detect-gaps":
        import asyncio
        import json

        from .ai.gap_detector import GapDetector

        async def _detect_gaps():
            detector = GapDetector(
                kernel,
                min_severity=args.min_severity,
                max_gaps=args.max_gaps,
            )

            gaps = await detector.detect_gaps()

            # Filter by gap types if specified
            if args.gap_types:
                gaps = [g for g in gaps if g.gap_type in args.gap_types]

            if args.output == "json":
                # JSON output
                output = {
                    "success": True,
                    "count": len(gaps),
                    "gaps": [
                        {
                            "type": g.gap_type,
                            "title": g.title,
                            "description": g.description,
                            "severity": round(g.severity, 2),
                            "suggestions": g.suggestions,
                            "related_notes": g.related_notes[:5],
                        }
                        for g in gaps
                    ],
                }
                print(json.dumps(output, indent=2))
            else:
                # Text output
                if not gaps:
                    print("\n✓ No significant knowledge gaps detected!")
                    return

                print(f"\n=== Knowledge Gaps Detected ({len(gaps)}) ===\n")

                for i, gap in enumerate(gaps, 1):
                    severity_bar = "!" * int(gap.severity * 10)
                    print(f"{i}. [{gap.gap_type.upper()}] {gap.title}")
                    print(f"   Severity: {severity_bar} {gap.severity:.0%}")
                    print(f"   {gap.description}\n")

                    if gap.suggestions:
                        print("   Suggestions:")
                        for suggestion in gap.suggestions[:3]:
                            print(f"   • {suggestion}")

                    if gap.related_notes:
                        print(f"   Related: {', '.join(gap.related_notes[:3])}")

                    print()

        asyncio.run(_detect_gaps())
        return

    if args.command == "search":
        run_search_command(kernel, args)
        return

    if args.command == "update":
        run_update_command(kernel, args)
        return

    if args.command == "delete":
        run_delete_command(kernel, args)
        return

    if args.command == "list":
        run_list_command(kernel, args)
        return

    if args.command == "batch-create":
        run_batch_create_command(kernel, args)
        return

    if args.command == "batch-update":
        run_batch_update_command(kernel, args)
        return

    if args.command == "batch-delete":
        run_batch_delete_command(kernel, args)
        return

    if args.command == "export":
        run_export_command(kernel, args)
        return

    if args.command == "import-backup":
        run_import_backup_command(kernel, args)
        return

    if args.command == "backup":
        run_backup_command(kernel, args)
        return

    if args.command == "config":
        run_config_command(kernel, args)
        return

    if args.command == "stats":
        run_stats_command(kernel, args)
        return

    if args.command == "analyze-knowledge":
        import asyncio

        import json

        from .ai.gap_detector import GapDetector

        async def _analyze():
            detector = GapDetector(kernel)
            analysis = await detector.analyze_knowledge_base()

            # Filter components based on flags
            if args.no_gaps:
                analysis["gaps"] = []
                analysis["summary"]["total_gaps"] = 0
            if args.no_clusters:
                analysis["clusters"] = []
                analysis["summary"]["total_clusters"] = 0
            if args.no_paths:
                analysis["learning_paths"] = []
                analysis["summary"]["total_paths"] = 0

            if args.output == "json":
                # JSON output
                print(json.dumps(analysis, indent=2))
            else:
                # Text output
                summary = analysis["summary"]
                print("\n=== Knowledge Base Analysis ===\n")
                print(f"Total Gaps: {summary['total_gaps']}")
                print(f"Total Clusters: {summary['total_clusters']}")
                print(f"Total Learning Paths: {summary['total_paths']}")

                if summary.get("gap_types"):
                    print("\nGaps by Type:")
                    for gap_type, count in summary["gap_types"].items():
                        if count > 0:
                            print(f"  • {gap_type}: {count}")

                if summary.get("avg_severity"):
                    print(f"\nAverage Gap Severity: {summary['avg_severity']:.0%}")

                # Show top gaps
                if not args.no_gaps and analysis["gaps"]:
                    print("\n=== Top Knowledge Gaps ===\n")
                    for i, gap in enumerate(analysis["gaps"][:5], 1):
                        print(f"{i}. [{gap['type']}] {gap['title']}")
                        print(
                            f"   Severity: {gap['severity']:.0%} - {gap['description']}\n"
                        )

                # Show clusters
                if not args.no_clusters and analysis["clusters"]:
                    print("=== Topic Clusters ===\n")
                    for i, cluster in enumerate(analysis["clusters"][:5], 1):
                        print(f"{i}. {cluster['name']} ({cluster['size']} notes)")
                        print(f"   Keywords: {', '.join(cluster['keywords'][:5])}")
                        print(
                            f"   Density: {cluster['density']:.0%}, Coverage: {cluster['coverage']:.0%}\n"
                        )

                # Show learning paths
                if not args.no_paths and analysis["learning_paths"]:
                    print("=== Learning Paths ===\n")
                    for i, path in enumerate(analysis["learning_paths"][:3], 1):
                        print(f"{i}. {path['topic']} ({path['order']} path)")
                        print(f"   Completeness: {path['completeness']:.0%}")
                        print(f"   Notes: {len(path['notes'])}")
                        if path["missing_steps"]:
                            print(
                                f"   Missing: {', '.join(path['missing_steps'][:2])}\n"
                            )
                        else:
                            print()

        asyncio.run(_analyze())
        return


if __name__ == "__main__":
    main()
