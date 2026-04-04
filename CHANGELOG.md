# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-04-02

### Added
- 🎉 **Published to Official MCP Registry** at [io.github.indhar01/memograph](https://github.com/modelcontextprotocol/servers/tree/main/src/memograph)
- Community & Feedback section in README with multiple engagement channels
- Enhanced registry installation instructions with step-by-step setup
- VERSIONING.md document with semantic versioning guidelines
- Direct links to MCP Registry and improved discoverability

### Changed
- Updated README.md with accurate MCP Registry installation process
- Improved version badge and status information
- Enhanced documentation for registry users
- Version bumped to 0.1.1 for registry integration improvements

### Fixed
- Corrected MCP Registry installation instructions (removed non-existent CLI installer)
- Updated community engagement links and resources

## [0.1.0] - 2026-03-28

### Added
- MCP marketplace support with smithery.json
- 14 MCP tools for AI assistant integration (search, create, read, update, delete, analytics)
- Autonomous hooks for query and response processing
- Comprehensive marketplace documentation (MARKETPLACE_QUICKSTART.md)
- Publishing automation scripts
- CODE_OF_CONDUCT.md for community guidelines
- CONTRIBUTING.md with detailed contribution guidelines
- SECURITY.md for security policy
- Pre-commit configuration for code quality
- Comprehensive test configuration
- Development dependencies in pyproject.toml
- Repository optimizations for better discoverability
- Enhanced documentation and examples

### Changed
- Bumped version to 0.1.0 for marketplace stability
- Enhanced MCP server with additional tools
- Improved project structure and organization
- Enhanced pyproject.toml with better tooling configuration
- Updated README with badges and better examples
- Improved documentation for marketplace submission

### Fixed
- Version consistency across configuration files
- Various code quality improvements

## [0.0.2] - 2026-03-02

### Changed
- Version bump for new release
- Updated repository metadata

## [0.0.1] - 2026-03-02

### Added
- Initial release
- Core memory kernel with graph-based retrieval
- Support for Markdown files with YAML frontmatter
- BFS graph traversal for related memories
- Memory types: episodic, semantic, procedural, fact
- Hybrid retrieval (keyword + graph + optional embeddings)
- CLI tool with commands: ingest, remember, context, ask, doctor
- Support for Ollama and Claude LLM providers
- Support for OpenAI and Ollama embedding providers
- Token compression for context windows
- Salience scoring for memory importance
- Caching system for efficient re-indexing
- Wikilink and backlink support
- Tag-based filtering

[Unreleased]: https://github.com/Indhar01/MemoGraph/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Indhar01/MemoGraph/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Indhar01/MemoGraph/compare/v0.0.2...v0.1.0
[0.0.2]: https://github.com/Indhar01/MemoGraph/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/Indhar01/MemoGraph/releases/tag/v0.0.1
