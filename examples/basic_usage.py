"""Basic usage example for MemoGraph."""

from memograph import MemoryKernel, MemoryType

# Initialize the kernel
kernel = MemoryKernel("~/my-vault")

# Add a memory
kernel.remember(
    title="Python Best Practices",
    content="Always use type hints and write comprehensive docstrings.",
    memory_type=MemoryType.SEMANTIC,
    tags=["python", "best-practices"],
)

# Index the vault
stats = kernel.ingest()
print(f"Indexed {stats['indexed']} new memories")
print(f"Total memories: {stats['total']}")

# Query the vault
context = kernel.context_window(
    query="What are the Python best practices?", tags=["python"], depth=2, top_k=5
)

print("\nRetrieved Context:")
print(context)
