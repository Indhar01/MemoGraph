import tempfile
import unittest

from memograph import MemoryKernel, MemoryType
from memograph.core.assistant import (
    build_answer_prompt,
    build_cited_context,
    retrieve_cited_context,
)
from memograph.core.node import MemoryNode


class AssistantTests(unittest.TestCase):
    def test_build_cited_context_adds_source_markers(self):
        nodes = [
            MemoryNode(
                id="retrieval-decision",
                title="Retrieval Decision",
                content="We decided to use BFS traversal first.",
                memory_type=MemoryType.SEMANTIC,
                tags=["retrieval", "design"],
            ),
            MemoryNode(
                id="embedding-plan",
                title="Embedding Plan",
                content="Embeddings are optional for reranking.",
                memory_type=MemoryType.FACT,
                tags=["embeddings"],
            ),
        ]

        context, sources = build_cited_context(nodes=nodes, token_limit=512)

        self.assertIn("[S1] Retrieval Decision", context)
        self.assertIn("[S2] Embedding Plan", context)
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0].source_id, "S1")
        self.assertEqual(sources[1].source_id, "S2")

    def test_build_answer_prompt_contains_contract_and_question(self):
        context = "[S1] Retrieval Decision | type=semantic | tags=retrieval\nUse BFS."
        query = "How does retrieval work?"

        prompt = build_answer_prompt(context=context, query=query)

        self.assertIn("cite source markers like [S1], [S2]", prompt)
        self.assertIn("<memory>", prompt)
        self.assertIn(context, prompt)
        self.assertIn(f"User question: {query}", prompt)

    def test_retrieve_cited_context_from_kernel(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = MemoryKernel(tmp)
            kernel.remember(
                title="Retrieval Decision",
                content="Primary approach is BFS graph traversal.",
                memory_type=MemoryType.SEMANTIC,
                tags=["retrieval", "design"],
            )
            kernel.remember(
                title="Release Note",
                content="Updated documentation formatting.",
                memory_type=MemoryType.FACT,
                tags=["docs"],
            )

            context, sources = retrieve_cited_context(
                kernel=kernel,
                query="What retrieval approach was selected?",
                tags=["retrieval"],
                depth=2,
                top_k=5,
                token_limit=512,
            )

            self.assertGreaterEqual(len(sources), 1)
            self.assertIn("Retrieval Decision", context)
            self.assertTrue(any(src.node_id == "retrieval-decision" for src in sources))


if __name__ == "__main__":
    unittest.main()
