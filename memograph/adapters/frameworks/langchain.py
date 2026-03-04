from ...core.node import MemoryNode


def to_langchain_documents(nodes: list[MemoryNode]) -> list[dict]:
    return [
        {
            "page_content": node.content,
            "metadata": {
                "id": node.id,
                "title": node.title,
                "memory_type": node.memory_type.value,
                "tags": node.tags,
                "salience": node.salience,
            },
        }
        for node in nodes
    ]
