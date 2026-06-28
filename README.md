# MemoGraph 🧠

<!-- mcp-name: io.github.Indhar01/memograph -->

[![PyPI version](https://img.shields.io/pypi/v/memograph)](https://pypi.org/project/memograph/)
[![Python Version](https://img.shields.io/pypi/pyversions/memograph)](https://pypi.org/project/memograph/)
[![License](https://img.shields.io/github/license/Indhar01/MemoGraph)](https://github.com/Indhar01/MemoGraph/blob/main/LICENSE)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-Published-blue)](https://modelcontextprotocol.io/registry)
[![MCP](https://img.shields.io/badge/MCP-Compatible-blue)](https://modelcontextprotocol.io)
[![CodeQL](https://github.com/Indhar01/MemoGraph/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/Indhar01/MemoGraph/actions/workflows/codeql.yml)
[![Security](https://github.com/Indhar01/MemoGraph/actions/workflows/security.yml/badge.svg?branch=main)](https://github.com/Indhar01/MemoGraph/actions/workflows/security.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/Indhar01/MemoGraph/badge)](https://securityscorecards.dev/viewer/?uri=github.com/Indhar01/MemoGraph)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue)](http://mypy-lang.org/)
[![Tests](https://img.shields.io/badge/tests-pytest-orange)](https://docs.pytest.org/)
[![Code Quality](https://img.shields.io/badge/code%20quality-A+-brightgreen)](https://github.com/Indhar01/MemoGraph)
[![Docs](https://img.shields.io/badge/docs-MkDocs%20Material-blue)](https://indhar01.github.io/MemoGraph/)
<!-- Hosted demo: replace the placeholder URL once the Hugging Face Space is live. See deploy/huggingface/SETUP.md. -->
[![Try the live demo](https://img.shields.io/badge/demo-Hugging%20Face%20Space-yellow?logo=huggingface)](https://huggingface.co/spaces)
<!-- Discord: replace the placeholder URL once the server is live. See docs/community/COMMUNITY.md. -->
[![Discord](https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white)](https://github.com/Indhar01/MemoGraph/discussions)
[![Benchmarks: MRA 81.8%](https://img.shields.io/badge/MRA-81.8%25-success)](BENCHMARKS.md)
[![CRS 3.04 vs 2.66 in-context](https://img.shields.io/badge/CRS-3.04%20vs%202.66-success)](BENCHMARKS.md)

**MemoGraph turns a folder of markdown notes into a queryable, AI-ready knowledge graph.** It solves the LLM memory problem — your AI assistants forget last Tuesday's decision, can't find a related note across two projects, and re-derive the same insight again and again — by giving them a persistent, navigable, attribution-friendly memory layer that lives in plain markdown files you control.

You write notes the way you already do. MemoGraph indexes them, builds a graph from `[[wikilinks]]`, ranks them by salience, and serves them back to your LLM (or your team) on demand.

## ⚡ Try it in 60 seconds

```bash
pip install memograph
memograph quickstart
```

That's it. The `quickstart` command drops a small, interconnected sample vault on your disk (15 notes about Python development, with real wikilinks between them), ingests it, and runs three live demo queries so you can see the graph + hybrid retrieval working before you decide whether to commit. Try this query in particular:

```bash
memograph --vault ~/memograph-quickstart search "FastAPI dependency injection"
```

The vault contains a note titled `FastAPI dependencies` (about `Depends(...)`) — the words "dependency" and "injection" never appear in any note's title. MemoGraph still finds it, because hybrid retrieval understands "dependency injection" semantically and the wikilink graph stitches related notes together. **That's the product, demonstrated in one query.**

Re-run `memograph quickstart --force` any time to reset to a fresh demo. When you're ready, point MemoGraph at your real notes: `memograph --vault ~/your-notes ingest`.

## What you get

### As a solo user / knowledge worker

- A vault of human-readable markdown files — nothing proprietary, no lock-in. Your notes outlive any tool.
- Hybrid retrieval that combines keyword search, semantic similarity, and graph traversal so you find the right note even when you don't remember the exact words.
- AI-assisted tagging, link suggestions, and gap detection that grow your knowledge base instead of letting it rot.
- A CLI and a web UI for browsing, editing, and visualizing the graph.

### As an AI agent / IDE user

- A first-class **Model Context Protocol (MCP) server** with 30+ tools, working out of the box with Claude Desktop, Claude Code, Cursor, Cline, Windsurf, Continue, Zed, VS Code, Goose, Gemini CLI, OpenAI Codex CLI, and others.
- Autonomous "auto-save" hooks that capture decisions and context from your AI conversations into the vault automatically.
- Per-conversation memory recall — your assistant can pull "what did we decide last week about X" without you copy-pasting context every time.

### As an enterprise / SaaS operator

- **Multi-tenant deployment** with filesystem-level isolation per tenant, end-to-end isolation tests, and a warm-LRU kernel cache.
- **OIDC + API-key authentication** with JWKS support (Auth0, Clerk, WorkOS, Keycloak, Azure AD, Okta), restrictive CORS, request-size caps, and rate limiting.
- **GDPR-compliant scheduled deletion**: tombstone-with-grace-period flow, automatic final backups, daily reaper, and an audit log of every deletion.
- **Observability built in**: OpenTelemetry traces + Prometheus `/metrics`, structured JSON logging with request IDs, and a separate `/healthz` / `/readyz` for orchestration.
- **Operations runbooks** shipped with the code: install, SSO setup, RBAC, backup-restore, and GDPR procedures.

## How consumers benefit

| You want to… | MemoGraph gives you… |
|---|---|
| Stop your AI assistant from forgetting context across conversations | Persistent vault + MCP server, plus optional auto-save hooks |
| Find a note across thousands when you only half-remember it | Hybrid retrieval (keyword + semantic + graph) with salience ranking |
| Connect related ideas without manual cross-linking | AI link suggestions, backlink graph, BFS traversal |
| Discover what's missing in your knowledge base | Gap detector + topic clustering + learning-path suggestions |
| Self-host a memory backend for a team or product | Web UI, FastAPI HTTP API, OpenAPI v1 contract, Docker compose |
| Ship MemoGraph to multiple paying customers | Multi-tenant kernel registry, OIDC, quotas (roadmap), GDPR runbook |
| Survive an SOC 2 audit conversation | Audit log with user + tenant binding, observability, security workflow, compliance roadmap doc |

> **Stability promise.** From 1.0 onwards, anything in
> `memograph.__all__`, any `/api/v1/...` route, any documented env var,
> and any CLI subcommand in `--help` is covered by a **2-minor-version
> deprecation window**. Pre-1.0 (0.x) is still alpha and may break in
> any minor release. See
> [CONTRIBUTING.md#stability-and-deprecation-policy](CONTRIBUTING.md#stability-and-deprecation-policy)
> for the full contract, and [docs/MIGRATION_0.X_TO_1.0.md](docs/MIGRATION_0.X_TO_1.0.md)
> for what specifically changes at 1.0.

## ✨ Capabilities at a glance

### Core memory engine

- **Graph-based memory** — bidirectional `[[wikilinks]]` build a navigable knowledge graph automatically.
- **Hybrid retrieval** — keyword + semantic embeddings + graph traversal, combined and re-ranked.
- **Memory types** inspired by cognitive science: episodic, semantic, procedural, fact.
- **Salience scoring** (0–1) that decays over time and boosts on access.
- **Smart indexing** — mtime-cached, only re-parses changed files.
- **Context compression** — token-budget-aware windowing for LLM prompts.
- **Markdown-native vault** — every memory is a `.md` file with YAML frontmatter; no proprietary format.

### AI features

- **Smart Auto-Organization Engine** — extract topics, people, action items, decisions, questions, sentiment, risks, ideas, and timeline events from memories.
- **AutoTagger** — suggest tags via semantic analysis, structure detection, and pattern learning.
- **LinkSuggester** — propose `[[wikilinks]]` to related notes; bidirectional opportunities included.
- **GapDetector** — surface missing topics, weak coverage, isolated notes, and unmade links.
- **Knowledge analysis** — vault stats, topic clustering, learning paths, connection analysis.

### Interfaces

- **Python API** — `MemoryKernel` with sync, async, and batch variants.
- **CLI** — 24+ commands for ingest, search, batch ops, import, export, backup, and AI features.
- **MCP server** — 30+ tools, stdio transport, drop-in for any MCP-compatible client.
- **Web UI** — React + D3 graph visualization, search, and editing (FastAPI backend + Vite frontend).
- **HTTP API** — versioned `/api/v1/`, OpenAPI snapshot in CI, ready for service-to-service integration.

### Enterprise & SaaS readiness

- **Source adapters** — connect a local folder, S3-compatible bucket (AWS / MinIO / R2 / B2), Notion workspace, Google Drive folder, or OneDrive / SharePoint library. OAuth for cloud providers is brokered through a self-hosted [Nango](https://nango.dev) instance (encrypted token storage, automatic refresh, REST proxy); per-source health probes; admin-scoped REST + a wizard in the web UI. Default-on; set `MEMOGRAPH_SOURCES_ENABLED=0` to opt out.
- **Multi-tenancy** with filesystem-isolated tenants, an LRU registry of warm kernels, per-tenant audit logs, and end-to-end isolation tests gating release.
- **Authentication** via OIDC (JWKS) or hashed API keys; per-route auth scope; identity bound into the audit log.
- **Web hardening** — restrictive CORS, slowapi rate limiting, request-size caps, structured JSON logging with request IDs, info-leak-free 500 handler.
- **Storage hardening** — path-traversal-safe vault writes, vault size soft/hard caps, schema-versioned cache files.
- **Scheduled deletion** for GDPR Art. 17: tombstone with configurable grace period, automatic final backup, daily reaper script, cancel-before-grace endpoint.
- **Observability** — OpenTelemetry FastAPI/asyncio auto-instrumentation, Prometheus `/metrics`, OTLP export.
- **Reliability** — concurrency audit, stress tests for concurrent writes, versioned backup format with integrity checks.
- **Distribution** — pinned-and-locked dependencies, Docker compose for self-host, security workflow (`bandit` + `pip-audit`).

> See [docs/INSTALL_ENTERPRISE.md](docs/INSTALL_ENTERPRISE.md), [docs/SSO_SETUP.md](docs/SSO_SETUP.md), [docs/SOURCES.md](docs/SOURCES.md), [docs/GDPR_RUNBOOK.md](docs/GDPR_RUNBOOK.md), [docs/BACKUP_RESTORE_RUNBOOK.md](docs/BACKUP_RESTORE_RUNBOOK.md), [docs/OBSERVABILITY_GUIDE.md](docs/OBSERVABILITY_GUIDE.md), and [docs/RBAC_GUIDE.md](docs/RBAC_GUIDE.md) for the operator-facing details.

## 🚀 Quick Start

> **Hosting it yourself?** [docs/HOSTING_GUIDE.md](docs/HOSTING_GUIDE.md)
> covers four genuinely-free paths — Oracle Free Tier, Cloudflare
> Tunnel + your hardware (recommended for most), GCP always-free
> stitch, and GitHub-repo-as-vault. Workspace identity via OIDC and
> Drive-as-portability-backup are documented in
> [docs/GOOGLE_WORKSPACE_SETUP.md](docs/GOOGLE_WORKSPACE_SETUP.md).

### Installation

```bash
pip install memograph
```

Install with optional dependencies:

```bash
# For OpenAI support
pip install memograph[openai]

# For Anthropic Claude support
pip install memograph[anthropic]

# For Ollama support
pip install memograph[ollama]

# For hosted-API embeddings (OpenAI, Cohere, Voyage etc.) — adds numpy only
pip install memograph[embeddings-api]

# For on-device embeddings via sentence-transformers — adds torch (~800 MB)
pip install memograph[embeddings-local]

# Install everything except torch (recommended starting point)
pip install memograph[all]

# Install absolutely everything, including torch
pip install memograph[all,embeddings-local]
```

### Python Usage

```python
from memograph import MemoryKernel, MemoryType

# Initialize the kernel attached to your vault path
kernel = MemoryKernel("~/my-vault")

# Ingest all notes in the vault
stats = kernel.ingest()
print(f"Indexed {stats['indexed']} memories.")

# Programmatically add a new memory
kernel.remember(
    title="Meeting Note",
    content="Decided to use BFS graph traversal for retrieval.",
    memory_type=MemoryType.EPISODIC,
    tags=["design", "retrieval"]
)

# Retrieve context for an LLM query
context = kernel.context_window(
    query="how does retrieval work?",
    tags=["retrieval"],
    depth=2,
    top_k=8
)

print(context)
```

## 🔌 MCP Server (Model Context Protocol)

MemoGraph includes a full-featured MCP server for seamless integration with AI assistants like **Cline** and **Claude Desktop**.

**📖 New to MemoGraph MCP?** See the **[MCP User Guide](docs/MCP_USER_GUIDE.md)** for practical usage instructions and examples!

**🚨 Having connection issues?** See **[Setup & Troubleshooting Guide](docs/MCP_SETUP_TROUBLESHOOTING.md)** - Common fixes for "cannot connect" errors!

### 19 Available Tools

| Category | Tools | Description |
|----------|-------|-------------|
| **Search** | `search_vault`, `query_with_context` | Semantic search and context retrieval |
| **Create** | `create_memory`, `import_document` | Add memories and import documents |
| **Read** | `list_memories`, `get_memory`, `get_vault_info` | Browse and retrieve memories |
| **Update** | `update_memory` | Modify existing memories |
| **Delete** | `delete_memory` | Remove memories by ID |
| **Analytics** | `get_vault_stats` | Vault statistics and insights |
| **Discovery** | `list_available_tools` | List all available tools |
| **Autonomous** | `auto_hook_query`, `auto_hook_response`, `configure_autonomous_mode`, `get_autonomous_config` | Autonomous memory management |
| **Graph** | `relate_memories`, `search_by_graph`, `find_path` | Graph-native linking and traversal |
| **Bulk** | `bulk_create` | Create multiple memories in one call |

### Supported Clients

MemoGraph's MCP server is a stdio server — it runs alongside any MCP-compatible agentic CLI or editor. The full setup cookbook (config-file paths, format quirks, verification steps) lives in **[docs/MCP_CLIENTS.md](docs/MCP_CLIENTS.md)**:

| Client | Format | Quick reference |
|---|---|---|
| Claude Code (CLI) | `mcpServers` | [`claude_code_config.json`](memograph/mcp/claude_code_config.json) |
| Claude Desktop | `mcpServers` | [`claude_desktop_config.json`](memograph/mcp/claude_desktop_config.json) |
| Cline | `mcp.servers` | [`cline_config.json`](memograph/mcp/cline_config.json) |
| Cursor | `mcpServers` | [`cursor_config.json`](memograph/mcp/cursor_config.json) |
| Windsurf | `mcpServers` | [`windsurf_config.json`](memograph/mcp/windsurf_config.json) |
| Continue.dev | `experimental.modelContextProtocolServers` | [`continue_config.json`](memograph/mcp/continue_config.json) |
| Zed | `context_servers` | [`zed_config.json`](memograph/mcp/zed_config.json) |
| VS Code (1.99+) | `servers` | [`vscode_config.json`](memograph/mcp/vscode_config.json) |
| Goose (Block) | YAML `extensions` | [`goose_config.yaml`](memograph/mcp/goose_config.yaml) |
| Roo Code | `mcpServers` | [`roo_code_config.json`](memograph/mcp/roo_code_config.json) |
| Gemini CLI | `mcpServers` | [`gemini_cli_config.json`](memograph/mcp/gemini_cli_config.json) |
| OpenAI Codex CLI | TOML `mcp_servers.<name>` | [`codex_config.toml`](memograph/mcp/codex_config.toml) |
| LM Studio | `mcpServers` | [`lm_studio_config.json`](memograph/mcp/lm_studio_config.json) |
| Cherry Studio | UI form | [`cherry_studio_config.json`](memograph/mcp/cherry_studio_config.json) |
| IBM Bob Shell | `mcpServers` | [`bob_shell_config.json`](memograph/mcp/bob_shell_config.json) |

### Launching the MCP server

After `pip install memograph` (or `uv tool install memograph`), three launch commands are all equivalent:

```bash
memograph-mcp                              # console script (recommended)
python -m memograph.mcp.run_server         # module form (works with any Python)
uvx --from memograph memograph-mcp         # zero-install via uv
```

`memograph-mcp` and `memograph` are both registered as console scripts: the first starts the MCP server, the second is the CLI. They do not collide.

### Read-only mode

For shared deployments or untrusted clients, set `MEMOGRAPH_READONLY=true`. The server refuses every vault-writing tool — `create_memory`, `import_document`, `update_memory`, `delete_memory`, `relate_memories`, `bulk_create`, `batch_update`, `batch_delete`, `import_backup_tool`, and the auto-save hooks — and returns a structured `{"success": false, "readonly": true, "error": "..."}` payload instead. Read tools (`search_vault`, `query_with_context`, `list_memories`, `get_memory`, analytics, graph traversal) stay fully functional.

### Quick Setup for Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "memograph": {
      "command": "memograph-mcp",
      "env": {
        "MEMOGRAPH_VAULT": "/path/to/your/vault"
      }
    }
  }
}
```

If the `memograph-mcp` binary isn't on the client's `PATH` (common when the client launches without your shell environment), use the explicit module form instead:

```json
{
  "mcpServers": {
    "memograph": {
      "command": "python",
      "args": ["-m", "memograph.mcp.run_server"],
      "env": {
        "MEMOGRAPH_VAULT": "/path/to/your/vault"
      }
    }
  }
}
```

### Quick Setup for Cline

Add to your `~/.cline/mcp_settings.json`:

```json
{
  "mcp": {
    "servers": {
      "memograph": {
        "command": "memograph-mcp",
        "env": {
          "MEMOGRAPH_VAULT": "/path/to/your/vault"
        }
      }
    }
  }
}
```

For **Claude Code, Cursor, Windsurf, Continue, Zed, VS Code, Goose, Gemini CLI, Codex CLI, LM Studio, Cherry Studio, and Bob Shell**, see **[docs/MCP_CLIENTS.md](docs/MCP_CLIENTS.md)**.

### Install from MCP Registry

**NEW**: MemoGraph is now available in the official MCP Registry! 🎉

**Registry URL**: [https://github.com/modelcontextprotocol/servers/tree/main/src/memograph](https://github.com/modelcontextprotocol/servers)

```bash
pip install memograph
```

Then drop the snippet for your client into its config file (see the table above or [docs/MCP_CLIENTS.md](docs/MCP_CLIENTS.md)).

**Benefits of MCP Registry Listing:**
- ✅ Official registry backed by Anthropic, GitHub, and Microsoft
- ✅ Discoverable by all MCP-compatible clients
- ✅ Verified server card and metadata
- ✅ Direct link from PyPI package
- ✅ Trusted by the MCP community

**Note**: The registry uses the PyPI package version. When you `pip install memograph`, you automatically get the latest registry-listed version.

See **[MCP_REGISTRY_GUIDE.md](docs/MCP_REGISTRY_GUIDE.md)** for complete submission and configuration guide.

### Usage Examples

Once configured, use natural language with your AI assistant:

```
"Search my vault for memories about Python"
"Create a memory titled 'Project Ideas' with content '...'"
"Update memory abc-123 to have salience 0.9"
"Delete memory xyz-456"
"What tools are available?"
"Get vault statistics"
```

See **[CONFIG_REFERENCE.md](memograph/mcp/CONFIG_REFERENCE.md)** for complete MCP configuration guide.

### Conversation-save hooks

MemoGraph exposes `auto_hook_query` and `auto_hook_response` MCP tools
that save conversation turns into the vault. **These are passive tools,
not server-side automation** — the AI client (Claude Desktop, Cursor,
Cline) must call them. To make that happen:

1. **Tell the client to call them.** Add to your Claude Desktop /
   Cursor / Cline custom instructions:
   > After each meaningful response, call `auto_hook_response` with the
   > original user query and your full answer.
2. **Set the env once** (optional): `MEMOGRAPH_AUTONOMOUS_MODE=true`
   keeps `auto_save_responses` enabled by default. `auto_save_queries`
   stays **off** by default to avoid filling the vault with
   acknowledgements like "ok" or "thanks"; flip it on with
   `configure_autonomous_mode` if you want every query saved.
3. **Verify**: ask the client "did you save the last response?", or run
   `verify_last_save` from the MCP tool list.

If the client doesn't have custom instructions, the hooks are inert —
the server can't force a call. This is by design: MCP tools are
request/response, not event-driven. If you need automatic capture
without client cooperation, run the optional conversation monitor
(`MEMOGRAPH_AUTO_SAVE_MONITOR=true`), which tails the client's
transcript file directly.

## 🎯 CLI Usage

MemoGraph comes with a powerful CLI for managing your vault and chatting with it.

### Ingest

Index your markdown files into the graph database:

```bash
memograph --vault ~/my-vault ingest
```

Force re-indexing all files:

```bash
memograph --vault ~/my-vault ingest --force
```

### Remember

Quickly add a memory from the command line:

```bash
memograph --vault ~/my-vault remember \
    --title "Team Sync" \
    --content "Discussed Q3 goals." \
    --tags planning q3
```

### Context Window

Generate context for a query:

```bash
memograph --vault ~/my-vault context \
    --query "What did we decide about the database?" \
    --tags architecture \
    --depth 2 \
    --top-k 5
```

### Ask (Interactive Chat)

Start an interactive chat session with your vault context:

```bash
memograph --vault ~/my-vault ask --chat --provider ollama --model llama3
```

Or ask a single question:

```bash
memograph --vault ~/my-vault ask \
    --query "Summarize our design decisions" \
    --provider claude \
    --model claude-3-5-sonnet-20240620
```

### Diagnostics

Check your environment and connection to LLM providers:

```bash
memograph --vault ~/my-vault doctor

### Import Documents

Import documents (TXT, PDF, DOCX) and convert them to markdown:

```bash
# Import a single file
memograph --vault ~/my-vault import document.pdf --type episodic

# Import entire folder
memograph --vault ~/my-vault import ~/Documents --recursive

# Preview files without importing (dry run)
memograph --vault ~/my-vault import ~/Documents --dry-run

# Auto-ingest after import
memograph --vault ~/my-vault import document.pdf --auto-ingest
```

### Batch Operations

Efficiently manage multiple memories at once:

```bash
# Bulk create memories from JSON/CSV
memograph --vault ~/my-vault batch-create memories.json

# Bulk update memories by filter
memograph --vault ~/my-vault batch-update \
    --filter-tags outdated \
    --add-tags reviewed \
    --salience 0.8

# Bulk delete with safety checks
memograph --vault ~/my-vault batch-delete \
    --filter-type episodic \
    --filter-max-salience 0.3 \
    --dry-run
```

### Data Management

Export, backup, and restore your vault:

```bash
# Export vault to JSON/CSV/Markdown
memograph --vault ~/my-vault export --format json --output backup.json

# Create timestamped backup
memograph --vault ~/my-vault backup --output ./backups

# Restore from backup
memograph --vault ~/my-vault import-backup backup.zip
```

### Configuration & Statistics

Manage settings and view vault analytics:

```bash
# View vault statistics
memograph --vault ~/my-vault stats

# Configure settings
memograph config set embedding_provider openai
memograph config get embedding_provider
memograph config list

# Manage profiles
memograph config profile create work --vault ~/work-vault
memograph config profile use work
```

### MCP Setup

Interactive wizard to configure MCP server for Claude Desktop or Cline:

```bash
# Run interactive setup wizard
memograph setup-mcp

# Verify MCP configuration
memograph verify-mcp
```

**📖 Complete CLI Documentation:** See **[CLI Usage Guide](MEMOGRAPH_CLI_USAGE_GUIDE.md)** for detailed documentation with 200+ examples covering all 24 commands.

### 🤖 AI Features

MemoGraph includes powerful AI-powered features to enhance your knowledge management workflow. See **[AI Features Guide](docs/guides/AI_FEATURES.md)** for complete documentation.

#### 🏷️ AutoTagger - Intelligent Tag Suggestions

Automatically suggest relevant tags using semantic analysis, content structure, and existing patterns:

```bash
# Suggest tags for a note
memograph suggest-tags note.md

# Apply high-confidence suggestions automatically
memograph suggest-tags note.md --apply

# Adjust confidence threshold and limit
memograph suggest-tags note.md --min-confidence 0.5 --max-suggestions 10
```

**Features:** Frequency-based extraction • Semantic similarity • Structure detection • Pattern learning • Confidence scoring

#### 🔗 LinkSuggester - Smart Wikilink Recommendations

Intelligently recommend wikilinks to related notes using semantic similarity and graph analysis:

```bash
# Suggest links for a note
memograph suggest-links note.md

# Apply suggestions automatically
memograph suggest-links note.md --apply

# Show bidirectional link opportunities
memograph suggest-links note.md --show-bidirectional
```

**Features:** Semantic search • Keyword matching • Graph-based suggestions • Bidirectional detection • Target previews

#### 🔍 GapDetector - Knowledge Base Analysis

Identify missing topics, weak coverage, and isolated notes in your vault:

```bash
# Detect all gaps
memograph detect-gaps

# Focus on high-severity gaps
memograph detect-gaps --min-severity 0.7

# Export results to JSON
memograph detect-gaps --output json > gaps.json
```

**Gap Types:** Missing Topics • Weak Coverage • Isolated Notes • Missing Links

#### 📊 Knowledge Analysis - Comprehensive Insights

Get comprehensive analysis of your entire knowledge base:

```bash
# Full analysis with all features
memograph analyze-knowledge

# Export detailed report to JSON
memograph analyze-knowledge --output json > analysis.json
```

**Analysis Includes:** Vault statistics • Topic clustering • Learning paths • Gap detection • Connection analysis

#### Python API for AI Features

```python
from memograph import MemoryKernel
from memograph.ai import AutoTagger, LinkSuggester, GapDetector

kernel = MemoryKernel("~/my-vault")
kernel.ingest()

# Get tag suggestions
tagger = AutoTagger(kernel, min_confidence=0.4)
suggestions = await tagger.suggest_tags(
    content="Python is great for data science",
    title="Data Science with Python"
)

# Get link suggestions
suggester = LinkSuggester(kernel, min_confidence=0.5)
links = await suggester.suggest_links(
    content="Python async programming tutorial",
    title="Async Python"
)

# Detect knowledge gaps
detector = GapDetector(kernel, min_severity=0.5)
gaps = await detector.detect_gaps()

# Comprehensive analysis
analysis = await detector.analyze_knowledge_base()
```

**📖 Complete Documentation:**
- **[AI Features Guide](docs/guides/AI_FEATURES.md)** - Comprehensive guide with examples
- **[Web UI Guide](docs/guides/WEB_UI_GUIDE.md)** - Using AI features in the browser
- **[MCP AI Tools Guide](docs/guides/MCP_AI_TOOLS.md)** - AI features for Claude & Cline

**💡 Use Cases:** Auto-organize notes • Discover connections • Identify gaps • Maintain consistency • Build learning paths

## 📖 Core Concepts

### Memory Types

MemoGraph supports different types of memories inspired by cognitive science:

- **Episodic**: Personal experiences and events (e.g., meeting notes)
- **Semantic**: Facts and general knowledge (e.g., documentation)
- **Procedural**: How-to knowledge and processes (e.g., tutorials)
- **Fact**: Discrete factual information (e.g., configuration values)

### Graph Traversal

The library uses BFS (Breadth-First Search) to traverse your knowledge graph:

```python
# Retrieve nodes with depth=2 (2 hops from seed nodes)
nodes = kernel.retrieve_nodes(
    query="graph algorithms",
    depth=2,  # Traverse up to 2 levels deep
    top_k=10  # Return top 10 relevant memories
)
```

### Salience Scoring

Each memory has a salience score (0.0-1.0) that represents its importance:

```yaml
---
title: "Critical Architecture Decision"
salience: 0.9
memory_type: semantic
---

We decided to use PostgreSQL for better ACID guarantees...
```

## 🏗️ Project Structure

```
MemoGraph/
├── memograph/          # Main package
│   ├── core/           # Core functionality
│   │   ├── kernel.py   # Memory kernel
│   │   ├── graph.py    # Graph implementation
│   │   ├── retriever.py # Hybrid retrieval
│   │   ├── indexer.py  # File indexing
│   │   └── parser.py   # Markdown parsing
│   ├── adapters/       # LLM and embedding adapters
│   │   ├── embeddings/ # Embedding providers
│   │   ├── frameworks/ # Framework integrations
│   │   └── llm/        # LLM providers
│   ├── storage/        # Storage and caching
│   ├── mcp/            # MCP server implementation
│   └── cli.py          # CLI implementation
├── tests/              # Test suite
├── examples/           # Example usage
└── scripts/            # Utility scripts
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/Indhar01/MemoGraph.git
   cd MemoGraph
   ```

2. Install in development mode:
   ```bash
   pip install -e ".[all,dev]"
   ```

3. Install pre-commit hooks:
   ```bash
   pre-commit install
   ```

4. Run tests:
   ```bash
   pytest
   ```

### Code Quality

We maintain high code quality standards:

- **Linting**: Ruff for fast Python linting
- **Formatting**: Ruff formatter for consistent code style
- **Type Checking**: MyPy for static type analysis
- **Testing**: Pytest with comprehensive test coverage
- **Pre-commit Hooks**: Automated checks before each commit

## 📚 Documentation

### Getting Started

- **[Hosting Guide](docs/HOSTING_GUIDE.md)** - 💸 **Free hosting options** (Oracle Free Tier, Cloudflare Tunnel, GCP, GitHub-vault) with hardening checklist
- **[Google Workspace Setup](docs/GOOGLE_WORKSPACE_SETUP.md)** - 🔐 OIDC identity + Drive portability backup
- **[MCP Clients Guide](docs/MCP_CLIENTS.md)** - 🔌 **Setup snippets for 15+ agentic CLIs/editors** (Claude Code, Cursor, Windsurf, Continue, Zed, VS Code, Goose, Gemini CLI, Codex CLI, LM Studio, …)
- **[MCP User Guide](docs/MCP_USER_GUIDE.md)** - ⭐ **Start here!** Complete guide for using MemoGraph MCP
- **[Setup & Troubleshooting](docs/MCP_SETUP_TROUBLESHOOTING.md)** - 🚨 **Can't connect?** Step-by-step fixes for connection issues
- **[MCP Testing Guide](docs/MCP_TESTING_GUIDE.md)** - Testing your MCP server after setup

### For Developers & Contributors
- **[MCP Registry Guide](docs/MCP_REGISTRY_GUIDE.md)** - Publishing to official MCP Registry
- **[Versioning Strategy](docs/VERSIONING.md)** - Semantic versioning and release planning
- **[AGENTS.md](AGENTS.md)** - Guide for AI agents working with this codebase
- **[Contributing Guide](CONTRIBUTING.md)** - How to contribute to the project
- **[Code of Conduct](CODE_OF_CONDUCT.md)** - Community guidelines
- **[Security Policy](SECURITY.md)** - Security reporting and best practices
- **[Changelog](CHANGELOG.md)** - Version history and changes

### Community & Distribution (for amplifiers, partners, and contributors)

- **[Launch Playbook](docs/community/LAUNCH_PLAYBOOK.md)** - 🚀 Free, no-PR-firm launch sequence (Show HN, ProductHunt, Reddit, dev.to)
- **[Paper Launch Playbook](docs/community/PAPER_LAUNCH.md)** - 📄 arXiv + TMLR + Papers With Code + ML Twitter sequence
- **[Awesome-list submissions](docs/community/AWESOME_SUBMISSIONS.md)** - 📋 Exact entries to file at each awesome-mcp-servers list
- **[Community setup](docs/community/COMMUNITY.md)** - 💬 Discord / GitHub Discussions / moderation playbook
- **[Hugging Face demo deployment](deploy/huggingface/SETUP.md)** - ▶️ Step-by-step to stand up the public read-only demo
- **[Demo GIF capture script](docs/DEMO_GIF_CAPTURE.md)** - 🎬 Script for the 60-second README GIF
- **[Benchmarks](BENCHMARKS.md)** - 📊 Headline numbers + reproduction harness pointer

## 🔒 Security

See our [Security Policy](SECURITY.md) for reporting vulnerabilities.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🌟 Acknowledgments

Inspired by the need for better memory management in LLM applications. Built with:

- Graph-based knowledge representation
- Hybrid retrieval strategies
- Cognitive science principles

## 📬 Contact & Support

- **Issues**: [GitHub Issues](https://github.com/Indhar01/MemoGraph/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Indhar01/MemoGraph/discussions)

## 📣 Community & Feedback

We value community feedback and contributions! Here's how to get involved:

### Report Issues
Found a bug or have a feature request? [Open an issue](https://github.com/Indhar01/MemoGraph/issues/new) on GitHub.

### Discussions
Join the conversation in [GitHub Discussions](https://github.com/Indhar01/MemoGraph/discussions):
- Ask questions
- Share use cases
- Suggest improvements
- Show what you've built

### Contributing
We welcome contributions! See our [Contributing Guide](CONTRIBUTING.md) for details on:
- Code contributions
- Documentation improvements
- Bug reports and feature requests
- Community support

### Stay Updated
- ⭐ Star the repository on [GitHub](https://github.com/Indhar01/MemoGraph)
- 👁️ Watch for updates and releases
- 📦 Follow the project on [PyPI](https://pypi.org/project/memograph/)
- 🔗 Check out the [MCP Registry listing](https://github.com/modelcontextprotocol/servers/tree/main/src/memograph)

## 🚦 Status

**Current version**: 0.3.0

Single-tenant deployments are stable and recommended for production use.
Multi-tenant deployments are feature-complete with end-to-end isolation
tests gating the release; the public API will stabilise at v1.0.

- ✅ Core functionality stable and tested (172+ tests across security, contract, and tenancy suites)
- ✅ Whole-package type-checked with MyPy
- ✅ Ruff lint + format + pre-commit hooks
- ✅ OpenAPI v1 contract snapshot in CI
- ✅ Multi-tenant isolation invariants verified by an e2e test suite
- ⚠️ Public API may change in minor versions until v1.0.0

### What landed recently

- **Phase 3.7** — GDPR-compliant scheduled tenant deletion: tombstone-with-grace-period, daily reaper, automatic final backups.
- **Phase 3.5** — `TenantRegistry` wired into the request path; non-admin routes resolve their kernel per-tenant.
- **Phase 3 scaffold** — multi-tenancy ADR, `TenantStorage`, `TenantRegistry`, admin routes for tenant lifecycle.
- **Phase 2** — OpenTelemetry + Prometheus, structured JSON logging, concurrency audit, stress tests.
- **Phase 1** — OIDC + API-key auth, slowapi rate limiting, restrictive CORS, request-size caps, vault size caps, schema-versioned caches, OpenAPI v1 contract, security test suite.
- **Phase 0** — path-traversal-safe vault writes, info-leak-free error handlers, pinned dependencies, Docker compose, security CI workflow.
- 📦 **Published to the official MCP Registry** ([io.github.indhar01/memograph](https://github.com/modelcontextprotocol/servers/tree/main/src/memograph))

---

Made with ❤️ for better LLM memory management
