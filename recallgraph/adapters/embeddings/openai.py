from .base import EmbeddingAdapter


class OpenAIEmbeddingAdapter(EmbeddingAdapter):
    def __init__(self, model: str = "text-embedding-3-small", api_key: str | None = None):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError("Install the optional dependency with: pip install openai") from exc

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def embed(self, text: str) -> list[float]:
        resp = self.client.embeddings.create(input=[text], model=self.model)
        return resp.data[0].embedding
