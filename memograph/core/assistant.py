from __future__ import annotations

from dataclasses import dataclass

from .kernel import MemoryKernel
from .node import MemoryNode


@dataclass
class SourceRef:
    source_id: str
    node_id: str
    title: str
    memory_type: str
    tags: list[str]


def build_cited_context(
    nodes: list[MemoryNode],
    token_limit: int = 2048,
    chars_per_token: float = 3.8,
) -> tuple[str, list[SourceRef]]:
    char_limit = int(token_limit * chars_per_token)
    sections: list[str] = []
    sources: list[SourceRef] = []
    total = 0
    separator = "\n\n---\n\n"

    for index, node in enumerate(nodes, start=1):
        sid = f"S{index}"
        tags = ", ".join(node.tags) if node.tags else "-"
        header = f"[{sid}] {node.title} | type={node.memory_type.value} | tags={tags}"
        chunk = f"{header}\n{node.content}"

        projected = total + len(chunk) + (len(separator) if sections else 0)
        if projected > char_limit:
            remaining = char_limit - total
            if remaining > 120:
                truncated = chunk[:remaining].rstrip() + "…"
                sections.append(truncated)
                sources.append(
                    SourceRef(
                        source_id=sid,
                        node_id=node.id,
                        title=node.title,
                        memory_type=node.memory_type.value,
                        tags=node.tags,
                    )
                )
            break

        sections.append(chunk)
        sources.append(
            SourceRef(
                source_id=sid,
                node_id=node.id,
                title=node.title,
                memory_type=node.memory_type.value,
                tags=node.tags,
            )
        )
        total = projected

    return separator.join(sections), sources


def build_answer_prompt(context: str, query: str) -> str:
    return (
        "You are a helpful assistant. Use memory context only when relevant. "
        "If context is insufficient, say what is missing. "
        "When you use evidence, cite source markers like [S1], [S2].\n\n"
        f"<memory>\n{context}\n</memory>\n\n"
        f"User question: {query}"
    )


def run_answer(
    provider: str,
    prompt: str,
    model: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.1,
    base_url: str | None = None,
) -> str:
    if provider == "claude":
        from ..adapters.llm.claude import ClaudeLLMClient, ClaudeLLMConfig

        client = ClaudeLLMClient(base_url=base_url)
        # Default to a widely available model if not specified, though future models may differ.
        config = ClaudeLLMConfig(
            model=model or "claude-3-5-sonnet-20240620",
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return client.generate(prompt=prompt, config=config)

    if provider == "ollama":
        from ..adapters.llm.ollama import OllamaLLMClient, OllamaLLMConfig

        client = OllamaLLMClient(base_url=base_url)
        config = OllamaLLMConfig(
            model=model or "llama3.1:8b",
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return client.generate(prompt=prompt, config=config)

    raise ValueError(f"Unsupported provider: {provider}")


def retrieve_cited_context(
    kernel: MemoryKernel,
    query: str,
    tags: list[str] | None = None,
    depth: int = 2,
    top_k: int = 8,
    token_limit: int = 2048,
) -> tuple[str, list[SourceRef]]:
    nodes = kernel.retrieve_nodes(query=query, tags=tags, depth=depth, top_k=top_k)
    return build_cited_context(nodes=nodes, token_limit=token_limit)
