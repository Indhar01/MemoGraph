import argparse
import json
import os
from urllib import error, request

from .core.assistant import build_answer_prompt, retrieve_cited_context, run_answer
from .core.enums import MemoryType
from .core.kernel import MemoryKernel


def _run_ask(kernel: MemoryKernel, args) -> None:
    if args.provider == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Set ANTHROPIC_API_KEY or use --provider ollama.")

    def ask_once(query_text: str) -> None:
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
            answer = run_answer(
                provider=args.provider,
                prompt=prompt,
                model=args.model,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                base_url=args.base_url,
            )
        except Exception as exc:
            print(f"LLM error: {exc}")
            return

        if args.show_context:
            print("=== Retrieved Context ===")
            print(context)
            print()

        print("=== Answer ===")
        print(answer)

        if sources and not args.no_citations:
            print("\n=== Sources ===")
            for src in sources:
                tags = ", ".join(src.tags) if src.tags else "-"
                print(
                    f"[{src.source_id}] {src.title} (id={src.node_id}, type={src.memory_type}, tags={tags})"
                )

    if args.chat:
        print("Interactive chat mode. Type 'exit' or 'quit' to stop.")
        while True:
            query_text = input("you> ").strip()
            if not query_text:
                continue
            if query_text.lower() in {"exit", "quit"}:
                print("bye")
                break
            ask_once(query_text)
            print()
        return

    if not args.query:
        raise RuntimeError("Provide --query for non-chat mode.")
    ask_once(args.query)


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

    doctor_parser = subparsers.add_parser(
        "doctor", help="Run environment and integration diagnostics"
    )
    doctor_parser.add_argument("--ollama-url", default=None, help="Override Ollama base URL")

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

    if args.command == "doctor":
        _run_doctor(args)
        return


if __name__ == "__main__":
    main()
