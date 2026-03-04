"""Example demonstrating embedding support for semantic search."""

from memograph import MemoryKernel, MemoryType

# Choose your embedding provider:

# Option 1: Sentence Transformers (Local, Free, No API Key)
from memograph.adapters.embeddings.sentence_transformers import (
    SentenceTransformerEmbeddings,
)

embedder = SentenceTransformerEmbeddings(
    model_name="all-MiniLM-L6-v2",  # Fast, good quality
    device="cpu",  # or "cuda" for GPU, "mps" for Apple Silicon
)

# Option 2: OpenAI (Best Quality, Requires API Key)
# from memograph.adapters.embeddings.openai import OpenAIEmbeddingAdapter
# embedder = OpenAIEmbeddingAdapter(
#     model="text-embedding-3-small",  # or "text-embedding-3-large"
#     api_key="your-api-key"  # or set OPENAI_API_KEY env var
# )

# Option 3: Ollama (Local, Free)
# from memograph.adapters.embeddings.ollama import OllamaEmbeddingAdapter
# embedder = OllamaEmbeddingAdapter(
#     model="nomic-embed-text",  # or "all-minilm", "mxbai-embed-large"
#     base_url="http://localhost:11434"
# )

# Initialize kernel with embedding adapter
kernel = MemoryKernel("~/my-vault", embedding_adapter=embedder)

# Add some test memories
kernel.remember(
    title="Python Programming",
    content="""
    Python is a high-level, interpreted programming language known for its simplicity and readability.
    It's widely used in data science, web development, automation, and AI/ML applications.
    Popular frameworks include Django, Flask, FastAPI, and PyTorch.
    """,
    memory_type=MemoryType.SEMANTIC,
    tags=["programming", "python"],
)

kernel.remember(
    title="Machine Learning Basics",
    content="""
    Machine learning is a subset of artificial intelligence that enables systems to learn from data.
    Common algorithms include linear regression, decision trees, neural networks, and transformers.
    Python libraries like scikit-learn, TensorFlow, and PyTorch are commonly used.
    """,
    memory_type=MemoryType.SEMANTIC,
    tags=["ml", "ai", "python"],
)

kernel.remember(
    title="Web Development",
    content="""
    Web development involves building websites and web applications.
    Frontend uses HTML, CSS, and JavaScript. Backend can use Python, Node.js, or other languages.
    Modern frameworks include React, Vue, Angular for frontend and Django, Express for backend.
    """,
    memory_type=MemoryType.SEMANTIC,
    tags=["web", "programming"],
)

kernel.remember(
    title="Database Design",
    content="""
    Databases store and organize data. SQL databases (PostgreSQL, MySQL) use tables and relationships.
    NoSQL databases (MongoDB, Redis) offer flexible schemas.
    Choose based on data structure, scalability needs, and consistency requirements.
    """,
    memory_type=MemoryType.SEMANTIC,
    tags=["database", "backend"],
)

# Index the vault (generates and caches embeddings)
print("Indexing vault and generating embeddings...")
stats = kernel.ingest()
print(f"✓ Indexed {