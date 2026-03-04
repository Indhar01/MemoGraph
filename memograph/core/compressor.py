# core/compressor.py
from .node import MemoryNode


class TokenCompressor:
    def __init__(self, token_limit: int = 4096, chars_per_token: float = 3.8):
        self.char_limit = int(token_limit * chars_per_token)

    def compress(self, nodes: list[MemoryNode], separator: str = "\n\n---\n\n") -> str:
        parts, total = [], 0
        for node in nodes:
            chunk = f"## {node.title}\n*Type: {node.memory_type.value} | Salience: {node.salience:.2f}*\n\n{node.content}"
            if total + len(chunk) > self.char_limit:
                # Truncate last entry to fit
                remaining = self.char_limit - total
                if remaining > 100:
                    parts.append(chunk[:remaining] + "…")
                break
            parts.append(chunk)
            total += len(chunk) + len(separator)
        return separator.join(parts)
