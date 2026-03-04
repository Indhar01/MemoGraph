# adapters/embeddings/base.py
from abc import ABC, abstractmethod


class EmbeddingAdapter(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]
