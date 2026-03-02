"""Example showing different memory types."""

from mnemo import MemoryKernel, MemoryType

kernel = MemoryKernel("~/my-vault")

# Episodic memory: personal experiences
kernel.remember(
    title="Team Meeting - Q1 Planning",
    content="We discussed the roadmap for Q1. Key decisions: migrate to microservices, adopt GraphQL.",
    memory_type=MemoryType.EPISODIC,
    tags=["meeting", "planning", "2024-Q1"]
)

# Semantic memory: general knowledge
kernel.remember(
    title="Microservices Architecture",
    content="Microservices are an architectural style that structures an application as a collection of loosely coupled services.",
    memory_type=MemoryType.SEMANTIC,
    tags=["architecture", "design-patterns"]
)

# Procedural memory: how-to knowledge
kernel.remember(
    title="How to Deploy with Docker",
    content="""
    1. Build the image: docker build -t myapp .
    2. Run the container: docker run -p 8000:8000 myapp
    3. Check logs: docker logs <container-id>
    """,
    memory_type=MemoryType.PROCEDURAL,
    tags=["docker", "deployment", "tutorial"]
)

# Fact memory: discrete facts
kernel.remember(
    title="API Configuration",
    content="Production API endpoint: https://api.example.com/v1",
    memory_type=MemoryType.FACT,
    tags=["configuration", "api"]
)

# Ingest and query
kernel.ingest()

# Query for procedural knowledge
context = kernel.context_window(
    query="How do I deploy?",
    depth=1,
    top_k=3
)

print("Deployment instructions:")
print(context)