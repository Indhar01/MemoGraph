import json
from urllib import request

from .base import EmbeddingAdapter


class OllamaEmbeddingAdapter(EmbeddingAdapter):
    def __init__(
        self, model: str = "nomic-embed-text", base_url: str = "http://localhost:11434"
    ):
        self.model = model
        self.url = f"{base_url.rstrip('/')}/api/embeddings"

    def embed(self, text: str) -> list[float]:
        payload = json.dumps({"model": self.model, "prompt": text}).encode("utf-8")
        req = request.Request(
            self.url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # base_url is constrained to a configured http(s) Ollama endpoint.
        with request.urlopen(req, timeout=30) as response:  # noqa: S310  # nosec B310
            body = json.loads(response.read().decode("utf-8"))
        embedding: list[float] = body["embedding"]
        return embedding
