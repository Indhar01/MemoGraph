## Architecture Overview

Mnemo-Vault is built around a graph-based knowledge representation with hybrid retrieval capabilities.

### Core Components

#### 1. Memory Kernel (`mnemo/core/kernel.py`)

The central orchestrator that provides the main API:
- `ingest()`: Index markdown files from the vault
- `remember()`: Create new memories programmatically
- `context_window()`: Retrieve and compress relevant context
- `retrieve_nodes()`: Get raw memory nodes for a query

#### 2. Graph (`memograph/core/graph.py`)

Maintains the knowledge graph structure:
- **Nodes**: Individual memories (MemoryNode objects)
- **Edges**: Wikilinks `[[target]]` create directed edges
- **Backlinks**: Automatically computed reverse edges
- **BFS Traversal**: Navigate relationships up to specified depth

#### 3. Retriever (`memograph/core/retriever.py`)

Hybrid retrieval strategy combining:
1. **Keyword Matching**: Simple word-based seed selection
2. **Graph Traversal**: BFS expansion from seed nodes
3. **Metadata Filtering**: Tag, type, and salience filters
4. **Vector Similarity** (optional): Re-ranking with embeddings

#### 4. Indexer (`memograph/core/indexer.py`)

Efficiently indexes markdown files:
- **Caching**: Only re-index modified files (based on mtime)
- **Incremental**: Fast subsequent ingestions
- **Cache File**: `.memograph_cache.json` stores modification times

#### 5. Parser (`memograph/core/parser.py`)

Extracts structured data from markdown:
- **YAML Frontmatter**: Metadata (title, type, salience, etc.)
- **Wikilinks**: `[[page-name]]` for connections
- **Tags**: `#tag` syntax in content
- **Content**: The actual markdown body

### Data Flow

```
┌─────────────────┐
│  Markdown Files │
│   (Vault Dir)   │
└────────┬────────┘
         │
         v
┌─────────────────┐
│     Parser      │
│  (frontmatter,  │
│  links, tags)   │
└────────┬────────┘
         │
         v
┌─────────────────┐
│     Indexer     │
│   (caching,     │
│   mtime check)  │
└────────┬────────┘
         │
         v
┌─────────────────┐
│   VaultGraph    │
│  (nodes, edges, │
│   backlinks)    │
└────────┬────────┘
         │
         v
┌─────────────────┐
│    Retriever    │
│  (hybrid search,│
│   BFS, filters) │
└────────┬────────┘
         │
         v
┌─────────────────┐
│   Compressor    │
│ (token budget,  │
│   truncation)   │
└────────┬────────┘
         │
         v
┌─────────────────┐
│  Context Window │
│  (LLM-ready)    │
└─────────────────┘
```

### Memory Node Structure

```python
@dataclass
class MemoryNode:
    id: str                  # File path slug
    title: str               # From frontmatter or filename
    content: str             # Markdown body
    memory_type: MemoryType  # episodic, semantic, procedural, fact
    
    # Graph relationships
    links: list[str]         # Outgoing wikilinks
    backlinks: list[str]     # Incoming links (computed)
    tags: list[str]          # Tags from content
    
    # Metadata
    salience: float          # Importance score (0.0-1.0)
    access_count: int        # Usage tracking
    last_accessed: datetime
    created_at: datetime
    modified_at: datetime
    
    # Optional
    embedding: list[float]   # Vector representation
```

### Retrieval Algorithm

1. **Seed Selection**: Find nodes matching query keywords
2. **Graph Expansion**: BFS traversal to depth `d`
3. **Filter Application**: Apply tag, type, salience filters
4. **Re-ranking** (optional): Score by vector similarity
5. **Top-K Selection**: Return best matches
6. **Compression**: Fit within token budget

### Extension Points

- **Embedding Adapters**: `memograph/adapters/embeddings/`
  - OpenAI, Ollama, custom implementations

- **LLM Adapters**: `memograph/adapters/llm/`
  - Claude, Ollama, extensible interface

- **Framework Integrations**: `memograph/adapters/frameworks/`
  - LangChain, LlamaIndex

### Design Decisions

#### Why Markdown + Frontmatter?
- Human-readable and editable
- Works with existing tools (Obsidian, Logseq, etc.)
- Git-friendly for version control
- Simple, no database required

#### Why BFS for Graph Traversal?
- Finds nearby memories efficiently
- Controllable depth prevents explosion
- Natural for "related concepts" discovery
- Better than DFS for knowledge graphs

#### Why Hybrid Retrieval?
- Keywords: Fast, simple, interpretable
- Graph: Captures relationships
- Vectors: Semantic understanding
- Combined: Robust across query types

### Performance Considerations

- **Caching**: Avoid re-parsing unchanged files
- **Lazy Loading**: Don't load full graph until needed
- **Incremental Indexing**: Only update what changed
- **Token Compression**: Character-based estimation

### Future Improvements

1. **Persistent Embeddings**: Cache vectors to disk
2. **Incremental Graph Updates**: Don't rebuild entire graph
3. **Advanced Compression**: Extractive summarization
4. **Memory Reinforcement**: Update salience on access
5. **Temporal Decay**: Implement forgetting curves
6. **Multi-vault**: Support multiple knowledge bases
7. **Conflict Resolution**: Handle concurrent edits