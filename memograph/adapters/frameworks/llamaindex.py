from ...core.node import MemoryNode


def to_llamaindex_documents(nodes: list[MemoryNode]) -> list[dict]:
    return [
        {
            "text": node.content,
            "doc_id": node.id,
            "metadata": {
                "title": node.title,
                "memory_type": node.memory_type.value,
                "tags": node.tags,
                "salience": node.salience,
            },
        }
        for node in nodes
    ]
