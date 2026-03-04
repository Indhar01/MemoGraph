# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- CODE_OF_CONDUCT.md for community guidelines
- CONTRIBUTING.md with detailed contribution guidelines
- SECURITY.md for security policy
- Pre-commit configuration for code quality
- Comprehensive test configuration
- Development dependencies in pyproject.toml

### Changed
- Improved project structure and organization
- Enhanced pyproject.toml with better tooling configuration
- Updated README with badges and better examples

### Fixed
- Various code quality improvements

## [Unreleased]

### Added
- Repository optimizations for better discoverability
- Enhanced documentation and examples

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

[Unreleased]: https://github.com/Indhar01/MemoGraph/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/Indhar01/MemoGraph/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/Indhar01/MemoGraph/releases/tag/v0.0.1
