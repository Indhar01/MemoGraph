"""Tests for TokenCompressor and assistant context building."""

from memograph.core.assistant import SourceRef, build_answer_prompt, build_cited_context
from memograph.core.compressor import TokenCompressor
from memograph.core.enums import MemoryType
from memograph.core.node import MemoryNode


def make_node(title="Test", content="Content", **kwargs):
    return MemoryNode(
        id=title.lower().replace(" ", "-"),
        title=title,
        content=content,
        **kwargs,
    )


class TestTokenCompressor:
    """Test TokenCompressor."""

    def test_compress_single_node(self):
        compressor = TokenCompressor(token_limit=4096)
        nodes = [make_node("Python Tips", "Use list comprehensions")]
        result = compressor.compress(nodes)
        assert "Python Tips" in result
        assert "list comprehensions" in result

    def test_compress_multiple_nodes(self):
        compressor = TokenCompressor(token_limit=4096)
        nodes = [
            make_node("Note 1", "Content 1"),
            make_node("Note 2", "Content 2"),
        ]
        result = compressor.compress(nodes)
        assert "Note 1" in result
        assert "Note 2" in result
        assert "---" in result

    def test_compress_truncates_at_limit(self):
        compressor = TokenCompressor(token_limit=50)  # very low limit
        nodes = [
            make_node("Note 1", "Short content"),
            make_node("Note 2", "This should be truncated or excluded"),
        ]
        result = compressor.compress(nodes)
        # Should have at most ~190 chars (50 * 3.8)
        assert len(result) <= 250

    def test_compress_empty(self):
        compressor = TokenCompressor(token_limit=4096)
        result = compressor.compress([])
        assert result == ""

    def test_compress_includes_type_and_salience(self):
        compressor = TokenCompressor(token_limit=4096)
        nodes = [make_node("Test", "Content", salience=0.85)]
        result = compressor.compress(nodes)
        assert "0.85" in result
        assert "semantic" in result


class TestBuildCitedContext:
    """Test build_cited_context."""

    def test_basic_context(self):
        nodes = [make_node("Tip 1", "First tip", tags=["python"])]
        context, sources = build_cited_context(nodes)
        assert "[S1]" in context
        assert "First tip" in context
        assert len(sources) == 1
        assert sources[0].source_id == "S1"
        assert sources[0].title == "Tip 1"

    def test_multiple_sources(self):
        nodes = [
            make_node("Tip 1", "First"),
            make_node("Tip 2", "Second"),
            make_node("Tip 3", "Third"),
        ]
        context, sources = build_cited_context(nodes)
        assert len(sources) == 3
        assert sources[2].source_id == "S3"

    def test_truncation(self):
        nodes = [make_node("Long", "x" * 10000)]
        context, sources = build_cited_context(nodes, token_limit=100)
        assert len(context) < 500
        assert context.endswith("…")

    def test_source_ref_fields(self):
        nodes = [
            make_node(
                "Test",
                "Content",
                memory_type=MemoryType.EPISODIC,
                tags=["meeting", "q3"],
            )
        ]
        _, sources = build_cited_context(nodes)
        ref = sources[0]
        assert isinstance(ref, SourceRef)
        assert ref.memory_type == "episodic"
        assert ref.tags == ["meeting", "q3"]


class TestBuildAnswerPrompt:
    """Test build_answer_prompt."""

    def test_prompt_structure(self):
        prompt = build_answer_prompt(context="Some context", query="What is X?")
        assert "<memory>" in prompt
        assert "Some context" in prompt
        assert "What is X?" in prompt
        assert "[S1]" in prompt or "cite" in prompt.lower()

    def test_prompt_includes_instructions(self):
        prompt = build_answer_prompt(context="ctx", query="q")
        assert "helpful assistant" in prompt.lower()
