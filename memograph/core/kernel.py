import asyncio
import logging
import os
import re
import threading
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from .compressor import TokenCompressor
from .enums import MemoryType
from .extractor import SmartAutoOrganizer
from .gam_retriever import GAMRetriever
from .gam_scorer import GAMConfig
from .graph import VaultGraph
from .indexer import VaultIndexer
from .node import MemoryNode
from .retriever import HybridRetriever
from .validation import (
    validate_depth,
    validate_query,
    validate_salience,
    validate_tags,
    validate_top_k,
)

# Initialize logger for MemoGraph
logger = logging.getLogger("memograph")


@dataclass
class SearchOptions:
    """
    Advanced search configuration options.

    This dataclass provides fine-grained control over search behavior,
    including search strategies, result filtering, and scoring weights.

    Attributes:
        strategy: Search strategy to use. Options:
            - "keyword": Pure keyword/BM25 search
            - "semantic": Pure embedding-based semantic search
            - "hybrid": Combined keyword + semantic (default)
            - "graph": Graph traversal based on wikilinks
        include_backlinks: Whether to include nodes that link to results.
        min_salience: Minimum salience threshold (0.0-1.0).
        max_results: Maximum number of results to return.
        depth: Graph traversal depth for connected nodes.
        boost_recent: Apply recency boost to scoring.
        time_decay_factor: Exponential decay factor for recency boost.
            Higher values = stronger recency preference.
        weights: Scoring weights for different strategies.
            Example: {"keyword": 0.3, "semantic": 0.7}

    Example:
        >>> opts = SearchOptions(
        ...     strategy="hybrid",
        ...     min_salience=0.7,
        ...     boost_recent=True,
        ...     weights={"keyword": 0.3, "semantic": 0.7}
        ... )
        >>> results = kernel.search("python tips", options=opts)
    """

    strategy: Literal["keyword", "semantic", "hybrid", "graph"] = "hybrid"
    include_backlinks: bool = True
    min_salience: float = 0.0
    max_results: int = 10
    depth: int = 2
    boost_recent: bool = False
    time_decay_factor: float | None = None
    weights: dict[str, float] | None = field(
        default_factory=lambda: {"keyword": 0.4, "semantic": 0.6}
    )


class MemoryQuery:
    """
    Fluent query builder for constructing complex memory searches.

    This class implements the builder pattern to make complex queries more
    readable and maintainable. Each method returns self for method chaining.

    Example:
        >>> kernel = MemoryKernel(vault_path="./vault")
        >>> results = (
        ...     kernel.query()
        ...         .search("python tips")
        ...         .with_tags(["programming", "ai"])
        ...         .memory_type(MemoryType.SEMANTIC)
        ...         .min_salience(0.7)
        ...         .depth(3)
        ...         .limit(10)
        ...         .execute()
        ... )
    """

    def __init__(self, kernel: "MemoryKernel"):
        """Initialize the query builder with a reference to the kernel."""
        self.kernel = kernel
        self._query: str | None = None
        self._tags: list[str] | None = None
        self._memory_type: MemoryType | None = None
        self._min_salience: float = 0.0
        self._depth: int = 2
        self._top_k: int = 8

    def search(self, query: str) -> "MemoryQuery":
        """
        Set the search query string.

        Args:
            query: Search query for keyword and semantic matching.

        Returns:
            Self for method chaining.
        """
        self._query = query
        return self

    def with_tags(self, tags: list[str]) -> "MemoryQuery":
        """
        Filter results by tags.

        Args:
            tags: List of tags to filter by.

        Returns:
            Self for method chaining.
        """
        self._tags = tags
        return self

    def memory_type(self, mem_type: MemoryType) -> "MemoryQuery":
        """
        Filter by memory type.

        Args:
            mem_type: MemoryType to filter by.

        Returns:
            Self for method chaining.
        """
        self._memory_type = mem_type
        return self

    def min_salience(self, salience: float) -> "MemoryQuery":
        """
        Set minimum salience threshold.

        Args:
            salience: Minimum salience value (0.0-1.0).

        Returns:
            Self for method chaining.
        """
        self._min_salience = salience
        return self

    def depth(self, depth: int) -> "MemoryQuery":
        """
        Set graph traversal depth.

        Args:
            depth: Number of hops through wikilinks to explore.

        Returns:
            Self for method chaining.
        """
        self._depth = depth
        return self

    def limit(self, top_k: int) -> "MemoryQuery":
        """
        Set maximum number of results.

        Args:
            top_k: Maximum number of nodes to return.

        Returns:
            Self for method chaining.
        """
        self._top_k = top_k
        return self

    def execute(self) -> list[MemoryNode]:
        """
        Execute the query and return results.

        Returns:
            List of MemoryNode objects matching the query criteria.

        Raises:
            ValueError: If no search query was provided.
        """
        if not self._query:
            raise ValueError(
                "Search query is required. Use .search('query string') first."
            )

        # Retrieve nodes using the kernel
        results: list[MemoryNode] = self.kernel.retrieve_nodes(
            query=self._query,
            tags=self._tags,
            depth=self._depth,
            top_k=self._top_k,
        )

        # Apply additional filters
        if self._memory_type:
            results = [n for n in results if n.memory_type == self._memory_type]

        if self._min_salience > 0.0:
            results = [n for n in results if n.salience >= self._min_salience]

        logger.debug(
            f"Query executed: {len(results)} results after filters "
            f"(type={self._memory_type}, min_salience={self._min_salience})"
        )

        return results

    async def execute_async(self) -> list[MemoryNode]:
        """
        Async version of execute() for FastAPI and async frameworks.

        Returns:
            List of MemoryNode objects matching the query criteria.
        """
        if not self._query:
            raise ValueError(
                "Search query is required. Use .search('query string') first."
            )

        # Use async retrieve
        results = await self.kernel.retrieve_nodes_async(
            query=self._query,
            tags=self._tags,
            depth=self._depth,
            top_k=self._top_k,
        )

        # Apply additional filters
        if self._memory_type:
            results = [n for n in results if n.memory_type == self._memory_type]

        if self._min_salience > 0.0:
            results = [n for n in results if n.salience >= self._min_salience]

        return results


class MemoryKernel:
    def __init__(
        self,
        vault_path: str,
        embedding_adapter: Any | None = None,
        llm_client: Any | None = None,
        llm_config: dict[str, Any] | None = None,
        auto_extract: bool = False,
        use_gam: bool = False,
        gam_config: GAMConfig | None = None,
        enable_cache: bool = False,
        cache_dir: str | None = None,
        validate_inputs: bool = False,
        max_concurrent: int = 10,
        memory_cache_size: int = 1000,
        memory_cache_mb: int = 512,
        enable_disk_cache: bool = True,
        query_cache_ttl: int = 300,
        query_cache_size: int = 100,
    ) -> None:
        """
        Initialize the memory kernel.

        Args:
            vault_path: Path to the vault directory. Will be created if it doesn't exist.
            embedding_adapter: Optional embedding adapter for semantic search.
            llm_client: Optional LLM client for auto-extraction of entities.
            llm_config: Optional configuration dictionary for the LLM.
            auto_extract: Whether to automatically extract entities during ingestion.
            use_gam: Enable Graph Attention Memory (GAM) scoring for enhanced retrieval.
            gam_config: Optional GAM configuration for custom scoring weights.
            enable_cache: Enable embedding and query result caching.
            cache_dir: Directory for cache files (default: vault_path/.cache).
            validate_inputs: Enable input validation with helpful error messages.
            max_concurrent: Maximum concurrent async operations (semaphore limit).
            memory_cache_size: Max items in memory cache (when caching enabled).
            memory_cache_mb: Max memory usage in MB for cache.
            enable_disk_cache: Whether to enable disk-based caching.
            query_cache_ttl: Query cache TTL in seconds.
            query_cache_size: Max queries to cache.
        """
        self.vault_path = Path(vault_path).expanduser()
        self.vault_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initializing MemoGraph kernel at: {self.vault_path}")

        self.graph = VaultGraph()
        self.embedding_adapter = embedding_adapter
        self.indexer = VaultIndexer(
            self.vault_path, embedding_adapter=embedding_adapter
        )

        # Initialize retriever based on GAM setting
        self.use_gam = use_gam
        self.enable_gam = use_gam  # Backwards-compat alias
        self.gam_config = gam_config

        # Declare retriever type (GAMRetriever is a subclass of HybridRetriever)
        self.retriever: HybridRetriever

        if use_gam:
            self.retriever = GAMRetriever(
                self.graph,
                embedding_adapter=embedding_adapter,
                use_gam=True,
                gam_config=gam_config,
            )
            logger.info("GAM-enhanced retrieval enabled")
        else:
            self.retriever = HybridRetriever(
                self.graph, embedding_adapter=embedding_adapter
            )
            logger.info("Standard hybrid retrieval enabled")

        # Auto-extraction setup
        self.auto_extract = auto_extract
        self.llm_client = llm_client
        self.llm_config = llm_config
        self.organizer = None
        if auto_extract and llm_client:
            self.organizer = SmartAutoOrganizer(llm_client, llm_config)
            logger.info("Auto-extraction enabled with LLM client")

        # Validation setting
        self.validate_inputs = validate_inputs

        # Concurrency control for async operations
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

        # Caching setup
        self.embedding_cache = None
        self.query_cache = None

        if enable_cache:
            from memograph.storage.cache_enhanced import (
                MultiLevelCache,
                QueryResultCache,
            )

            cache_dir_path = (
                Path(vault_path) / ".cache" if cache_dir is None else Path(cache_dir)
            )

            self.embedding_cache = MultiLevelCache(
                cache_dir=cache_dir_path / "embeddings",
                memory_max_size=memory_cache_size,
                memory_max_mb=memory_cache_mb,
                enable_disk_cache=enable_disk_cache,
            )
            self.query_cache = QueryResultCache(
                ttl_seconds=query_cache_ttl, max_size=query_cache_size
            )
            logger.info(
                f"Caching enabled: memory={memory_cache_size} items, "
                f"disk={'yes' if enable_disk_cache else 'no'}, "
                f"query_ttl={query_cache_ttl}s"
            )

        # Ingest failure tracking (Fix #4)
        self._last_ingest_error: Exception | None = None
        self._ingest_attempt_count = 0
        self._max_auto_ingest_attempts = 3

        # Thread safety for graph operations (Fix #5)
        self._graph_lock = threading.RLock()
        self._graph_version = 0

        logger.info("MemoGraph kernel initialized successfully")

    @classmethod
    def from_config(cls, config_path: str) -> "MemoryKernel":
        """
        Create a MemoryKernel instance from a TOML configuration file.

        This method reads configuration from a TOML file and initializes
        the kernel with the specified settings.

        Args:
            config_path: Path to the TOML configuration file.

        Returns:
            Configured MemoryKernel instance.

        Raises:
            FileNotFoundError: If the config file doesn't exist.
            ImportError: If TOML library is not available.
            KeyError: If required configuration keys are missing.

        Example:
            >>> # Create memograph.toml:
            >>> # [memograph]
            >>> # vault_path = "./data/vault"
            >>> # auto_extract = false
            >>> #
            >>> # [search]
            >>> # default_depth = 3
            >>> # default_top_k = 10
            >>>
            >>> kernel = MemoryKernel.from_config("memograph.toml")

        Note:
            Requires Python 3.11+ (tomllib) or install: pip install tomli
        """
        import sys

        # Try to import TOML library
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomli as tomllib
            except ImportError as err:
                raise ImportError(
                    "TOML support requires Python 3.11+ or 'tomli' package. "
                    "Install with: pip install tomli"
                ) from err

        # Read config file
        config_path_obj = Path(config_path)
        if not config_path_obj.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path_obj}")

        with open(config_path_obj, "rb") as f:
            config = tomllib.load(f)

        # Extract memograph section
        memograph_config = config.get("memograph", {})

        # Required parameter
        vault_path = memograph_config.get("vault_path")
        if not vault_path:
            raise KeyError(
                "Configuration must include 'vault_path' in [memograph] section"
            )

        # Optional parameters
        auto_extract = memograph_config.get("auto_extract", False)

        logger.info(f"Loaded configuration from: {config_path}")

        # Create and return kernel
        return cls(
            vault_path=vault_path,
            embedding_adapter=None,  # Would need to be configured separately
            llm_client=None,  # Would need to be configured separately
            llm_config=None,
            auto_extract=auto_extract,
        )

    @classmethod
    def from_env(
        cls,
        vault_path_env: str = "MEMOGRAPH_VAULT_PATH",
        auto_extract_env: str = "MEMOGRAPH_AUTO_EXTRACT",
        prefix: str = "MEMOGRAPH_",
    ) -> "MemoryKernel":
        """
        Create a MemoryKernel instance from environment variables.

        This method reads configuration from environment variables,
        useful for containerized deployments and CI/CD pipelines.

        Args:
            vault_path_env: Environment variable name for vault_path.
                Default: "MEMOGRAPH_VAULT_PATH"
            auto_extract_env: Environment variable name for auto_extract.
                Default: "MEMOGRAPH_AUTO_EXTRACT"
            prefix: Common prefix for environment variables.
                Default: "MEMOGRAPH_"

        Returns:
            Configured MemoryKernel instance.

        Raises:
            ValueError: If required environment variables are not set.

        Example:
            >>> # Set environment variables:
            >>> # export MEMOGRAPH_VAULT_PATH="./data/vault"
            >>> # export MEMOGRAPH_AUTO_EXTRACT="false"
            >>>
            >>> kernel = MemoryKernel.from_env()
            >>>
            >>> # Or with custom variable names:
            >>> kernel = MemoryKernel.from_env(
            ...     vault_path_env="MY_VAULT_PATH",
            ...     auto_extract_env="MY_AUTO_EXTRACT"
            ... )
        """
        # Get vault_path (required)
        vault_path = os.getenv(vault_path_env)
        if not vault_path:
            raise ValueError(
                f"Environment variable '{vault_path_env}' is required but not set. "
                f"Set it with: export {vault_path_env}='./path/to/vault'"
            )

        # Get auto_extract (optional, default False)
        auto_extract_str = os.getenv(auto_extract_env, "false").lower()
        auto_extract = auto_extract_str in ("true", "1", "yes", "on")

        logger.info(
            f"Loaded configuration from environment variables (prefix: {prefix})"
        )
        logger.info(f"  {vault_path_env}={vault_path}")
        logger.info(f"  {auto_extract_env}={auto_extract}")

        # Create and return kernel
        return cls(
            vault_path=vault_path,
            embedding_adapter=None,
            llm_client=None,
            llm_config=None,
            auto_extract=auto_extract,
        )

    @staticmethod
    def _normalize_tags(tags: list[str] | None) -> list[str]:
        """Normalize tags by removing '#' prefix and trimming whitespace."""
        if not tags:
            return []
        normalized = []
        for tag in tags:
            clean = tag.strip().lstrip("#")
            if clean:
                normalized.append(clean)
        return normalized

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to a URL-safe slug."""
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
        return slug or datetime.now(timezone.utc).strftime("memory-%Y%m%d-%H%M%S")

    @staticmethod
    def _atomic_write(file_path: Path, content: str) -> None:
        """Write file atomically using temp file + rename to prevent corruption.

        Args:
            file_path: Target file path to write to
            content: Content to write

        Raises:
            OSError: If write or rename fails
        """
        temp_path = file_path.with_suffix(".tmp")
        try:
            temp_path.write_text(content, encoding="utf-8")
            temp_path.replace(file_path)  # Atomic on POSIX and Windows
        except Exception:
            # Clean up temp file on failure (best effort)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass  # Best effort cleanup
            raise

    def ingest(
        self, force: bool = False, auto_extract: bool | None = None
    ) -> dict[str, int]:
        """
        Ingest all markdown memories from the vault directory into the knowledge graph.

        This method scans the vault directory, parses markdown files with YAML frontmatter,
        extracts wikilinks, builds the graph structure, and optionally extracts entities
        using an LLM if auto-extraction is enabled.

        Args:
            force: Force re-indexing of all files, even if they haven't changed since
                the last ingestion. Useful for rebuilding the graph or updating
                embeddings. Default: False
            auto_extract: Override the default auto_extract setting for this specific
                ingestion. If None, uses the kernel's auto_extract setting.
                Default: None

        Returns:
            Dictionary with ingestion statistics:
                - indexed (int): Number of files newly indexed or re-indexed
                - skipped (int): Number of files skipped (unchanged since last ingest)
                - total (int): Total number of memories in the graph
                - entities_extracted (int): Number of entities extracted (if enabled)

        Example:
            >>> kernel = MemoryKernel(vault_path="./vault")
            >>> # Initial ingestion
            >>> stats = kernel.ingest()
            >>> print(f"Indexed {stats['indexed']} memories")
            >>>
            >>> # Force re-index everything
            >>> stats = kernel.ingest(force=True)
            >>>
            >>> # Enable extraction for this ingestion only
            >>> stats = kernel.ingest(auto_extract=True)
            >>> print(f"Extracted {stats['entities_extracted']} entities")
        """
        # Thread-safe graph rebuild (Fix #5)
        with self._graph_lock:
            try:
                logger.info(
                    f"Acquiring graph lock for ingest (version: {self._graph_version})"
                )
                logger.info(f"Starting ingestion from vault: {self.vault_path}")

                # Rebuild graph from scratch
                self.graph = VaultGraph()
                indexed, skipped = self.indexer.index(self.graph, force=force)

                # Recreate retriever with same configuration
                if self.use_gam:
                    self.retriever = GAMRetriever(
                        self.graph,
                        embedding_adapter=self.retriever.embeddings,
                        use_gam=True,
                        gam_config=self.gam_config,
                        access_tracker=getattr(
                            self.retriever, "access_tracker", None
                        ),  # Preserve tracker
                    )
                else:
                    self.retriever = HybridRetriever(
                        self.graph, embedding_adapter=self.retriever.embeddings
                    )

                logger.info(
                    f"Indexed {indexed} files, skipped {skipped} unchanged files"
                )

                # Perform auto-extraction if enabled
                extract_enabled = (
                    auto_extract if auto_extract is not None else self.auto_extract
                )
                entities_extracted = 0

                if extract_enabled and self.organizer:
                    logger.info("Starting entity extraction from memories")
                    entities_extracted = self._extract_entities_from_memories()
                    logger.info(f"Extracted {entities_extracted} total entities")

                total = len(self.graph._nodes)

                self._graph_version += 1
                logger.info(f"Graph rebuilt (version: {self._graph_version})")
                logger.info(f"Ingestion complete: {total} total memories in graph")

                # Clear error state on success (Fix #4)
                self._last_ingest_error = None
                self._ingest_attempt_count = 0

                return {
                    "indexed": indexed,
                    "skipped": skipped,
                    "total": total,
                    "entities_extracted": entities_extracted,
                }

            except Exception as e:
                # Track failure (Fix #4)
                self._last_ingest_error = e
                self._ingest_attempt_count += 1
                logger.error(
                    f"Ingest failed (attempt {self._ingest_attempt_count}): {e}",
                    exc_info=True,
                )
                raise

    def _extract_entities_from_memories(self) -> int:
        """
        Extract entities from all memories in the graph.

        Returns:
            Number of entities extracted
        """
        total_entities = 0
        for memory in self.graph.all_nodes():
            try:
                if self.organizer is None:
                    continue
                result = self.organizer.extract(memory)
                self.graph.add_extraction_result(result)
                total_entities += result.entity_count()
                logger.debug(
                    f"Extracted {result.entity_count()} entities from {memory.id}"
                )
            except Exception as e:
                logger.warning(f"Failed to extract from {memory.id}: {e}")

        return total_entities

    def extract_from_memory(self, memory_id: str) -> dict[str, Any]:
        """
        Manually extract entities from a specific memory using LLM.

        This method performs on-demand entity extraction from a single memory,
        useful for extracting from newly created memories or re-extracting
        after content updates.

        Args:
            memory_id: ID (slug) of the memory to extract from.

        Returns:
            Dictionary with extraction results containing:
                - memory_id (str): The memory ID processed
                - entities_extracted (int): Total number of entities extracted
                - topics (int): Number of topics found
                - people (int): Number of people/entities mentioned
                - action_items (int): Number of action items identified
                - decisions (int): Number of decisions recorded
                - questions (int): Number of questions raised
                - risks (int): Number of risks identified

        Raises:
            RuntimeError: If auto-extraction is not enabled (no LLM client provided).
            ValueError: If the memory_id is not found in the graph.

        Example:
            >>> kernel = MemoryKernel(
            ...     vault_path="./vault",
            ...     llm_client=my_llm,
            ...     auto_extract=True
            ... )
            >>> kernel.ingest()
            >>> result = kernel.extract_from_memory("meeting-notes-2024")
            >>> print(f"Found {result['action_items']} action items")
        """
        if not self.organizer:
            raise RuntimeError(
                "Auto-extraction not enabled. "
                "Initialize kernel with llm_client and auto_extract=True"
            )

        memory = self.graph.get(memory_id)
        if not memory:
            raise ValueError(f"Memory '{memory_id}' not found in graph")

        logger.info(f"Extracting entities from memory: {memory_id}")

        result = self.organizer.extract(memory)
        self.graph.add_extraction_result(result)

        logger.debug(f"Extracted {result.entity_count()} entities from {memory_id}")

        return {
            "memory_id": memory_id,
            "entities_extracted": result.entity_count(),
            "topics": len(result.topics),
            "people": len(result.people),
            "action_items": len(result.action_items),
            "decisions": len(result.decisions),
            "questions": len(result.questions),
            "risks": len(result.risks),
        }

    def get_entities(
        self, memory_id: str | None = None, entity_type: Any | None = None
    ) -> list[Any]:
        """
        Get extracted entities, optionally filtered by memory or type.

        Args:
            memory_id: Optional memory ID to filter entities by. If provided,
                only returns entities extracted from that specific memory.
            entity_type: Optional EntityType to filter by. If provided, only
                returns entities of that specific type (e.g., TOPIC, PERSON,
                ACTION_ITEM, etc.).

        Returns:
            List of entity objects matching the specified filters.

        Example:
            >>> kernel = MemoryKernel(
            ...     vault_path="./vault",
            ...     llm_client=my_llm,
            ...     auto_extract=True
            ... )
            >>> kernel.ingest(auto_extract=True)
            >>>
            >>> # Get all entities
            >>> all_entities = kernel.get_entities()
            >>>
            >>> # Get entities from specific memory
            >>> entities = kernel.get_entities(memory_id="meeting-notes-2024")
            >>>
            >>> # Get entities of specific type
            >>> from memograph.core.entity import EntityType
            >>> action_items = kernel.get_entities(entity_type=EntityType.ACTION_ITEM)
        """
        if memory_id:
            entities = self.graph.get_entities_for_memory(memory_id)
            logger.debug(f"Retrieved {len(entities)} entities from memory: {memory_id}")
        else:
            entities = self.graph.all_entities()
            logger.debug(f"Retrieved {len(entities)} total entities")

        if entity_type:
            entities = [e for e in entities if e.entity_type == entity_type]
            logger.debug(f"Filtered to {len(entities)} entities of type: {entity_type}")

        return entities

    def remember(
        self,
        title: str,
        content: str,
        memory_type: MemoryType = MemoryType.FACT,
        tags: list[str] | None = None,
        salience: float = 0.5,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """
        Create and store a new memory in the knowledge graph.

        This method creates a new memory as a markdown file with YAML frontmatter,
        automatically handling filename collisions and wikilink parsing for
        bidirectional connections.

        Args:
            title: Memory title. Must be non-empty.
            content: Memory content. Supports [[wikilinks]] for automatic connections
                to other memories. Must be non-empty.
            memory_type: Type classification for the memory. Options:
                - MemoryType.EPISODIC: Personal experiences and events
                - MemoryType.SEMANTIC: Facts and general knowledge
                - MemoryType.PROCEDURAL: How-to knowledge and procedures
                - MemoryType.FACT: Atomic facts and statements
                Default: MemoryType.FACT
            tags: Optional list of tags for categorization. Tags can include '#' prefix
                which will be automatically normalized.
            salience: Importance score from 0.0 (least important) to 1.0 (most important).
                Used for ranking and retrieval. Default: 0.5
            meta: Optional arbitrary metadata dictionary to store with the memory.

        Returns:
            Path to the created memory file as a string.

        Raises:
            ValueError: If title or content is empty or if salience is out of range.
            TypeError: If parameters have incorrect types.

        Example:
            >>> kernel = MemoryKernel(vault_path="./vault")
            >>> # Basic memory
            >>> path = kernel.remember(
            ...     title="Python Tips",
            ...     content="Always use list comprehensions when possible"
            ... )
            >>>
            >>> # Memory with wikilinks and metadata
            >>> path = kernel.remember(
            ...     title="FastAPI Best Practices",
            ...     content="Use [[dependency injection]] for [[database connections]]",
            ...     memory_type=MemoryType.PROCEDURAL,
            ...     tags=["programming", "python", "web"],
            ...     salience=0.8,
            ...     meta={"project": "api-backend", "author": "team"}
            ... )
            >>> print(f"Created: {path}")
            Created: ./vault/fastapi-best-practices.md
        """
        # Validate title
        if not title or not isinstance(title, str):
            raise TypeError(
                f"title must be a non-empty string, got {type(title).__name__}"
            )

        if not title.strip():
            raise ValueError(
                "title cannot be empty. Provide a non-empty string for the memory title."
            )

        # Validate content
        if not content or not isinstance(content, str):
            raise TypeError(
                f"content must be a non-empty string, got {type(content).__name__}"
            )

        if not content.strip():
            raise ValueError(
                "content cannot be empty. Provide memory content (supports [[wikilinks]])."
            )

        # Validate salience
        if not isinstance(salience, int | float):
            raise TypeError(f"salience must be a number, got {type(salience).__name__}")

        if not 0.0 <= salience <= 1.0:
            raise ValueError(f"salience must be between 0.0 and 1.0, got {salience}")

        # Validate memory_type
        if not isinstance(memory_type, MemoryType):
            raise TypeError(
                f"memory_type must be a MemoryType enum, got {type(memory_type).__name__}"
            )

        # Validate tags and salience with enhanced validation if enabled
        if self.validate_inputs:
            if tags:
                tags = validate_tags(tags)
            salience = validate_salience(salience)

        # Process tags
        normalized_tags = self._normalize_tags(tags)

        # Generate slug and handle collisions
        slug = self._slugify(title)
        file_path = self.vault_path / f"{slug}.md"

        counter = 2
        while file_path.exists():
            file_path = self.vault_path / f"{slug}-{counter}.md"
            counter += 1

        # Create frontmatter
        created_at = datetime.now(timezone.utc).isoformat()
        tags_line = " ".join(f"#{tag}" for tag in normalized_tags)

        payload = {
            "title": title,
            "memory_type": memory_type.value,
            "created": created_at,
            "salience": salience,
        }

        # Add meta to frontmatter if provided
        if meta:
            payload["meta"] = meta  # type: ignore[assignment]

        frontmatter = (
            "---\n" + yaml.safe_dump(payload, sort_keys=False).strip() + "\n---\n\n"
        )

        # Create body with tags
        body = content.strip()
        if tags_line:
            body = f"{body}\n\n{tags_line}"

        # Write file with disk space handling (Fix #7)
        try:
            file_path.write_text(frontmatter + body + "\n", encoding="utf-8")
        except OSError as e:
            # Handle disk full, permission errors, etc.
            if file_path.exists():
                # Clean up partial write
                try:
                    file_path.unlink()
                except Exception:
                    pass  # Best effort cleanup

            if e.errno == 28 or "No space left" in str(e):  # ENOSPC
                raise OSError(
                    f"Disk full: Cannot write memory '{title}' to {file_path}. "
                    f"Free up disk space and try again."
                ) from e
            elif e.errno == 13:  # EACCES
                raise PermissionError(
                    f"Permission denied: Cannot write to {file_path}"
                ) from e
            else:
                raise OSError(f"Failed to write memory '{title}': {e}") from e

        logger.info(f"Created memory: {title} -> {file_path.name}")
        logger.debug(
            f"Memory details: type={memory_type.value}, salience={salience}, tags={normalized_tags}"
        )

        return str(file_path)

    def remember_many(
        self,
        memories: list[dict[str, Any]],
        continue_on_error: bool = False,
    ) -> tuple[list[str], list[tuple[dict[str, Any], Exception]]]:
        """
        Create multiple memories in a single batch operation.

        This method efficiently creates multiple memories at once, useful for
        bulk imports from other note-taking systems or batch data ingestion.

        Args:
            memories: List of memory data dictionaries. Each dictionary should contain:
                - title (str, required): Memory title
                - content (str, required): Memory content
                - memory_type (MemoryType, optional): Memory type classification
                - tags (list[str], optional): List of tags
                - salience (float, optional): Importance score (0.0-1.0)
                - meta (dict, optional): Additional metadata
            continue_on_error: If True, continue processing remaining memories even
                if some fail. If False, stop on first error. Default: False

        Returns:
            Tuple of (successful_paths, errors):
                - successful_paths: List of file paths for successfully created memories
                - errors: List of tuples (memory_data, exception) for failed memories

        Example:
            >>> kernel = MemoryKernel(vault_path="./vault")
            >>> memories = [
            ...     {
            ...         "title": "Python Tip 1",
            ...         "content": "Use list comprehensions",
            ...         "tags": ["python", "tips"],
            ...         "salience": 0.7
            ...     },
            ...     {
            ...         "title": "Python Tip 2",
            ...         "content": "Use f-strings for formatting",
            ...         "tags": ["python", "tips"],
            ...         "salience": 0.6
            ...     }
            ... ]
            >>> paths, errors = kernel.remember_many(memories)
            >>> print(f"Created {len(paths)} memories, {len(errors)} failed")
            Created 2 memories, 0 failed
        """
        successful_paths = []
        errors = []

        logger.info(f"Starting batch creation of {len(memories)} memories")

        for idx, memory_data in enumerate(memories):
            try:
                # Extract parameters from dictionary
                title_raw = memory_data.get("title")
                content_raw = memory_data.get("content")

                # Validate and cast title and content to str
                if not isinstance(title_raw, str) or not title_raw:
                    raise ValueError(
                        f"title must be a non-empty string, got {type(title_raw).__name__}"
                    )
                if not isinstance(content_raw, str) or not content_raw:
                    raise ValueError(
                        f"content must be a non-empty string, got {type(content_raw).__name__}"
                    )

                title: str = title_raw
                content: str = content_raw
                memory_type = memory_data.get("memory_type", MemoryType.FACT)
                tags = memory_data.get("tags")
                salience = memory_data.get("salience", 0.5)
                meta = memory_data.get("meta")

                # Create memory
                path = self.remember(
                    title=title,
                    content=content,
                    memory_type=memory_type,
                    tags=tags,
                    salience=salience,
                    meta=meta,
                )
                successful_paths.append(path)
                logger.debug(f"Batch [{idx + 1}/{len(memories)}]: Created {title}")

            except Exception as e:
                error_info = (memory_data, e)
                errors.append(error_info)
                logger.warning(
                    f"Batch [{idx + 1}/{len(memories)}]: Failed to create "
                    f"'{memory_data.get('title', 'unknown')}': {e}"
                )

                if not continue_on_error:
                    logger.error(
                        f"Batch creation stopped after {len(successful_paths)} successes "
                        f"and {len(errors)} failures"
                    )
                    break

        logger.info(
            f"Batch creation complete: {len(successful_paths)} created, {len(errors)} failed"
        )

        return successful_paths, errors

    def update_many(
        self,
        updates: list[tuple[str, dict[str, Any]]],
        continue_on_error: bool = True,
    ) -> tuple[list[str], list[tuple[str, Exception]]]:
        """
        Update multiple memories in a single batch operation.

        This method efficiently updates multiple existing memories, useful for
        bulk metadata changes or content updates.

        Args:
            updates: List of tuples (memory_id, update_data). Each update_data
                dictionary can contain:
                - content (str, optional): New content (appends to existing)
                - tags (list[str], optional): New tags (merges with existing)
                - salience (float, optional): New salience value
                - meta (dict, optional): Metadata to merge with existing
            continue_on_error: If True, continue processing even if some fail.
                Default: True

        Returns:
            Tuple of (successful_ids, errors):
                - successful_ids: List of memory IDs successfully updated
                - errors: List of tuples (memory_id, exception) for failed updates

        Example:
            >>> kernel = MemoryKernel(vault_path="./vault")
            >>> kernel.ingest()
            >>> updates = [
            ...     ("python-tip-1", {"salience": 0.9, "tags": ["important"]}),
            ...     ("python-tip-2", {"salience": 0.8})
            ... ]
            >>> updated, errors = kernel.update_many(updates)
            >>> print(f"Updated {len(updated)} memories")
            Updated 2 memories

        Note:
            This method reads the markdown file, updates the frontmatter,
            and writes it back. Content updates are appended, tags are merged.
        """
        successful_ids = []
        errors = []

        logger.info(f"Starting batch update of {len(updates)} memories")

        for idx, (memory_id, update_data) in enumerate(updates):
            try:
                # Find the memory file using graph lookup (much faster than rglob)
                node = self.graph.get(memory_id)
                if not node or not node.source_path:
                    raise ValueError(f"Memory not found in graph: {memory_id}")

                memory_path = Path(node.source_path)
                if not memory_path.exists():
                    raise ValueError(f"Memory file not found for ID: {memory_id}")

                # Read existing content
                content = memory_path.read_text(encoding="utf-8")

                # Parse frontmatter and body
                if content.startswith("---\n"):
                    parts = content.split("---\n", 2)
                    if len(parts) >= 3:
                        frontmatter_str = parts[1]
                        body = parts[2].strip()
                        frontmatter = yaml.safe_load(frontmatter_str)
                    else:
                        raise ValueError(f"Invalid frontmatter format in {memory_id}")
                else:
                    raise ValueError(f"No frontmatter found in {memory_id}")

                # Update frontmatter
                if "salience" in update_data:
                    frontmatter["salience"] = update_data["salience"]

                if "meta" in update_data:
                    if "meta" not in frontmatter:
                        frontmatter["meta"] = {}
                    frontmatter["meta"].update(update_data["meta"])

                # Update body if content provided (append)
                if "content" in update_data:
                    body = f"{body}\n\n{update_data['content'].strip()}"

                # Merge tags if provided
                if "tags" in update_data:
                    new_tags = update_data["tags"]
                    # Extract existing tags from body
                    existing_tags = []
                    tag_pattern = r"#(\w+)"
                    existing_tags = re.findall(tag_pattern, body)

                    # Merge tags (deduplicate)
                    all_tags = list(set(existing_tags + new_tags))

                    # Remove old tag line
                    body = re.sub(r"\n\n#[\w\s#]+$", "", body).strip()

                    # Add new tag line
                    tags_line = " ".join(f"#{tag}" for tag in all_tags)
                    if tags_line:
                        body = f"{body}\n\n{tags_line}"

                # Update modified timestamp
                frontmatter["modified"] = datetime.now(timezone.utc).isoformat()

                # Write back
                new_frontmatter = (
                    "---\n"
                    + yaml.safe_dump(frontmatter, sort_keys=False).strip()
                    + "\n---\n\n"
                )
                self._atomic_write(memory_path, new_frontmatter + body + "\n")  # type: ignore[union-attr]

                successful_ids.append(memory_id)
                logger.debug(
                    f"Batch update [{idx + 1}/{len(updates)}]: Updated {memory_id}"
                )

            except Exception as e:
                error_info = (memory_id, e)
                errors.append(error_info)
                logger.warning(
                    f"Batch update [{idx + 1}/{len(updates)}]: Failed to update '{memory_id}': {e}"
                )

                if not continue_on_error:
                    logger.error(
                        f"Batch update stopped after {len(successful_ids)} successes "
                        f"and {len(errors)} failures"
                    )
                    break

        logger.info(
            f"Batch update complete: {len(successful_ids)} updated, {len(errors)} failed"
        )

        return successful_ids, errors

    def context_window(
        self,
        query: str,
        tags: list[str] | None = None,
        depth: int = 2,
        top_k: int = 8,
        token_limit: int = 2048,
    ) -> str:
        """
        Retrieve relevant context from the memory vault as a compressed string.

        This method combines retrieval and token compression to generate a context
        window suitable for LLM prompts or RAG applications.

        Args:
            query: Search query string to find relevant memories.
            tags: Optional list of tags to filter results. Only memories with
                at least one matching tag will be included.
            depth: Graph traversal depth for finding related memories through
                wikilinks. Higher values explore more connections. Default: 2
            top_k: Maximum number of memories to retrieve. Default: 8
            token_limit: Maximum number of tokens in the compressed output.
                The compressor will truncate content to fit within this limit.
                Default: 2048

        Returns:
            Compressed string representation of the most relevant memories,
            formatted and ready for use as LLM context.

        Example:
            >>> kernel = MemoryKernel(vault_path="./vault")
            >>> kernel.ingest()
            >>> context = kernel.context_window(
            ...     query="python best practices",
            ...     tags=["programming"],
            ...     depth=2,
            ...     top_k=5,
            ...     token_limit=1024
            ... )
            >>> print(context[:100])
            Memory: Python Tips
            Content: Always use list comprehensions...
        """
        nodes = self.retrieve_nodes(query=query, tags=tags, depth=depth, top_k=top_k)
        compressor = TokenCompressor(token_limit=token_limit)
        compressed = compressor.compress(nodes)

        logger.debug(
            f"Generated context window: {len(nodes)} nodes, ~{len(compressed)} chars"
        )

        return compressed

    def retrieve_nodes(
        self,
        query: str,
        tags: list[str] | None = None,
        depth: int = 2,
        top_k: int = 8,
        use_cache: bool = True,
    ) -> list[MemoryNode]:
        """
        Retrieve relevant memory nodes using hybrid search (keyword + semantic + graph).

        Args:
            query: Search query string.
            tags: Optional list of tags to filter results.
            depth: Graph traversal depth from seed nodes. Default: 2
            top_k: Maximum number of nodes to return. Default: 8
            use_cache: Whether to use query result cache. Default: True

        Returns:
            List of MemoryNode objects ranked by relevance score.
        """
        # Validate inputs
        if self.validate_inputs:
            query = validate_query(query)
            if tags:
                tags = validate_tags(tags)
            depth = validate_depth(depth)
            top_k = validate_top_k(top_k)
        else:
            if not query or not isinstance(query, str):
                raise TypeError(
                    f"query must be a non-empty string, got {type(query).__name__}"
                )
            if not query.strip():
                raise ValueError("query cannot be empty")
            if not isinstance(depth, int) or depth < 0:
                raise ValueError(f"depth must be a non-negative integer, got {depth}")
            if not isinstance(top_k, int) or top_k <= 0:
                raise ValueError(f"top_k must be a positive integer, got {top_k}")

        # Check query cache
        if use_cache and self.query_cache:
            cache_key = f"{query}|{tags}|{depth}|{top_k}"
            cached_results = self.query_cache.get(cache_key)
            if cached_results is not None:
                logger.debug(f"Query cache hit: {query}")
                return cached_results

        normalized_tags = self._normalize_tags(tags)

        # Auto-ingest with failure tracking (Fix #4)
        if not self.graph._nodes:
            if self._last_ingest_error:
                raise RuntimeError(
                    f"Cannot retrieve - ingest failed:\n"
                    f"  {type(self._last_ingest_error).__name__}: "
                    f"{self._last_ingest_error}\n\n"
                    f"Fix issues and call kernel.ingest(force=True)"
                )

            if self._ingest_attempt_count >= self._max_auto_ingest_attempts:
                raise RuntimeError(
                    f"Auto-ingest failed {self._ingest_attempt_count} times. "
                    f"Check logs and retry manually."
                )

            logger.info(
                f"Auto-ingest attempt {self._ingest_attempt_count + 1}/"
                f"{self._max_auto_ingest_attempts}"
            )
            try:
                self.ingest()
            except Exception as e:
                raise RuntimeError(f"Auto-ingest failed: {e}") from e

        # Keyword-based seed finding
        query_words = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
        seed_ids = []
        for node in self.graph._nodes.values():
            haystack = f"{node.title} {node.content}".lower()
            if any(word in haystack for word in query_words):
                seed_ids.append(node.id)

        logger.debug(f"Found {len(seed_ids)} seed nodes for query: '{query}'")

        # Retrieval with thread safety (Fix #5)
        with self._graph_lock:
            start_time = time_module.time()
            results = self.retriever.retrieve(
                query=query,
                seed_ids=seed_ids,
                tags=normalized_tags,
                depth=depth,
                top_k=top_k,
            )
            duration = time_module.time() - start_time

            logger.info(
                f"Retrieved {len(results)} nodes "
                f"(graph v{self._graph_version}) in {duration:.3f}s"
            )

        # Cache results
        if use_cache and self.query_cache:
            cache_key = f"{query}|{tags}|{depth}|{top_k}"
            self.query_cache.put(cache_key, results)

            return results

    def query(self) -> MemoryQuery:
        """
        Create a new query builder for constructing complex searches.

        Returns:
            MemoryQuery instance for building and executing queries.

        Example:
            >>> kernel = MemoryKernel(vault_path="./vault")
            >>> # Simple query
            >>> results = kernel.query().search("python").execute()
            >>>
            >>> # Complex query with multiple filters
            >>> results = (
            ...     kernel.query()
            ...         .search("machine learning")
            ...         .with_tags(["ai", "python"])
            ...         .memory_type(MemoryType.SEMANTIC)
            ...         .min_salience(0.7)
            ...         .depth(3)
            ...         .limit(10)
            ...         .execute()
            ... )
            >>> for node in results:
            ...     print(f"{node.title}: {node.salience}")
        """
        return MemoryQuery(self)

    def search(
        self,
        query: str,
        options: SearchOptions | None = None,
    ) -> list[MemoryNode]:
        """
        Advanced search with configurable options.

        This method provides fine-grained control over search behavior through
        the SearchOptions dataclass, allowing customization of strategies,
        filters, and scoring weights.

        Args:
            query: Search query string.
            options: Optional SearchOptions for advanced configuration.
                If None, uses default hybrid search.

        Returns:
            List of MemoryNode objects matching the search criteria,
            filtered and sorted according to the options.

        Example:
            >>> kernel = MemoryKernel(vault_path="./vault")
            >>> # Simple search with defaults
            >>> results = kernel.search("python tips")
            >>>
            >>> # Advanced search with options
            >>> opts = SearchOptions(
            ...     strategy="hybrid",
            ...     min_salience=0.7,
            ...     boost_recent=True,
            ...     max_results=5,
            ...     weights={"keyword": 0.3, "semantic": 0.7}
            ... )
            >>> results = kernel.search("python tips", options=opts)
            >>> for node in results:
            ...     print(f"{node.title}: {node.salience}")
        """
        # Use default options if none provided
        if options is None:
            options = SearchOptions()

        # Retrieve nodes using standard method
        results = self.retrieve_nodes(
            query=query,
            tags=None,  # SearchOptions doesn't include tags (use query builder for that)
            depth=options.depth,
            top_k=options.max_results * 2,  # Get more initially for filtering
        )

        # Apply min_salience filter
        if options.min_salience > 0.0:
            results = [n for n in results if n.salience >= options.min_salience]
            logger.debug(
                f"Filtered to {len(results)} nodes with salience >= {options.min_salience}"
            )

        # Apply recency boost if requested
        if options.boost_recent and options.time_decay_factor:
            import copy
            import math
            import time

            current_time = time.time()

            # Create copies to avoid modifying original nodes (prevents side effects)
            boosted_results = []
            for node in results:
                # Create shallow copy to avoid modifying original
                boosted_node = copy.copy(node)

                # Calculate time difference in days
                node_time = node.created_at.timestamp()
                days_old = (current_time - node_time) / (24 * 3600)

                # Apply exponential decay: score * exp(-decay_factor * days)
                recency_factor = math.exp(-options.time_decay_factor * days_old)

                # Boost salience on the copy
                boosted_node.salience = node.salience * (0.5 + 0.5 * recency_factor)
                boosted_results.append(boosted_node)

            results = boosted_results

            # Re-sort by boosted salience
            results.sort(key=lambda n: n.salience, reverse=True)
            logger.debug(
                f"Applied recency boost with decay factor {options.time_decay_factor}"
            )

        # Include backlinks if requested
        if options.include_backlinks:
            # Add nodes that link to our results
            backlink_ids = set()
            for node in results[: options.max_results]:
                backlink_ids.update(node.backlinks)

            for backlink_id in backlink_ids:
                if (
                    backlink_node := self.graph.get(backlink_id)
                ) and backlink_node not in results:
                    results.append(backlink_node)

            logger.debug(f"Included {len(backlink_ids)} backlink nodes")

        # Limit to max_results
        results = results[: options.max_results]

        logger.info(
            f"Search completed: {len(results)} results "
            f"(strategy={options.strategy}, min_salience={options.min_salience})"
        )

        return results

    def explain_retrieval(
        self,
        query: str,
        tags: list[str] | None = None,
        depth: int = 2,
        top_k: int = 8,
    ) -> dict:
        """
        Explain the retrieval process with detailed score breakdowns.

        Only available when GAM is enabled. Shows why memories were ranked
        in a particular order with component score contributions.

        Args:
            query: Search query string
            tags: Optional tag filter
            depth: Graph traversal depth
            top_k: Maximum results to explain

        Returns:
            Dict with retrieval explanation including:
            - query info
            - GAM configuration
            - candidate count
            - top results with detailed score breakdowns

        Raises:
            RuntimeError: If GAM is not enabled

        Example:
            >>> kernel = MemoryKernel(vault_path="./vault", use_gam=True)
            >>> kernel.ingest()
            >>> explanation = kernel.explain_retrieval("python tips", top_k=5)
            >>>
            >>> print(f"Query: {explanation['query']}")
            >>> print(f"Found {explanation['candidates_found']} candidates")
            >>>
            >>> for result in explanation['results']:
            ...     print(f"\nMemory: {result['node_title']}")
            ...     print(f"Final Score: {result['final_score']:.3f}")
            ...     comps = result['components']
            ...     print(f"  Relationship: {comps['relationship']['contribution']:.3f}")
            ...     print(f"  Co-access: {comps['co_access']['contribution']:.3f}")
            ...     print(f"  Recency: {comps['recency']['contribution']:.3f}")
            ...     print(f"  Salience: {comps['salience']['contribution']:.3f}")
        """
        if not self.use_gam:
            raise RuntimeError(
                "GAM is not enabled. Initialize kernel with use_gam=True to use this feature."
            )

        if not isinstance(self.retriever, GAMRetriever):
            raise RuntimeError("Retriever is not a GAMRetriever instance")

        normalized_tags = self._normalize_tags(tags)

        # Auto-ingest if needed
        if not self.graph._nodes:
            logger.info("Graph is empty, running auto-ingest")
            self.ingest()

        # Get seed IDs
        query_words = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
        seed_ids = []
        for node in self.graph._nodes.values():
            haystack = f"{node.title} {node.content}".lower()
            if any(word in haystack for word in query_words):
                seed_ids.append(node.id)

        # Get explanation from GAM retriever
        explanation = self.retriever.explain_retrieval(
            query, seed_ids, normalized_tags, depth, top_k
        )

        return explanation

    def get_gam_statistics(self) -> dict:
        """
        Get GAM access tracking statistics.

        Returns access patterns and co-access data collected during retrieval.
        Only available when GAM is enabled.

        Returns:
            Dict with statistics:
            - total_queries: Number of queries tracked
            - nodes_tracked: Number of unique nodes accessed
            - relationships_tracked: Number of co-access relationships
            - history_size: Size of query history
            - most_accessed_nodes: Top 10 most accessed memories

        Raises:
            RuntimeError: If GAM is not enabled

        Example:
            >>> kernel = MemoryKernel(vault_path="./vault", use_gam=True)
            >>> kernel.ingest()
            >>> # Perform some queries...
            >>> kernel.retrieve_nodes("python tips")
            >>> kernel.retrieve_nodes("machine learning")
            >>>
            >>> stats = kernel.get_gam_statistics()
            >>> print(f"Tracked {stats['total_queries']} queries")
            >>> print(f"Most accessed memories:")
            >>> for node_id, count in stats['most_accessed_nodes']:
            ...     print(f"  {node_id}: {count} accesses")
        """
        if not self.use_gam:
            raise RuntimeError(
                "GAM is not enabled. Initialize kernel with use_gam=True to use this feature."
            )

        if not isinstance(self.retriever, GAMRetriever):
            raise RuntimeError("Retriever is not a GAMRetriever instance")

        return self.retriever.get_access_statistics()

    # ==================== Cache Management ====================

    def get_cache_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics for embedding and query caches.
        """
        stats: dict[str, Any] = {}
        if self.embedding_cache:
            stats["embedding"] = self.embedding_cache.get_stats()
        if self.query_cache:
            stats["query"] = self.query_cache.get_stats()
        return stats

    def clear_cache(self, cache_type: str = "all"):
        """Clear caches.

        Args:
            cache_type: Type of cache to clear ('embedding', 'query', 'all').
        """
        if cache_type in ("embedding", "all") and self.embedding_cache:
            self.embedding_cache.clear()
            logger.info("Embedding cache cleared")
        if cache_type in ("query", "all") and self.query_cache:
            self.query_cache.clear()
            logger.info("Query cache cleared")

    async def search_async(
        self,
        query: str,
        options: SearchOptions | None = None,
    ) -> list[MemoryNode]:
        """
        Async version of search() for FastAPI and async frameworks.

        Args:
            Same as search()

        Returns:
            List of MemoryNode objects matching the search criteria.

        Example:
            >>> async def advanced_search():
            ...     opts = SearchOptions(boost_recent=True, min_salience=0.7)
            ...     results = await kernel.search_async("python", options=opts)
            ...     return results
        """
        return await asyncio.to_thread(self.search, query=query, options=options)

    # ==================== Async Methods for FastAPI Integration ====================

    async def remember_async(
        self,
        title: str,
        content: str,
        memory_type: MemoryType = MemoryType.FACT,
        tags: list[str] | None = None,
        salience: float = 0.5,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """
        Async version of remember() for FastAPI and async frameworks.

        Runs the synchronous remember() method in a thread pool to avoid
        blocking the event loop.

        Args:
            Same as remember()

        Returns:
            Path to the created memory file as a string.

        Example:
            >>> import asyncio
            >>> kernel = MemoryKernel(vault_path="./vault")
            >>>
            >>> async def create_memory():
            ...     path = await kernel.remember_async(
            ...         title="Async Note",
            ...         content="Created asynchronously",
            ...         salience=0.8
            ...     )
            ...     return path
            >>>
            >>> asyncio.run(create_memory())
        """
        return await asyncio.to_thread(
            self.remember,
            title=title,
            content=content,
            memory_type=memory_type,
            tags=tags,
            salience=salience,
            meta=meta,
        )

    async def ingest_async(
        self, force: bool = False, auto_extract: bool | None = None
    ) -> dict[str, int]:
        """
        Async version of ingest() for FastAPI and async frameworks.

        Runs the synchronous ingest() method in a thread pool.

        Args:
            Same as ingest()

        Returns:
            Dictionary with ingestion statistics.

        Example:
            >>> async def load_vault():
            ...     stats = await kernel.ingest_async()
            ...     print(f"Loaded {stats['total']} memories")
        """
        return await asyncio.to_thread(
            self.ingest, force=force, auto_extract=auto_extract
        )

    async def retrieve_nodes_async(
        self,
        query: str,
        tags: list[str] | None = None,
        depth: int = 2,
        top_k: int = 8,
        use_cache: bool = True,
        use_gam: bool | None = None,
        **kwargs,
    ) -> list[MemoryNode]:
        """Async version of retrieve_nodes().

        Args:
            query: Search query string.
            tags: Optional list of tags to filter results.
            depth: Graph traversal depth.
            top_k: Maximum number of nodes to return.
            use_cache: Whether to use query result cache.
            use_gam: Ignored (kept for backwards compat with GAMAsyncKernel).
        """
        async with self._semaphore:
            return await asyncio.to_thread(
                self.retrieve_nodes,
                query=query,
                tags=tags,
                depth=depth,
                top_k=top_k,
                use_cache=use_cache,
            )

    async def context_window_async(
        self,
        query: str,
        tags: list[str] | None = None,
        depth: int = 2,
        top_k: int = 8,
        token_limit: int = 2048,
    ) -> str:
        """
        Async version of context_window() for FastAPI and async frameworks.

        Runs the synchronous context_window() method in a thread pool.

        Args:
            Same as context_window()

        Returns:
            Compressed string representation of relevant memories.

        Example:
            >>> async def get_context():
            ...     context = await kernel.context_window_async(
            ...         query="machine learning",
            ...         token_limit=1024
            ...     )
            ...     return context
        """
        return await asyncio.to_thread(
            self.context_window,
            query=query,
            tags=tags,
            depth=depth,
            top_k=top_k,
            token_limit=token_limit,
        )

    async def remember_many_async(
        self,
        memories: list[dict[str, Any]],
        continue_on_error: bool = False,
    ) -> tuple[list[str], list[tuple[dict[str, Any], Exception]]]:
        """
        Async version of remember_many() for FastAPI and async frameworks.

        Runs the synchronous remember_many() method in a thread pool.

        Args:
            Same as remember_many()

        Returns:
            Tuple of (successful_paths, errors).

        Example:
            >>> async def bulk_create():
            ...     memories = [
            ...         {"title": "Note 1", "content": "Content 1"},
            ...         {"title": "Note 2", "content": "Content 2"}
            ...     ]
            ...     paths, errors = await kernel.remember_many_async(memories)
            ...     print(f"Created {len(paths)} memories")
        """
        return await asyncio.to_thread(
            self.remember_many,
            memories=memories,
            continue_on_error=continue_on_error,
        )

    async def update_many_async(
        self,
        updates: list[tuple[str, dict[str, Any]]],
        continue_on_error: bool = True,
    ) -> tuple[list[str], list[tuple[str, Exception]]]:
        """
        Async version of update_many() for FastAPI and async frameworks.

        Runs the synchronous update_many() method in a thread pool.

        Args:
            Same as update_many()

        Returns:
            Tuple of (successful_ids, errors).

        Example:
            >>> async def bulk_update():
            ...     updates = [
            ...         ("note-1", {"salience": 0.9}),
            ...         ("note-2", {"tags": ["important"]})
            ...     ]
            ...     updated, errors = await kernel.update_many_async(updates)
            ...     print(f"Updated {len(updated)} memories")
        """
        return await asyncio.to_thread(
            self.update_many,
            updates=updates,
            continue_on_error=continue_on_error,
        )

    async def get_cache_stats_async(self) -> dict:
        """Get cache statistics asynchronously."""
        return await asyncio.to_thread(self.get_cache_stats)

    async def clear_cache_async(self, cache_type: str = "all"):
        """Clear caches asynchronously."""
        await asyncio.to_thread(self.clear_cache, cache_type)

    # ==================== Batch Async Operations ====================

    async def remember_batch_async(
        self,
        memories: list[dict[str, Any]],
        show_progress: bool = False,
        batch_size: int = 10,
    ) -> list[str]:
        """Create multiple memories asynchronously in batches.

        Args:
            memories: List of memory dictionaries with title, content, tags, etc.
            show_progress: Whether to show progress bar (requires rich).
            batch_size: Number of concurrent operations per batch.

        Returns:
            List of file paths for created memories.
        """

        async def create_memory(memory: dict[str, Any]) -> str:
            kwargs = {}
            if "memory_type" in memory and memory["memory_type"] is not None:
                kwargs["memory_type"] = memory["memory_type"]
            return await self.remember_async(
                memory.get("title", ""),
                memory.get("content", ""),
                tags=memory.get("tags"),
                salience=memory.get("salience", 0.5),
                **kwargs,
            )

        if show_progress:
            try:
                from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    TextColumn("{task.completed}/{task.total}"),
                ) as progress:
                    task = progress.add_task(
                        "Creating memories...", total=len(memories)
                    )
                    results = []
                    for i in range(0, len(memories), batch_size):
                        batch = memories[i : i + batch_size]
                        batch_results = await asyncio.gather(
                            *[create_memory(m) for m in batch]
                        )
                        results.extend(batch_results)
                        progress.update(task, advance=len(batch))
                    await asyncio.sleep(0.1)
                    await self.ingest_async(force=True)
                    return results
            except ImportError:
                pass

        results = []
        for i in range(0, len(memories), batch_size):
            batch = memories[i : i + batch_size]
            batch_results = await asyncio.gather(*[create_memory(m) for m in batch])
            results.extend(batch_results)

        await asyncio.sleep(0.1)
        await self.ingest_async(force=True)
        return results

    async def retrieve_batch_async(
        self,
        queries: list[str],
        tags: list[str] | None = None,
        depth: int = 2,
        top_k: int = 8,
        deduplicate: bool = True,
        show_progress: bool = True,
        **kwargs,
    ) -> dict[str, list[MemoryNode]]:
        """Retrieve results for multiple queries concurrently.

        Args:
            queries: List of search queries.
            tags: Filter by tags (applied to all queries).
            depth: Graph traversal depth.
            top_k: Number of results per query.
            deduplicate: Remove duplicate nodes across queries.
            show_progress: Show progress indicator.

        Returns:
            Dictionary mapping queries to their result lists.
        """

        async def retrieve_one(q: str) -> tuple[str, list[MemoryNode]]:
            nodes = await self.retrieve_nodes_async(
                q, tags=tags, depth=depth, top_k=top_k
            )
            return (q, nodes)

        results_list = await asyncio.gather(*[retrieve_one(q) for q in queries])
        results = dict(results_list)

        if deduplicate:
            seen_ids: set[str] = set()
            deduplicated: dict[str, list[MemoryNode]] = {}
            for query_str, nodes in results.items():
                unique = []
                for node in nodes:
                    if node.id not in seen_ids:
                        unique.append(node)
                        seen_ids.add(node.id)
                deduplicated[query_str] = unique
            results = deduplicated

        return results

    async def update_batch_async(
        self, updates: list[dict[str, Any]], show_progress: bool = True
    ) -> list[str]:
        """Update multiple memories concurrently.

        Args:
            updates: List of update dicts with 'id' and fields to update.
            show_progress: Show progress indicator.

        Returns:
            List of updated memory IDs.
        """
        from memograph.core.validation import validate_memory_id

        for update in updates:
            if "id" not in update:
                raise ValueError("Each update must contain 'id' field")
            validate_memory_id(update["id"])

        async def update_single(update: dict[str, Any]) -> str:
            async with self._semaphore:
                memory_id = update["id"]
                node = self.graph.get(memory_id)
                if not node:
                    raise FileNotFoundError(f"Memory not found: {memory_id}")

                file_path = Path(node.source_path)
                content = await asyncio.to_thread(file_path.read_text, encoding="utf-8")

                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        frontmatter = yaml.safe_load(parts[1])
                        body = parts[2].strip()
                    else:
                        frontmatter = {}
                        body = content
                else:
                    frontmatter = {}
                    body = content

                if "tags" in update:
                    frontmatter["tags"] = update["tags"]
                if "salience" in update:
                    frontmatter["salience"] = update["salience"]
                if "content" in update:
                    body = update["content"]

                new_content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n{body}"
                await asyncio.to_thread(
                    file_path.write_text, new_content, encoding="utf-8"
                )
                return memory_id

        updated_ids = await asyncio.gather(*[update_single(u) for u in updates])
        await self.ingest_async(force=True)
        return list(updated_ids)

    async def delete_batch_async(
        self, memory_ids: list[str], show_progress: bool = True
    ) -> list[str]:
        """Delete multiple memories concurrently.

        Args:
            memory_ids: List of memory IDs to delete.
            show_progress: Show progress indicator.

        Returns:
            List of deleted memory IDs.
        """
        from memograph.core.validation import validate_memory_id

        for memory_id in memory_ids:
            validate_memory_id(memory_id)

        async def delete_single(memory_id: str) -> str:
            async with self._semaphore:
                node = self.graph.get(memory_id)
                if not node:
                    raise FileNotFoundError(f"Memory not found: {memory_id}")
                file_path = Path(node.source_path)
                await asyncio.to_thread(file_path.unlink)
                return memory_id

        deleted_ids = await asyncio.gather(*[delete_single(mid) for mid in memory_ids])
        await self.ingest_async(force=True)
        return list(deleted_ids)

    async def aggregate_results_async(
        self, queries: list[str], aggregation: str = "union", **kwargs
    ) -> list[MemoryNode]:
        """Aggregate results from multiple queries.

        Args:
            queries: List of search queries.
            aggregation: Aggregation method ('union' or 'intersection').

        Returns:
            Aggregated list of memory nodes.
        """
        results = await self.retrieve_batch_async(queries, deduplicate=False, **kwargs)

        if aggregation == "union":
            seen: set[str] = set()
            union_nodes = []
            for nodes in results.values():
                for node in nodes:
                    if node.id not in seen:
                        union_nodes.append(node)
                        seen.add(node.id)
            return union_nodes
        elif aggregation == "intersection":
            if not results:
                return []
            first_query = list(results.keys())[0]
            intersection_ids = {node.id for node in results[first_query]}
            for _query, nodes in list(results.items())[1:]:
                intersection_ids &= {node.id for node in nodes}
            all_nodes_map = {
                node.id: node for nodes in results.values() for node in nodes
            }
            return [all_nodes_map[nid] for nid in intersection_ids]
        else:
            raise ValueError(f"Unknown aggregation method: {aggregation}")

    # ==================== GAM Async Stats ====================

    async def get_gam_stats_async(self) -> dict[str, Any]:
        """Get GAM statistics asynchronously.

        Returns:
            Dictionary with GAM statistics.
        """
        if not self.use_gam:
            return {"enabled": False}

        gam_config = getattr(self, "gam_config", None)

        if isinstance(self.retriever, GAMRetriever):
            tracker = getattr(self.retriever, "access_tracker", None)
            if tracker:
                return await asyncio.to_thread(
                    lambda: {
                        "enabled": True,
                        "total_accesses": len(tracker.access_history),
                        "unique_nodes": len(tracker.node_access_counts),
                        "config": gam_config,
                    }
                )
        return {
            "enabled": True,
            "total_accesses": 0,
            "unique_nodes": 0,
            "config": gam_config,
        }

    async def reset_gam_stats_async(self):
        """Reset GAM access statistics asynchronously."""
        if isinstance(self.retriever, GAMRetriever):
            tracker = getattr(self.retriever, "access_tracker", None)
            if tracker:
                await asyncio.to_thread(tracker.reset)
