import os
from dataclasses import dataclass, field


@dataclass
class ClaudeLLMConfig:
    model: str = field(default_factory=lambda: os.environ.get("MODEL_NAME", "claude-sonnet-4-5"))
    max_tokens: int = 1024
    temperature: float = 0.1


class ClaudeLLMClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic client not installed. Run: pip install anthropic"
            ) from exc

        effective_base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        if api_key and effective_base_url:
            self._client = Anthropic(api_key=api_key, base_url=effective_base_url)
        elif api_key:
            self._client = Anthropic(api_key=api_key)
        elif effective_base_url:
            self._client = Anthropic(base_url=effective_base_url)
        else:
            self._client = Anthropic()

    def generate(self, prompt: str, config: ClaudeLLMConfig) -> str:
        response = self._client.messages.create(
            model=config.model,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text_chunks = []
        for block in response.content:
            block_text = getattr(block, "text", None)
            if block_text:
                text_chunks.append(block_text)
        return "\n".join(text_chunks).strip()
