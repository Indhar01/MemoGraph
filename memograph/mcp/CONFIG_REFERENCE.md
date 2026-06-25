
# MemoGraph MCP Configuration Reference

Complete reference for configuring MemoGraph MCP server with various AI assistants and clients.

## Table of Contents

- [Quick Start](#quick-start)
- [Configuration File Locations](#configuration-file-locations)
- [Basic Configuration Structure](#basic-configuration-structure)
- [Core Parameters](#core-parameters)
- [Environment Variables](#environment-variables)
- [Client-Specific Configuration](#client-specific-configuration)
- [Advanced Configuration](#advanced-configuration)
- [Configuration Examples](#configuration-examples)

## Quick Start

**Minimal Configuration (Cline):**

```json
{
  "mcp": {
    "servers": {
      "memograph": {
        "command": "python",
        "args": ["-m", "memograph.mcp.run_server"],
        "env": {
          "MEMOGRAPH_VAULT": "/path/to/your/vault"
        }
      }
    }
  }
}
```

**Minimal Configuration (Claude Desktop):**

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

## Configuration File Locations

### Claude Desktop

**macOS:**
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

**Windows:**
```
%APPDATA%/Claude/claude_desktop_config.json
```

**Linux:**
```
~/.config/Claude/claude_desktop_config.json
```

### Cline (VS Code Extension)

**Primary Location:**
```
~/.cline/mcp_settings.json
```

**Alternative Location:**
```
~/.config/cline/mcp_settings.json
```

**Global VS Code Settings:**
```
%APPDATA%/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json
```

### Bob Shell

```
~/.bob/mcp_settings.json
```

### Creating Config Files

If the config file doesn't exist:

```bash
# macOS/Linux
mkdir -p ~/.cline
touch ~/.cline/mcp_settings.json

# Windows (PowerShell)
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.cline"
New-Item -ItemType File -Force -Path "$env:USERPROFILE\.cline\mcp_settings.json"
```

## Basic Configuration Structure

### Cline/Bob Format

```json
{
  "mcp": {
    "servers": {
      "server-name": {
        "command": "executable",
        "args": ["arg1", "arg2"],
        "env": {
          "VAR_NAME": "value"
        }
      }
    }
  }
}
```

### Claude Desktop Format

```json
{
  "mcpServers": {
    "server-name": {
      "command": "executable",
      "args": ["arg1", "arg2"],
      "env": {
        "VAR_NAME": "value"
      }
    }
  }
}
```

**Key Difference:** `mcp.servers` vs `mcpServers` at the root level.

## Core Parameters

### `command` (Required)

The executable to run the MCP server.

**Options:**

1. **Simple Python command** (requires memograph in PATH):
   ```json
   "command": "python"
   ```

2. **Python 3 specifically**:
   ```json
   "command": "python3"
   ```

3. **Full Python path** (recommended for reliability):
   ```json
   "command": "/usr/local/bin/python3"
   "command": "C:/Users/You/AppData/Local/Programs/Python/Python311/python.exe"
   ```

4. **Wrapper script** (recommended, created by [`setup_mcp.py`](../../scripts/setup_mcp.py:1)):
   ```json
   "command": "/path/to/project/run_memograph_mcp.sh"
   "command": "C:/path/to/project/run_memograph_mcp.bat"
   ```

**Platform-Specific Examples:**

| Platform | Typical Path |
|----------|-------------|
| macOS (Homebrew) | `/usr/local/bin/python3` |
| macOS (system) | `/usr/bin/python3` |
| Windows | `C:/Python311/python.exe` |
| Linux (system) | `/usr/bin/python3` |
| Conda | `~/anaconda3/bin/python` |
| venv | `./venv/bin/python` |

### `args` (Required)

Arguments passed to the command.

**Standard Configuration:**
```json
"args": ["-m", "memograph.mcp.run_server"]
```

**With Vault Parameter:**
```json
"args": [
  "-m", "memograph.mcp.run_server",
  "--vault", "/path/to/vault"
]
```

**With All Parameters:**
```json
"args": [
  "-m", "memograph.mcp.run_server",
  "--vault", "/path/to/vault",
  "--provider", "ollama",
  "--model", "llama3",
  "--log-level", "INFO"
]
```

**Available Arguments:**

| Argument | Type | Description | Default |
|----------|------|-------------|---------|
| `--vault` | string | Vault directory path | `$MEMOGRAPH_VAULT` or `~/my-vault` |
| `--provider` | enum | LLM provider (`ollama`, `claude`) | None |
| `--model` | string | Model name | Provider default |
| `--log-level` | enum | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |

### `env` (Required)

Environment variables for the server process.

**Minimal:**
```json
"env": {
  "MEMOGRAPH_VAULT": "/path/to/vault"
}
```

**Full:**
```json
"env": {
  "MEMOGRAPH_VAULT": "/Users/you/Documents/memograph-vault",
  "MEMOGRAPH_PROVIDER": "ollama",
  "MEMOGRAPH_MODEL": "llama3",
  "MEMOGRAPH_AUTONOMOUS_MODE": "true",
  "MEMOGRAPH_LOG_LEVEL": "DEBUG",
  "CARD_SERVER_PORT": "8080"
}
```

## Environment Variables

### `MEMOGRAPH_VAULT` (Required)

Path to your MemoGraph vault directory containing markdown files.

**Format:** Absolute path (recommended)

**Examples:**
```bash
# macOS/Linux
MEMOGRAPH_VAULT=/Users/you/Documents/my-vault
MEMOGRAPH_VAULT=~/knowledge-base

# Windows (in JSON, use forward slashes or escaped backslashes)
MEMOGRAPH_VAULT=C:/Users/You/Documents/my-vault
MEMOGRAPH_VAULT=C:\\Users\\You\\Documents\\my-vault
```

**Tips:**
- Use absolute paths for reliability
- Create directory before first run
- Ensure write permissions
- No trailing slash

### `MEMOGRAPH_PROVIDER` (Optional)

LLM provider for [`query_with_context()`](server.py:412) tool when generating answers.

**Values:**
- `ollama` - Use local Ollama instance
- `claude` - Use Anthropic Claude API
- `openai` - Use OpenAI API (requires `memograph[openai]`)
- Omit - Client manages all LLM interactions (recommended)

**Default:** None (client-managed mode)

**Example:**
```json
"MEMOGRAPH_PROVIDER": "ollama"
```

**Notes:**
- Only needed if you want server to generate answers
- Most users should omit this (let client handle responses)
- Requires additional setup (API keys, Ollama installation)

### `MEMOGRAPH_MODEL` (Optional)

Specific model name override for the LLM provider.

**Examples:**
```json
"MEMOGRAPH_MODEL": "llama3"          // Ollama
"MEMOGRAPH_MODEL": "claude-3-opus"   // Claude
"MEMOGRAPH_MODEL": "gpt-4"           // OpenAI
```

**Default:** Provider-specific default model

**Notes:**
- Only used if `MEMOGRAPH_PROVIDER` is set
- Model must be available/pulled for the provider

### `MEMOGRAPH_AUTONOMOUS_MODE` (Optional)

Configure autonomous hooks behavior (pre-configure settings for auto-search and auto-save).

**⚠️ IMPORTANT**: This does NOT make hooks automatic. The AI assistant must still explicitly call the hook tools. This setting only changes the DEFAULT configuration.

> **🚨 AUTO-SAVE NOT WORKING?**
>
> If you expected conversations to be automatically saved but they're not:
> - **See:** [Autonomous Hooks Troubleshooting Guide](../../docs/AUTONOMOUS_HOOKS_TROUBLESHOOTING.md)
> - **Quick Fix:** [Claude Desktop Custom Instructions Templates](../../docs/CLAUDE_DESKTOP_CUSTOM_INSTRUCTIONS.md)
>
> **Root Cause:** MCP protocol doesn't support automatic hooks - Claude must explicitly call the save tool.
> **Solution:** Use custom instructions to make Claude consistently call it.

**Values:**
- `true` - Enable auto-search and auto-save by default
- `false` or omit - Disable by default

**Default:** `false`

**Example:**
```json
"MEMOGRAPH_AUTONOMOUS_MODE": "true"
```

**What it actually does:**
- Sets `auto_search_enabled = true` (searches vault when [`auto_hook_query`](../autonomous_hooks.py:54) is called)
- Sets `auto_save_responses = true` (saves conversation when [`auto_hook_response`](../autonomous_hooks.py:183) is called)
- Does **NOT** automatically trigger these hooks - the AI must still call them explicitly

**To make conversation saving work automatically:**
1. Set this to `true` (enables save when hook is called)
2. Add custom instructions to Claude Desktop (makes Claude call the hook after each response)
3. **Use ready-to-use templates:** [Claude Desktop Custom Instructions](../../docs/CLAUDE_DESKTOP_CUSTOM_INSTRUCTIONS.md)
4. **If issues persist:** [Troubleshooting Guide](../../docs/AUTONOMOUS_HOOKS_TROUBLESHOOTING.md)

**Related Documentation:**

- Conversation-save hooks setup — see the **Conversation-save hooks**
  section in the [project README](../../README.md#conversation-save-hooks).
- Troubleshooting — open an issue with the `conversation-hooks` label.

### `MEMOGRAPH_AUTO_SAVE_MONITOR` (Phase 2)

**Type:** Boolean (true/false)
**Default:** false
**Recommended:** true (after Phase 1 is tested)
**Phase:** 2 (Server-side Monitor)

**What it does:**

Enables Layer 2 of the hybrid auto-save system - a background server-side monitor that automatically detects and saves conversations that were missed by Layer 1 (explicit AI saves).

**How it works:**

1. **Pattern Detection:** Monitors MCP tool usage for conversation patterns:
   - `search_vault` → `query_with_context` (high confidence)
   - Multiple `query_with_context` calls (medium confidence)
   - `query_with_context` → `create_memory` (low confidence)

2. **Smart Buffering:** Detected exchanges are buffered in memory

3. **Idle Detection:** After 30s of inactivity, buffered exchanges are saved

4. **Duplicate Prevention:** Coordinates with Layer 1 to avoid duplicate saves

**Performance Impact:**
- CPU: <5% overhead
- Memory: ~50MB for buffer
- Disk: Additional conversation files

**Configuration Options:**

```json
{
  "env": {
    "MEMOGRAPH_AUTO_SAVE_MONITOR": "true",
    "MEMOGRAPH_IDLE_THRESHOLD": "30",
    "MEMOGRAPH_MIN_QUESTION_LENGTH": "10",
    "MEMOGRAPH_MAX_BUFFER_SIZE": "50",
    "MEMOGRAPH_CHECK_INTERVAL": "5"
  }
}
```

**Environment Variables:**

- `MEMOGRAPH_IDLE_THRESHOLD`: Seconds of inactivity before saving (default: 30)
- `MEMOGRAPH_MIN_QUESTION_LENGTH`: Minimum question length to detect (default: 10)
- `MEMOGRAPH_MAX_BUFFER_SIZE`: Maximum exchanges to buffer (default: 50)
- `MEMOGRAPH_CHECK_INTERVAL`: How often to check for saves (default: 5)

**When to Enable:**

✅ Enable if:
- You want 94%+ save rate
- Phase 1 is working (70% baseline)
- You can afford 50MB memory overhead
- You want automatic backup saves

❌ Disable if:
- Resource-constrained environment
- Phase 1 is sufficient for your needs
- You prefer manual control only

**Related:**
- [Phase 2 Architecture](../../docs/AUTO_SAVE_ARCHITECTURE_PLAN_PART2.md)
- [ConversationMonitor Implementation](../../memograph/mcp/conversation_monitor.py)

### `MEMOGRAPH_LOG_LEVEL` (Optional)

Logging verbosity level.

**Values:**
- `DEBUG` - Detailed debug information
- `INFO` - General informational messages (default)
- `WARNING` - Warning messages only
- `ERROR` - Error messages only

**Default:** `INFO`

**Example:**
```json
"MEMOGRAPH_LOG_LEVEL": "DEBUG"
```

**Use cases:**
- `DEBUG` - Troubleshooting issues, development
- `INFO` - Normal operation
- `WARNING` - Production, reduce noise
- `ERROR` - Production, errors only

### `CARD_SERVER_PORT` (Optional)

Port for the MCP server card HTTP server (metadata endpoint).

**Values:** Integer port number (1024-65535)

**Default:** `8080`

**Example:**
```json
"CARD_SERVER_PORT": "8888"
```

**Notes:**
- Rarely needs changing
- Only relevant for server card/metadata serving
- Server still works if port is occupied (non-fatal)

## Client-Specific Configuration

### Claude Desktop Configuration

**File:** `claude_desktop_config.json`

**Complete Example:**

```json
{
  "mcpServers": {
    "memograph": {
      "command": "/usr/local/bin/python3",
      "args": ["-m", "memograph.mcp.run_server"],
      "env": {
        "MEMOGRAPH_VAULT": "/Users/you/Documents/memograph-vault"
      }
    }
  }
}
```

**Multiple Servers:**

```json
{
  "mcpServers": {
    "memograph": {
      "command": "python",
      "args": ["-m", "memograph.mcp.run_server"],
      "env": {
        "MEMOGRAPH_VAULT": "/Users/you/work-vault"
      }
    },
    "memograph-personal": {
      "command": "python",
      "args": ["-m", "memograph.mcp.run_server"],
      "env": {
        "MEMOGRAPH_VAULT": "/Users/you/personal-vault"
      }
    }
  }
}
```

### Cline Configuration

**File:** `~/.cline/mcp_settings.json`

**Complete Example:**

```json
{
  "mcp": {
    "servers": {
      "memograph": {
        "command": "/usr/local/bin/python3",
        "args": ["-m", "memograph.mcp.run_server"],
        "env": {
          "MEMOGRAPH_VAULT": "/Users/you/Documents/memograph-vault",
          "MEMOGRAPH_LOG_LEVEL": "INFO"
        }
      }
    }
  }
}
```

**Development Configuration:**

```json
{
  "mcp": {
    "servers": {
      "memograph-dev": {
        "command": "/Users/you/projects/MemoGraph/.venv/bin/python",
        "args": ["-m", "memograph.mcp.run_server"],
        "env": {
          "MEMOGRAPH_VAULT": "/Users/you/test-vault",
          "MEMOGRAPH_LOG_LEVEL": "DEBUG",
          "MEMOGRAPH_AUTONOMOUS_MODE": "true"
        }
      }
    }
  }
}
```

### Bob Shell Configuration

**File:** `~/.bob/mcp_settings.json`

**Format:** Same as Cline (uses `mcp.servers` structure)

```json
{
  "mcp": {
    "servers": {
      "memograph": {
        "command": "python3",
        "args": ["-m", "memograph.mcp.run_server"],
        "env": {
          "MEMOGRAPH_VAULT": "~/Documents/bob-vault"
        }
      }
    }
  }
}
```

## Advanced Configuration

### Multiple Vaults

Configure multiple MemoGraph instances for different vaults:

```json
{
  "mcpServers": {
    "work-vault": {
      "command": "python",
      "args": ["-m", "memograph.mcp.run_server"],
      "env": {
        "MEMOGRAPH_VAULT": "/Users/you/work-vault"
      }
    },
    "personal-vault": {
      "command": "python",
      "args": ["-m", "memograph.mcp.run_server"],
      "env": {
        "MEMOGRAPH_VAULT": "/Users/you/personal-vault"
      }
    },
    "research-vault": {
      "command": "python",
      "args": ["-m", "memograph.mcp.run_server"],
      "env": {
        "MEMOGRAPH_VAULT": "/Users/you/research-vault",
        "MEMOGRAPH_AUTONOMOUS_MODE": "true"
      }
    }
  }
}
```

**Usage:**
The client will present each vault as a separate MCP server with distinct tools.

### Using Virtual Environments

**Recommended for development:**

```json
{
  "command": "/full/path/to/project/.venv/bin/python",
  "args": ["-m", "memograph.mcp.run_server"],
  "env": {
    "MEMOGRAPH_VAULT": "/path/to/vault"
  }
}
```

**Windows:**
```json
{
  "command": "C:/Projects/MemoGraph/.venv/Scripts/python.exe",
  "args": ["-m", "memograph.mcp.run_server"],
  "env": {
    "MEMOGRAPH_VAULT": "C:/Users/You/vault"
  }
}
```

### Wrapper Script Configuration

**Using setup_mcp.py-generated wrapper:**

```json
{
  "command": "/Users/you
