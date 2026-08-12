import pytest
from memograph.ai.content_analyzer import ContentAnalyzer
from memograph import MemoryKernel


@pytest.fixture
def analyzer(tmp_path):
    kernel = MemoryKernel(str(tmp_path / "test_vault"))
    return ContentAnalyzer(kernel)


@pytest.fixture
def analyzer_with_embeddings(tmp_path):
    """Analyzer with a sentence-transformers embedding adapter.

    Skips when the optional ``embeddings-local`` extra (sentence-transformers
    + torch) is not installed — the default CI install is ``[dev,all]`` which
    deliberately excludes it, so this fixture must degrade to a skip rather
    than error the whole test session.
    """
    try:
        from memograph.adapters.embeddings.sentence_transformers import (
            SentenceTransformerEmbeddings,
        )

        adapter = SentenceTransformerEmbeddings()
    except Exception as exc:  # ImportError or model-load failure
        pytest.skip(f"sentence-transformers not available: {exc}")

    kernel = MemoryKernel(str(tmp_path / "test_vault"))
    kernel.embedding_adapter = adapter
    return ContentAnalyzer(kernel)


# ============================================================================
# extract_keywords tests
# ============================================================================


def test_extract_keywords_basic(analyzer):
    """Test basic keyword extraction with frequency analysis."""
    content = "Python is great. Python is versatile. Python programming."
    keywords = analyzer.extract_keywords(content, max_keywords=5)
    assert len(keywords) > 0
    assert keywords[0][0] == "python"
    assert keywords[0][1] >= 2  # 'python' appears multiple times


def test_extract_keywords_filters_stop_words(analyzer):
    """Test that stop words are filtered out."""
    content = "the and or but in on at to for of with by from"
    keywords = analyzer.extract_keywords(content, max_keywords=10)
    assert len(keywords) == 0  # All stop words should be filtered


def test_extract_keywords_min_frequency(analyzer):
    """Test min_frequency parameter."""
    content = "python java python javascript python ruby"
    keywords = analyzer.extract_keywords(content, max_keywords=10, min_frequency=2)
    assert len(keywords) == 1  # Only 'python' appears >= 2 times
    assert keywords[0][0] == "python"


def test_extract_keywords_max_keywords(analyzer):
    """Test max_keywords parameter limits results."""
    content = " ".join(
        [f"word{i}" for i in range(20)] * 2
    )  # 20 unique words, each appears twice
    keywords = analyzer.extract_keywords(content, max_keywords=5, min_frequency=2)
    assert len(keywords) <= 5


def test_extract_keywords_empty_content(analyzer):
    """Test with empty content."""
    keywords = analyzer.extract_keywords("", max_keywords=5)
    assert keywords == []


def test_extract_keywords_filters_short_words(analyzer):
    """Test that words shorter than 3 characters are filtered."""
    content = "a ab abc abcd abcde"
    keywords = analyzer.extract_keywords(content, max_keywords=10, min_frequency=1)
    # Only 'abc', 'abcd', 'abcde' should be extracted (3+ chars)
    assert all(len(word) >= 3 for word, _ in keywords)


# ============================================================================
# extract_existing_tags tests
# ============================================================================


def test_extract_existing_tags_basic(analyzer):
    """Test basic hashtag extraction."""
    content = "Note about #python and #ai"
    tags = analyzer.extract_existing_tags(content)
    assert "python" in tags
    assert "ai" in tags
    assert len(tags) == 2


def test_extract_existing_tags_multiple(analyzer):
    """Test extraction of multiple tags."""
    content = "#tag1 #tag2 #tag3 #tag4"
    tags = analyzer.extract_existing_tags(content)
    assert len(tags) == 4
    assert all(f"tag{i}" in tags for i in range(1, 5))


def test_extract_existing_tags_no_tags(analyzer):
    """Test with content that has no tags."""
    content = "Just plain text without any tags"
    tags = analyzer.extract_existing_tags(content)
    assert len(tags) == 0


def test_extract_existing_tags_mixed_content(analyzer):
    """Test tags mixed with other content."""
    content = """
    # Heading
    Some text about #python programming
    - List item with #ai
    Code: print('hello') #code
    """
    tags = analyzer.extract_existing_tags(content)
    assert "python" in tags
    assert "ai" in tags
    assert "code" in tags


# ============================================================================
# analyze_structure tests
# ============================================================================


def test_analyze_structure_headings(analyzer):
    """Test heading count detection."""
    content = "# H1\n## H2\n### H3\n#### H4"
    structure = analyzer.analyze_structure(content)
    assert structure["heading_count"] == 4


def test_analyze_structure_lists(analyzer):
    """Test list count detection."""
    content = "- item1\n- item2\n* item3\n+ item4"
    structure = analyzer.analyze_structure(content)
    assert structure["list_count"] == 4


def test_analyze_structure_code_blocks(analyzer):
    """Test code block detection."""
    content = "```python\ncode1\n```\n```js\ncode2\n```"
    structure = analyzer.analyze_structure(content)
    assert structure["code_block_count"] == 2


def test_analyze_structure_links(analyzer):
    """Test wikilink detection."""
    content = "[[link1]] and [[link2]] and [[link3]]"
    structure = analyzer.analyze_structure(content)
    assert structure["link_count"] == 3


def test_analyze_structure_word_count(analyzer):
    """Test word count."""
    content = "one two three four five"
    structure = analyzer.analyze_structure(content)
    assert structure["word_count"] == 5


def test_analyze_structure_frontmatter(analyzer):
    """Test frontmatter detection."""
    content = "---\ntitle: Test\n---\nContent here"
    structure = analyzer.analyze_structure(content)
    assert structure["has_frontmatter"] is True

    content_no_fm = "Content without frontmatter"
    structure = analyzer.analyze_structure(content_no_fm)
    assert structure["has_frontmatter"] is False


def test_analyze_structure_comprehensive(analyzer):
    """Test all structure analysis features together."""
    content = """---
title: Test Note
---

# Main Heading
## Sub Heading

Some text with [[wikilink1]] and [[wikilink2]].

- List item 1
- List item 2
- List item 3

```python
def example():
    return "code"
```

More text with [[wikilink3]].
"""
    structure = analyzer.analyze_structure(content)
    assert structure["heading_count"] == 2
    assert structure["list_count"] == 3
    assert structure["code_block_count"] == 1
    assert structure["link_count"] == 3
    assert structure["word_count"] > 10
    assert structure["has_frontmatter"] is True


# ============================================================================
# detect_content_type tests
# ============================================================================


def test_detect_content_type_code(analyzer):
    """Test detection of code-heavy content."""
    content = "\n".join([f"```python\ncode{i}\n```" for i in range(5)])
    assert analyzer.detect_content_type(content) == "code"


def test_detect_content_type_article(analyzer):
    """Test detection of article-type content."""
    content = (
        "# Heading\n" + "word " * 1001 + "\n## Heading2\n### Heading3\n#### Heading4"
    )
    assert analyzer.detect_content_type(content) == "article"


def test_detect_content_type_list(analyzer):
    """Test detection of list-heavy content."""
    content = "\n".join([f"- item {i}" for i in range(15)])
    assert analyzer.detect_content_type(content) == "list"


def test_detect_content_type_reference(analyzer):
    """Test detection of reference-type content."""
    content = "\n".join([f"[[link{i}]]" for i in range(10)])
    assert analyzer.detect_content_type(content) == "reference"


def test_detect_content_type_note(analyzer):
    """Test detection of generic note content."""
    content = "Just a simple note with some text."
    assert analyzer.detect_content_type(content) == "note"


def test_detect_content_type_priority(analyzer):
    """Test that type detection follows priority order."""
    # Code type has highest priority (>3 code blocks)
    content = (
        "```\ncode1\n```\n```\ncode2\n```\n```\ncode3\n```\n```\ncode4\n```\n"
        + "word " * 1500
    )
    assert analyzer.detect_content_type(content) == "code"


# ============================================================================
# _clean_content tests
# ============================================================================


def test_clean_content_removes_code_blocks(analyzer):
    """Test that code blocks are removed during cleaning."""
    content = "text ```python\ncode here\n``` more text"
    cleaned = analyzer._clean_content(content)
    assert "code here" not in cleaned
    assert "text" in cleaned
    assert "more text" in cleaned


def test_clean_content_removes_inline_code(analyzer):
    """Test that inline code is removed during cleaning."""
    content = "text `inline code` more text"
    cleaned = analyzer._clean_content(content)
    assert "inline code" not in cleaned
    assert "text" in cleaned


def test_clean_content_removes_urls(analyzer):
    """Test that URLs are removed during cleaning."""
    content = "text https://example.com more text"
    cleaned = analyzer._clean_content(content)
    assert "example.com" not in cleaned
    assert "text" in cleaned


# ============================================================================
# get_semantic_keywords tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_semantic_keywords_no_adapter(analyzer):
    """Test semantic keywords falls back to frequency when no adapter."""
    content = "Python programming Python development Python"
    keywords = await analyzer.get_semantic_keywords(content, top_k=5)
    assert len(keywords) > 0
    assert isinstance(keywords[0], tuple)
    assert isinstance(keywords[0][0], str)
    assert isinstance(keywords[0][1], float)


@pytest.mark.asyncio
async def test_get_semantic_keywords_with_adapter_no_tags(analyzer_with_embeddings):
    """Test semantic keywords with adapter but no existing tags."""
    content = "Python programming Python development Python testing Python"
    keywords = await analyzer_with_embeddings.get_semantic_keywords(content, top_k=5)
    # Should fall back to frequency-based since no tags in graph
    assert len(keywords) > 0
    assert isinstance(keywords[0], tuple)
    assert isinstance(keywords[0][0], str)
    assert isinstance(keywords[0][1], float)


@pytest.mark.skip(
    reason="Requires async embedding adapter support (embed_async method)"
)
@pytest.mark.asyncio
async def test_get_semantic_keywords_with_adapter_and_tags(analyzer_with_embeddings):
    """Test semantic keywords with adapter and existing tags in graph."""
    # Add a memory with tags to the kernel
    analyzer_with_embeddings.kernel.remember(
        title="Python Programming Tutorial",
        content="A comprehensive guide to Python programming",
        tags=["python", "programming", "tutorial"],
    )
    analyzer_with_embeddings.kernel.ingest()

    content = "Learning Python programming basics for beginners"
    keywords = await analyzer_with_embeddings.get_semantic_keywords(content, top_k=3)
    assert len(keywords) > 0
    # Should return semantic similarity scores
    assert all(isinstance(score, float) for _, score in keywords)
    assert all(0 <= score <= 1 for _, score in keywords)


# ============================================================================
# _cosine_similarity tests
# ============================================================================


def test_cosine_similarity_identical_vectors(analyzer):
    """Test cosine similarity of identical vectors is 1.0."""
    vec = [1.0, 2.0, 3.0]
    similarity = analyzer._cosine_similarity(vec, vec)
    assert abs(similarity - 1.0) < 0.0001


def test_cosine_similarity_orthogonal_vectors(analyzer):
    """Test cosine similarity of orthogonal vectors is ~0."""
    vec1 = [1.0, 0.0]
    vec2 = [0.0, 1.0]
    similarity = analyzer._cosine_similarity(vec1, vec2)
    assert abs(similarity) < 0.0001


def test_cosine_similarity_opposite_vectors(analyzer):
    """Test cosine similarity of opposite vectors is -1.0."""
    vec1 = [1.0, 2.0, 3.0]
    vec2 = [-1.0, -2.0, -3.0]
    similarity = analyzer._cosine_similarity(vec1, vec2)
    assert abs(similarity - (-1.0)) < 0.0001


def test_cosine_similarity_zero_vectors(analyzer):
    """Test cosine similarity with zero vectors returns 0."""
    vec1 = [0.0, 0.0, 0.0]
    vec2 = [1.0, 2.0, 3.0]
    similarity = analyzer._cosine_similarity(vec1, vec2)
    assert similarity == 0.0


def test_cosine_similarity_partial_similarity(analyzer):
    """Test cosine similarity with partially similar vectors."""
    vec1 = [1.0, 1.0, 0.0]
    vec2 = [1.0, 0.0, 0.0]
    similarity = analyzer._cosine_similarity(vec1, vec2)
    # Should be positive but less than 1
    assert 0 < similarity < 1


# ============================================================================
# Integration tests
# ============================================================================


def test_analyzer_workflow(analyzer):
    """Test complete analysis workflow."""
    content = """---
title: Python Guide
---

# Python Programming
A comprehensive guide to #python programming.

## Topics
- Variables and data types
- Functions and classes
- File I/O operations

```python
def hello():
    print("Hello, World!")
```

See also: [[advanced-python]] and [[python-best-practices]]
"""

    # Extract keywords
    keywords = analyzer.extract_keywords(content, max_keywords=10)
    assert len(keywords) > 0

    # Extract tags
    tags = analyzer.extract_existing_tags(content)
    assert "python" in tags

    # Analyze structure
    structure = analyzer.analyze_structure(content)
    assert structure["heading_count"] == 2
    assert structure["list_count"] == 3
    assert structure["code_block_count"] == 1
    assert structure["link_count"] == 2
    assert structure["has_frontmatter"] is True

    # Detect content type
    content_type = analyzer.detect_content_type(content)
    assert content_type in ["code", "article", "list", "reference", "note"]


def test_stop_words_are_loaded(analyzer):
    """Test that stop words are properly loaded."""
    assert len(analyzer._stop_words) > 0
    assert "the" in analyzer._stop_words
    assert "and" in analyzer._stop_words


def test_tag_patterns_compiled(analyzer):
    """Test that regex patterns are compiled."""
    assert "hashtag" in analyzer._tag_patterns
    assert "code_block" in analyzer._tag_patterns
    assert "inline_code" in analyzer._tag_patterns
    assert "url" in analyzer._tag_patterns
    assert "wikilink" in analyzer._tag_patterns
