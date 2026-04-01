# MCP Roadmap

MCP server implementation status for MemoGraph.

## Current State

19 tools + Resources + Prompts. Uses all 3 MCP capabilities. Official `mcp` SDK with stdio transport. Supports Claude Desktop, Cline, and any MCP-compatible client.

### Tools (19)

| Category | Tools | Status |
|----------|-------|--------|
| **Search** | `search_vault`, `query_with_context` | Done |
| **Create** | `create_memory`, `import_document`, `bulk_create` | Done |
| **Read** | `list_memories`, `get_memory`, `get_vault_info`, `get_vault_stats` | Done |
| **Update** | `update_memory` | Done |
| **Delete** | `delete_memory` | Done |
| **Graph** | `relate_memories`, `search_by_graph`, `find_path` | Done |
| **Discovery** | `list_available_tools` | Done |
| **Autonomous** | `auto_hook_query`, `auto_hook_response`, `configure_autonomous_mode`, `get_autonomous_config` | Done |

### Resources

| URI Pattern | Description | Status |
|-------------|-------------|--------|
| `memograph://vault/{memory_id}` | Browse individual memories as markdown | Done |
| `memograph://tag/{tag}` | List memories by tag | Done |

### Prompts

| Name | Description | Status |
|------|-------------|--------|
| `vault-summary` | Summarize entire vault with stats and themes | Done |
| `recall` | Recall knowledge about a topic (parameterized) | Done |
| `weekly-review` | Review recent memories | Done |
| `find-connections` | Find connections between two topics | Done |

---

## Completed Bug Fixes

All 8 P0 bugs fixed:

1. ~~Missing tool routing for autonomous tools~~ — Added to `handle_call_tool()`
2. ~~No auto-ingest on startup~~ — Added `kernel.ingest()` in `__init__`
3. ~~`delete_memory` bypasses graph~~ — Uses `graph.remove_node()`
4. ~~`server_enhanced.py` dead code~~ — Deleted
5. ~~`cline_config.json` stale comment~~ — Updated to 19 tools
6. ~~Zero MCP tests~~ — 43 tests written
7. ~~`import_document` broken import~~ — Replaced with direct file reading
8. ~~Hardcoded server version~~ — Uses `memograph.__version__`

---

## Remaining Work

### MCP Notifications
Send `resources/updated` notifications when memories change so AI clients stay in sync without re-polling. The MCP SDK supports `ResourceUpdatedNotification`.

### Smithery Listing
Update the Smithery listing to reflect 19 tools + Resources + Prompts. Verify `npx @smithery/cli install @indhar01/memograph` works.

### SSE Transport
Currently stdio-only. Adding SSE transport would enable remote/web-based MCP clients.
