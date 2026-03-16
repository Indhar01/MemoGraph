import argparse
import itertools
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib import error, request

from .core.assistant import build_answer_prompt, retrieve_cited_context, run_answer
from .core.enums import MemoryType
from .core.kernel import MemoryKernel


class Spinner:
    """Simple terminal spinner for showing progress during LLM requests."""

    def __init__(self, message: str = "Thinking"):
        self.message = message
        self.spinner_chars = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        self.stop_spinner = False
        self.spinner_thread: Optional[threading.Thread] = None

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
            should_stream = args.provider == "ollama" and args.stream and not args.no_spinner

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
            title = _generate_conversation_title(query, answer, provider, model, base_url)
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
            title = _generate_conversation_title(first_q, first_a, provider, model, base_url)
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

        print(f"\n✓ Saved conversation with {len(conversation_history)} exchanges to vault")

    except Exception as e:
        print(f"\nWarning: Failed to save combined conversation: {e}")


def _run_doctor(args) -> None:
    print("=== Mnemo Doctor ===")
    vault = MemoryKernel(args.vault)
    stats = vault.ingest(force=False)
    print(f"vault: {vault.vault_path}")
    print(f"indexed: {stats['indexed']} | skipped: {stats['skipped']} | total: {stats['total']}")

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
    parser = argparse.ArgumentParser(description="Mnemo CLI")
    parser.add_argument("--vault", default="~/my-vault", help="Path to memory vault")

    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Index all markdown memories")
    ingest_parser.add_argument("--force", action="store_true", help="Reindex all files")

    remember_parser = subparsers.add_parser("remember", help="Create a new memory note")
    remember_parser.add_argument("--title", required=True, help="Memory title")
    remember_parser.add_argument("--content", required=True, help="Memory content")
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

    context_parser = subparsers.add_parser("context", help="Build context window for a query")
    context_parser.add_argument("--query", required=True, help="Query text")
    context_parser.add_argument("--tags", nargs="*", default=[], help="Optional tag filter")
    context_parser.add_argument("--depth", type=int, default=2, help="Graph traversal depth")
    context_parser.add_argument("--top-k", type=int, default=8, help="Max memories to return")
    context_parser.add_argument(
        "--token-limit", type=int, default=2048, help="Compression token limit"
    )

    ask_parser = subparsers.add_parser("ask", help="Ask an LLM with retrieved memory context")
    ask_parser.add_argument(
        "--provider", choices=["claude", "ollama"], default="ollama", help="LLM provider"
    )
    ask_parser.add_argument("--query", help="Question text (omit in --chat mode)")
    ask_parser.add_argument("--chat", action="store_true", help="Interactive chat mode")
    ask_parser.add_argument("--tags", nargs="*", default=[], help="Optional tag filter")
    ask_parser.add_argument("--depth", type=int, default=2, help="Graph traversal depth")
    ask_parser.add_argument("--top-k", type=int, default=8, help="Max memories to retrieve")
    ask_parser.add_argument(
        "--token-limit", type=int, default=2048, help="Context compression budget"
    )
    ask_parser.add_argument("--model", default=None, help="Provider-specific model")
    ask_parser.add_argument("--base-url", default=None, help="Provider base URL override")
    ask_parser.add_argument("--max-tokens", type=int, default=1024, help="Max generated tokens")
    ask_parser.add_argument("--temperature", type=float, default=0.1, help="Sampling temperature")
    ask_parser.add_argument("--show-context", action="store_true", help="Print context sent to LLM")
    ask_parser.add_argument("--no-citations", action="store_true", help="Hide source list output")
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
        "--no-spinner", action="store_true", help="Disable spinner animation during LLM requests"
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

    doctor_parser = subparsers.add_parser(
        "doctor", help="Run environment and integration diagnostics"
    )
    doctor_parser.add_argument("--ollama-url", default=None, help="Override Ollama base URL")

    setup_mcp_parser = subparsers.add_parser("setup-mcp", help="Interactive MCP setup wizard")
    setup_mcp_parser.add_argument(
        "--vault-path", default=None, help="Default vault path for setup (optional)"
    )

    subparsers.add_parser("verify-mcp", help="Verify MCP setup and configuration")

    args = parser.parse_args()
    kernel = MemoryKernel(args.vault)

    if args.command == "ingest":
        print(kernel.ingest(force=args.force))
        return

    if args.command == "remember":
        path = kernel.remember(
            title=args.title,
            content=args.content,
            memory_type=MemoryType(args.type),
            tags=args.tags,
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
                    if f.is_file() and f.suffix.lower() in [".txt", ".pdf", ".docx", ".doc"]
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
            print(f"\n{'='*50}")
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
        if args.auto_ingest and (results["success"] if source_path.is_dir() else success):
            print(f"\n{'='*50}")
            print("Running ingest...")
            stats = kernel.ingest()
            print(f"✓ Indexed {stats['indexed']} files")
            print(f"  Total memories in vault: {stats['total']}")
        else:
            print(f"\n{'='*50}")
            print(f"Remember to run: memograph --vault {args.vault} ingest")

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


if __name__ == "__main__":
    main()
