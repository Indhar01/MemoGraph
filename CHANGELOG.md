# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] — 2026-06-23

This release ships everything required for the v1.0 cut: a signed,
multi-arch container image; a Helm chart and raw K8s manifests; an
explicit public API surface and deprecation policy; and the full
Phase 0–3 enterprise readiness work (auth, hardening, multi-tenancy
scaffold, GDPR scheduled deletion). It is also the first release cut
through the new `release.yml` + `verify-versions` + cosign pipeline —
so the version itself is partly a dress rehearsal for v1.0.

### Added — v1.0 release readiness

- `requirements.lock` (pip-compile, hash-pinned, includes `[web]` extras)
  and Dockerfile install via `--require-hashes` against it.
- Base image pinned by digest (`python@sha256:...`) instead of tag in
  Dockerfile.
- [`docs/RELEASE_RUNBOOK.md`](docs/RELEASE_RUNBOOK.md) — durable,
  version-agnostic procedure for cutting a release across PyPI, GHCR,
  and the MCP registry.
- [`docs/MIGRATION_0.X_TO_1.0.md`](docs/MIGRATION_0.X_TO_1.0.md) —
  contract for what changes (and what doesn't) at the v1.0 cut.
- `memograph.scripts.migrate_to_multitenant` — helper that relocates a
  single-vault 0.x deploy under a 1.0 global root with `--dry-run`.
- Expanded `memograph.__all__` to declare the 1.0 public Python surface
  (`MemoryKernel`, `MemoryQuery`, `SearchOptions`, `MemoryNode`,
  `VaultGraph`, `VaultStorage`, `HybridRetriever`, and the GAM types).
- `helm lint` + double `helm template` render job in CI to catch chart
  regressions before they reach Helm users.

### Added — Phase 0–3 enterprise readiness

The work below makes MemoGraph deployable to multiple paying
tenants with full GDPR procedures, observability, and authentication
without leaving the alpha branch. None of these change the
single-tenant developer experience, but they unlock the SaaS path.

#### Authentication & web hardening (Phase 1)

- OIDC bearer-token auth with JWKS support — works with Auth0, Clerk,
  WorkOS, Keycloak, Azure AD, Okta, Google Workspace.
- Hashed-API-key auth (`X-API-Key`) for service-to-service callers.
- `MEMOGRAPH_AUTH_PROVIDER=multi` accepts either credential type.
- `slowapi` rate limiting (per-key + per-IP, configurable).
- Restrictive CORS (default-deny, allowlist via `MEMOGRAPH_CORS_ORIGINS`).
- Request-size cap middleware (default 1 MB).
- Versioned `/api/v1/` prefix; old `/api/` redirects.
- Separate `/healthz` (liveness) and `/readyz` (readiness).
- Structured JSON logging with request-id propagation.
- Path-traversal-safe `VaultStorage.write` with control-char and
  reserved-name rejection.
- Vault size soft + hard caps with graceful error responses.
- Schema-versioned cache files with migration on load.
- 16 OWASP-top-10-style security tests under `tests/security/`.
- OpenAPI snapshot test in CI to catch unintentional contract drift.

#### Observability & reliability (Phase 2)

- OpenTelemetry FastAPI/asyncio auto-instrumentation; OTLP export.
- Prometheus `/metrics` endpoint as fallback for OTLP-less ops.
- Manual spans on `kernel.search`, `kernel.remember`, swarm cycles.
- Concurrency audit doc + targeted stress tests for concurrent
  reads, writes, deletes.
- Versioned backup format with sha256 manifest + integrity check
  on restore.
- `bandit` + `pip-audit` security workflow on every PR.

#### Multi-tenancy (Phase 3)

- ADR 0001 documenting the kernel-per-tenant + LRU eviction model.
- `TenantStorage` orchestrator: per-tenant directory layout under
  `<global_root>/<tenant_id>/`, validated tenant ids, filesystem-level
  isolation enforced before disk hits.
- `TenantRegistry`: bounded LRU of warm `MemoryKernel` instances;
  cold tenants evict cleanly with cache flush + lock release.
- Admin REST routes for tenant lifecycle: create, list, get, usage,
  immediate-offboard.
- `kernel_for_request` FastAPI dependency wires the registry into
  every non-admin route; per-request kernel resolution from the
  authenticated user's `org_id` claim. Single-tenant deployments
  (`MEMOGRAPH_TENANCY_ENABLED` unset) continue to work unchanged.
- Audit log carries `tenant_id` automatically via the existing
  `current_user` ContextVar — no kernel changes required.
- End-to-end isolation test suite (`tests/tenancy/test_isolation_e2e.py`)
  gating the multi-tenant release: cross-tenant search empty,
  get-by-id 404, list only own-tenant, admin offboard leaves siblings
  byte-identical, orphan users 403, single-tenant smoke preserved.

#### GDPR scheduled deletion (Phase 3.7)

- `POST /api/v1/admin/tenants/{id}/schedule-delete` with
  configurable grace period (default 7 days) and operator reason.
- `DELETE /api/v1/admin/tenants/{id}/schedule-delete` cancels
  before the reaper fires.
- Tombstone schema (`_tombstone.json`, schema-versioned) marks
  tenants for deletion; refuses overwrite to prevent misclick
  resets.
- `python -m memograph.scripts.run_reaper <global_root>` sweeps
  expired tombstones, takes a final backup tarball under
  `.tombstoned-exports/`, then destroys. JSON Lines on stdout;
  `--dry-run` for safe audits.
- Tombstoned tenants return **410 Gone** to non-admin requests
  via `tenant_resolver`; admin routes still serve so operators
  can inspect or cancel.
- 33 tests across tombstone primitives, admin routes, routing
  layer, and reaper sweep behaviors.
- `docs/GDPR_RUNBOOK.md` rewritten to document the scheduled
  flow as the preferred Art. 17 procedure.

#### Enterprise documentation set

- `docs/INSTALL_ENTERPRISE.md` — multi-tenant on-prem + SaaS install.
- `docs/SSO_SETUP.md` — provider-neutral OIDC walkthrough.
- `docs/RBAC_GUIDE.md` — roles and scope mapping.
- `docs/GDPR_RUNBOOK.md` — Art. 15 / 17 / 20 procedures.
- `docs/BACKUP_RESTORE_RUNBOOK.md` — versioned-backup operations.
- `docs/OBSERVABILITY_GUIDE.md` — OTLP/Prometheus dashboards.
- `docs/COMPLIANCE_ROADMAP.md` — SOC 2 / ISO 27001 plan.
- `docs/HOSTING_GUIDE.md` — four genuinely-free hosting paths
  (Oracle Free, Cloudflare Tunnel, GCP, GitHub-vault) with
  hardening checklist.
- `docs/GOOGLE_WORKSPACE_SETUP.md` — Workspace OIDC + Drive
  portability backup walkthrough.
- `docs/adr/0001-tenancy-model.md`, `docs/adr/0002-storage-adapter-strategy.md`
  — architectural decision records.

#### Quickstart experience

- `memograph quickstart` — materialises a 15-note interconnected
  sample vault (Python development knowledge), ingests it, runs
  three illustrative live queries, prints next-step pointers.
  Total time from `pip install` to "wow" under 60 seconds.
- 12 tests covering bundled-vault integrity (every note parses,
  minimum link count, salience in range), the materialise primitive
  (idempotent, refuses to clobber non-empty targets without
  `--force`), and the end-to-end run.

### Tests

- 172+ tests passing across `tests/security/`, `tests/contract/`,
  `tests/tenancy/`, plus 12 quickstart tests. Whole-package mypy
  clean.

## [0.3.0] - 2026-04-21

### Added - AI Features Release 🤖
- 🎉 **Major AI Features Release** - Complete AI-powered knowledge management
- 🏷️ **AutoTagger** - Intelligent tag suggestions with confidence scores and reasoning
- 🔗 **LinkSuggester** - Smart link recommendations between related memories
- 🔍 **GapDetector** - Automatic knowledge gap identification and recommendations
- 📊 **ContentAnalyzer** - Comprehensive knowledge base analytics and insights
- 🔧 **MCP AI Tools** - 4 new MCP tools for AI features (suggest_tags, suggest_links, detect_knowledge_gaps, analyze_knowledge_base)
- 📚 **Comprehensive Documentation** - 75,500+ words across 11 guides
- 🧪 **170+ Tests** - Complete test coverage for all AI features (98.88% for AutoTagger)

### Enhanced - Core Features
- Enhanced CLI with AI commands (`memograph ai suggest-tags`, `suggest-links`, `detect-gaps`, `analyze`)
- Enhanced Web UI with AI features integration
- Enhanced MCP server with 14 total tools (10 existing + 4 new AI tools)
- Improved Python API with AI feature classes

### Documentation
- Added `AI_FEATURES.md` - Complete AI features guide (14KB)
- Added `WEB_UI_GUIDE.md` - Web interface documentation (21KB)
- Added `MCP_AI_TOOLS.md` - MCP integration guide (22KB)
- Added `QUICK_START.md` - 5-minute getting started guide
- Added `AI_ASSISTANT_GUIDE.md` - Building with AI assistants (13KB)
- Added `ENTERPRISE_STRATEGY.md` - Enterprise deployment strategy
- Added `DOCS_GUIDE.md` - Documentation navigation guide
- Updated `TODO.md` - Active release tasks
- Updated `PROJECT_STATUS.md` - Project overview

### Performance & Quality
- **Test Coverage:** 98.88% for AutoTagger, 50%+ for core components
- **AI Features:** All 4 features fully implemented and tested
- **Cross-Platform:** Verified on Windows, Linux, macOS (Python 3.10-3.12)
- **Documentation:** 8 active user guides, 60+ archived planning docs

### Breaking Changes
- None - Fully backward compatible with v0.2.0

### Migration Guide
- No migration needed - Install/upgrade with `pip install --upgrade memograph`
- New AI features are opt-in and don't affect existing functionality
- MCP server automatically includes new AI tools after upgrade

### Technical Details
- New Python modules: `memograph/ai/auto_tagger.py`, `link_suggester.py`, `gap_detector.py`, `content_analyzer.py`
- New test modules: `tests/ai/test_auto_tagger.py`, `test_link_suggester.py`, `test_gap_detector.py`, `test_content_analyzer.py`
- Enhanced MCP server: `memograph/mcp/server.py` with 4 new tool handlers
- LiteLLM integration for multi-provider AI support (OpenAI, Anthropic, Ollama, etc.)


## [0.2.0] - 2026-04-11

### Added - Obsidian Integration v0.2.0
- 🎉 **Major Obsidian Plugin Release** - Advanced sync features and performance optimizations
- ⚡ **Real-time Auto-sync** with intelligent 300ms debouncing
- 🔧 **Advanced Conflict Resolution UI** with side-by-side diff view
- 📦 **Batch Sync Operations** for large vaults (100+ files tested)
- 🚀 **Performance Optimizations** - SQLite indexing (2-3x faster), LRU caching (2-21x speedup)
- 📊 **Sync Status Dashboard** with real-time progress tracking
- 🛡️ **Robust Error Handling** with automatic retry and rollback
- 📚 **Comprehensive Documentation** - Beta testing guide, troubleshooting, FAQ
- 🧪 **48 Integration Tests** with performance benchmarks

### Enhanced - Python Backend
- Enhanced `ObsidianSync` with batch operations, error handling, and rollback mechanism
- Added `PerformanceTracker` for detailed performance metrics
- Improved `ObsidianWatcher` with debouncing and queue management
- Enhanced `SyncState` with SQLite backend and checkpoint/restore
- Optimized `ObsidianParser` with LRU caching and wikilink resolution
- Enhanced `ConflictResolver` with UI callbacks and history tracking

### Documentation
- Added `BETA_TESTING_GUIDE.md` - Comprehensive beta testing guide
- Added `KNOWN_LIMITATIONS.md` - Detailed limitations documentation
- Added `BUG_TRIAGE_PROCESS.md` - Bug management process
- Added `OBSIDIAN_SETUP_GUIDE.md` - Beginner-friendly setup guide
- Added `OBSIDIAN_FEATURES.md` - Complete features documentation
- Added `TROUBLESHOOTING.md` - Troubleshooting guide
- Added `OBSIDIAN_FAQ.md` - FAQ with 27+ questions answered
- Added `PERFORMANCE_BENCHMARKS.md` - Performance metrics and targets

### Performance Improvements
- **Small vaults (10-50 files):** < 5-15s sync time, 2-3 files/s throughput
- **Medium vaults (100 files):** < 30s sync time, 3+ files/s throughput, < 200 MB memory
- **Large vaults (1000 files):** < 300s sync time, 3+ files/s throughput, < 1 GB memory
- **Incremental sync:** 30x speedup (only changed files processed)
- **Cache effectiveness:** 95%+ hit rate, 2-21x speedup on warm cache

### Technical Details
- New TypeScript components: `statusView.ts`, `syncStats.ts`, `conflictModal.ts`, `diffView.ts`
- New Python modules: `performance_metrics.py`
- Enhanced test coverage: 48 integration tests, performance benchmarks
- Test pass rates: Auto-sync 93%, Conflict UI 100%, Batch 78%, Error handling 78%

### Breaking Changes
None - fully backward compatible with previous versions

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

[Unreleased]: https://github.com/Indhar01/MemoGraph/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Indhar01/MemoGraph/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/Indhar01/MemoGraph/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Indhar01/MemoGraph/compare/v0.0.2...v0.1.0
[0.0.2]: https://github.com/Indhar01/MemoGraph/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/Indhar01/MemoGraph/releases/tag/v0.0.1
