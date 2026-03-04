# adapters/embeddings/sentence_transformers.py
"""Sentence Transformers embedding adapter for local, free embeddings."""

from .base import EmbeddingAdapter


class SentenceTransformerEmbeddings(EmbeddingAdapter):
    """
    Local embedding adapter using sentence-transformers.
    
    Popular models:
    - 'all-MiniLM-L6-v2': Fast, 384 dimensions, good quality
    - 'all-mpnet-base-v2': Slower, 768 dimensions, better quality
    - 'multi-qa-mpnet-base-dot-v1': Optimized for Q&A
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str = "cpu"):
        """
        Initialize sentence-transformers embedding model.
        
        Args:
            model_name: HuggingFace model identifier
            device: 'cpu', 'cuda', or 'mps' (for Apple Silicon)
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "Install the optional dependency with: pip install memograph[embeddings]"
            ) from exc

        self.model = SentenceTransformer(model_name, device=device)
        self.model_name = model_name

    def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts efficiently."""
        embeddings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return embeddings.tolist()