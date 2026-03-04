"""Example demonstrating graph traversal with wikilinks."""

from memograph import MemoryKernel, MemoryType

kernel = MemoryKernel("~/my-vault")

# Create interconnected memories with wikilinks
kernel.remember(
    title="graph-algorithms",
    content="""
    Graph algorithms are fundamental in computer science.
    Common algorithms include [[bfs]] and [[dfs]].
    """,
    memory_type=MemoryType.SEMANTIC,
    tags=["algorithms", "graphs"],
)

kernel.remember(
    title="bfs",
    content="""
    Breadth-First Search (BFS) explores nodes level by level.
    Used in [[shortest-path]] problems.
    """,
    memory_type=MemoryType.PROCEDURAL,
    tags=["algorithms", "search"],
)

kernel.remember(
    title="dfs",
    content="""
    Depth-First Search (DFS) explores as far as possible along each branch.
    Useful for [[topological-sort]] and cycle detection.
    """,
    memory_type=MemoryType.PROCEDURAL,
    tags=["algorithms", "search"],
)

# Index the vault
kernel.ingest()

# Retrieve with graph traversal
nodes = kernel.retrieve_nodes(
    query="graph algorithms",
    depth=2,  # Will traverse 2 hops through the graph
    top_k=10,
)

print(f"Retrieved {len(nodes)} related memories:")
for node in nodes:
    print(f"  - {node.title} (links: {node.links}, backlinks: {node.backlinks})")
