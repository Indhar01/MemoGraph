import json
import os
from dataclasses import dataclass, field
from urllib import error, request


@dataclass
class OllamaLLMConfig:
    model: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
    )
    max_tokens: int = 512
    temperature: float = 0.1
    timeout: int = field(
        default_factory=lambda: int(os.environ.get("OLLAMA_TIMEOUT", "600"))
    )
    stream: bool = True


class OllamaLLMClient:
    def __init__(self, base_url: str | None = None):
        effective_base = base_url or os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self.url = f"{effective_base.rstrip('/')}/api/generate"

    def generate(
        self, prompt: str, config: OllamaLLMConfig, stream_callback=None
    ) -> str:
        """
        Generate a response from Ollama.

        Args:
            prompt: The prompt to send to the model
            config: Configuration for the LLM
            stream_callback: Optional callback function for streaming tokens.
                           Should accept a string token as parameter.

        Returns:
            Complete response text
        """
        payload = {
            "model": config.model,
            "prompt": prompt,
            "stream": config.stream,
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
            if config.stream and stream_callback:
                # Streaming mode: process tokens as they arrive
                return self._generate_stream(req, config.timeout, stream_callback)
            else:
                # Non-streaming mode: wait for complete response
                return self._generate_non_stream(req, config.timeout)

        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8") if exc.fp else str(exc)
            raise RuntimeError(f"Ollama HTTP error ({exc.code}): {detail}") from exc
        except error.URLError as exc:
            if "timed out" in str(exc).lower():
                raise RuntimeError(
                    f"Ollama request timed out after {config.timeout} seconds. "
                    f"Try increasing timeout with --ollama-timeout or OLLAMA_TIMEOUT env variable."
                ) from exc
            raise RuntimeError(
                "Cannot reach Ollama. Start it first (e.g., `ollama serve`) "
                f"and verify base URL {self.url}."
            ) from exc

    def _generate_non_stream(self, req: request.Request, timeout: int) -> str:
        """Generate response without streaming."""
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310  # nosec B310
            body = json.loads(response.read().decode("utf-8"))
        response_text: str = body.get("response", "")
        return response_text.strip()

    def _generate_stream(
        self, req: request.Request, timeout: int, stream_callback
    ) -> str:
        """Generate response with streaming token display."""
        full_response = []

        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310  # nosec B310
            # Read the stream line by line
            for line in response:
                if not line:
                    continue

                try:
                    chunk = json.loads(line.decode("utf-8"))
                    token = chunk.get("response", "")

                    if token:
                        full_response.append(token)
                        # Call the callback with the token
                        if stream_callback:
                            stream_callback(token)

                    # Check if this is the final chunk
                    if chunk.get("done", False):
                        break

                except json.JSONDecodeError:
                    # Skip invalid JSON lines
                    continue

        return "".join(full_response).strip()
