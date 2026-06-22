from .base import EmbeddingAdapter


class OpenAIEmbeddingAdapter(EmbeddingAdapter):
    def __init__(
        self, model: str = "text-embedding-3-small", api_key: str | None = None
    ):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "Install the optional dependency with: pip install openai"
            ) from exc

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def embed(self, text: str) -> list[float]:
        resp = self.client.embeddings.create(input=[text], model=self.model)
        # OpenAI's SDK returns the embedding as a typed list[float] at
        # runtime but its stubs declare it as Any; cast keeps mypy clean.
        return list(resp.data[0].embedding)
