import json
import os
from dataclasses import dataclass, field
from urllib import error, request


@dataclass
class OllamaLLMConfig:
    model: str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL", "llama3.1:8b"))
    max_tokens: int = 512
    temperature: float = 0.1


class OllamaLLMClient:
    def __init__(self, base_url: str | None = None):
        effective_base = base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.url = f"{effective_base.rstrip('/')}/api/generate"

    def generate(self, prompt: str, config: OllamaLLMConfig) -> str:
        payload = {
            "model": config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": config.temperature,
                "num_predict": config.max_tokens,
            },
        }
        req = request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=180) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8") if exc.fp else str(exc)
            raise RuntimeError(f"Ollama HTTP error ({exc.code}): {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(
                "Cannot reach Ollama. Start it first (e.g., `ollama serve`) "
                f"and verify base URL {self.url}."
            ) from exc
        return body.get("response", "").strip()
