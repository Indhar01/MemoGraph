"""MCP Setup and Configuration Wizard.

This module provides automated setup, detection, and configuration
for MemoGraph MCP integration with various clients.
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


class MCPClient:
    """Represents an MCP client that can be configured."""

    def __init__(self, name: str, config_path: Path, detected: bool = False):
        self.name = name
        self.config_path = config_path
        self.detected = detected

    def __repr__(self):
        status = "✓" if self.detected else "✗"
        return f"{self.name} ({status})"


class MCPSetup:
    """Automated MCP setup wizard."""

    def __init__(self, vault_path: str | None = None):
        self.vault_path = vault_path
        self.system = platform.system()
        self.clients: list[MCPClient] = []

    def detect_clients(self) -> list[MCPClient]:
        """Detect installed MCP clients."""
        clients = []

        # Detect Claude Desktop
        claude_config = self._get_claude_config_path()
        if claude_config:
            clients.append(
                MCPClient(
                    "Claude Desktop",
                    claude_config,
                    detected=claude_config.parent.exists(),
                )
            )

        # Detect Cursor (user-scoped config; project-scoped is opt-in)
        cursor_config = self._get_cursor_config_path()
        if cursor_config:
            clients.append(
                MCPClient(
                    "Cursor",
                    cursor_config,
                    detected=cursor_config.parent.exists(),
                )
            )

        # Detect Cline CLI
        cline_config = self._get_cline_config_path()
        if cline_config:
            clients.append(
                MCPClient(
                    "Cline CLI",
                    cline_config,
                    detected=cline_config.parent.exists()
                    or self._check_cline_installed(),
                )
            )

        # Detect VS Code Cline Extension
        vscode_cline = self._get_vscode_cline_config_path()
        if vscode_cline:
            clients.append(
                MCPClient(
                    "VS Code Cline Extension",
                    vscode_cline,
                    detected=vscode_cline.parent.exists(),
                )
            )

        self.clients = clients
        return clients

    def _get_claude_config_path(self) -> Path | None:
        """Get Claude Desktop config path based on OS."""
        if self.system == "Darwin":  # macOS
            return (
                Path.home()
                / "Library/Application Support/Claude/claude_desktop_config.json"
            )
        elif self.system == "Windows":
            appdata = os.environ.get("APPDATA")
            if appdata:
                return Path(appdata) / "Claude/claude_desktop_config.json"
        elif self.system == "Linux":
            return Path.home() / ".config/Claude/claude_desktop_config.json"
        return None

    def _get_cursor_config_path(self) -> Path | None:
        """Get the user-scoped Cursor MCP config path.

        Cursor reads ``~/.cursor/mcp.json`` for user-scoped MCP
        servers (the same ``mcpServers`` shape Claude Desktop uses).
        Project-scoped configs at ``<project>/.cursor/mcp.json``
        are out of scope here — quickstart targets the global
        editor, not the project the user happens to be cd'd into.
        """
        return Path.home() / ".cursor" / "mcp.json"

    def _get_cline_config_path(self) -> Path | None:
        """Get Cline CLI config path."""
        # Try common locations
        paths = [
            Path.home() / ".cline/mcp_settings.json",
            Path.home() / ".config/cline/mcp_settings.json",
        ]

        # Return first existing parent dir, or first path as default
        for path in paths:
            if path.parent.exists():
                return path

        return paths[0]  # Default to first path

    def _get_vscode_cline_config_path(self) -> Path | None:
        """Get VS Code Cline extension config path."""
        if self.system == "Darwin":
            base = Path.home() / "Library/Application Support/Code/User"
        elif self.system == "Windows":
            appdata = os.environ.get("APPDATA")
            if appdata:
                base = Path(appdata) / "Code/User"
            else:
                return None
        elif self.system == "Linux":
            base = Path.home() / ".config/Code/User"
        else:
            return None

        return base / "settings.json"

    def _check_cline_installed(self) -> bool:
        """Check if Cline CLI is installed."""
        try:
            result = subprocess.run(
                ["cline", "--version"], capture_output=True, timeout=2
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def quickstart_setup(
        self,
        vault_path: str,
        *,
        apply: bool = False,
        provider: str = "ollama",
        model: str | None = None,
    ) -> dict[str, Any]:
        """Non-interactive wire-up for the quickstart flow.

        Detects installed MCP clients and either previews (default)
        or writes (``apply=True``) the config snippet to make
        MemoGraph available to each one. Returns a result dict
        suitable for printing back to the user.

        Distinct from :meth:`interactive_setup` in three ways:

        1. **No prompts.** Designed to run inline right after
           ``memograph quickstart`` finishes its demo — every
           interactive prompt is a new chance for the user to
           bounce.
        2. **Detected-only by default.** We only touch clients
           that already have a config directory on disk. A user
           who hasn't installed Cursor doesn't get a Cursor
           config dropped into their home.
        3. **Preview-first.** Default ``apply=False`` prints what
           *would* happen and leaves the filesystem alone. The
           user explicitly opts in with ``--apply``.

        Returns a dict with:

        - ``detected``: list of detected client names
        - ``actions``: per-client ``{client, config_path, status,
          message}`` — status is ``"would_write"`` in preview mode
          or ``"written"`` / ``"skipped"`` / ``"error"`` in apply mode
        - ``not_detected``: clients we know about that weren't found
        """
        if not self.clients:
            self.detect_clients()

        result: dict[str, Any] = {
            "detected": [],
            "actions": [],
            "not_detected": [],
        }

        client_config = {
            "vault_path": vault_path,
            "provider": provider,
        }
        if model:
            client_config["model"] = model

        for client in self.clients:
            if not client.detected:
                result["not_detected"].append(client.name)
                continue
            result["detected"].append(client.name)
            action: dict[str, Any] = {
                "client": client.name,
                "config_path": str(client.config_path),
                "status": "would_write" if not apply else "written",
                "message": "",
            }
            if not apply:
                action["message"] = (
                    f"Would write MemoGraph MCP server config to "
                    f"{client.config_path}. Run with --mcp-apply to do it."
                )
                result["actions"].append(action)
                continue

            try:
                self._configure_client(client, client_config)
                action["message"] = (
                    f"Wired MemoGraph into {client.name}. "
                    f"Restart {client.name} to pick up the change."
                )
            except Exception as exc:  # noqa: BLE001
                action["status"] = "error"
                action["message"] = f"Failed to write config: {exc}"
            result["actions"].append(action)

        return result

    def interactive_setup(self) -> dict[str, Any]:
        """Run interactive setup wizard."""
        print("🔧 MemoGraph MCP Setup Wizard")
        print("=" * 50)

        # Detect clients
        print("\n📡 Detecting MCP clients...")
        clients = self.detect_clients()

        if not clients:
            print("❌ No MCP clients detected.")
            print("\nPlease install one of the following:")
            print("  - Claude Desktop")
            print("  - Cline CLI")
            print("  - VS Code with Cline extension")
            return {}

        print(f"\n✓ Found {len(clients)} potential client(s):")
        for i, client in enumerate(clients, 1):
            status = "Detected" if client.detected else "Not found"
            print(f"  [{i}] {client.name} - {status}")

        # Select clients
        print("\n📋 Which client(s) do you want to configure?")
        print(f"  [1-{len(clients)}] Individual client")
        print("  [A] All detected clients")
        print("  [0] Cancel")

        choice = input("\nYour choice: ").strip().upper()

        selected_clients = []
        if choice == "A":
            selected_clients = [c for c in clients if c.detected]
            if not selected_clients:
                print("❌ No clients detected to configure.")
                return {}
        elif choice == "0":
            print("Setup cancelled.")
            return {}
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(clients):
                    selected_clients = [clients[idx]]
                else:
                    print("❌ Invalid choice.")
                    return {}
            except ValueError:
                print("❌ Invalid choice.")
                return {}

        if not selected_clients:
            print("❌ No clients selected.")
            return {}

        # Get vault path
        print("\n📁 Vault Configuration")
        default_vault = self.vault_path or str(
            Path.home() / "Documents/memograph-vault"
        )
        vault_input = input(f"Vault path (default: {default_vault}): ").strip()
        vault_path = Path(vault_input if vault_input else default_vault)

        # Create vault if it doesn't exist
        if not vault_path.exists():
            create = input("\nVault doesn't exist. Create it? (Y/n): ").strip().lower()
            if create != "n":
                vault_path.mkdir(parents=True, exist_ok=True)
                print(f"✓ Created vault at {vault_path}")

        # Get LLM provider
        print("\n🤖 LLM Provider Configuration")
        print("  [1] Ollama (Free, local)")
        print("  [2] Claude (Requires API key)")
        print("  [3] OpenAI (Requires API key)")

        provider_choice = input("\nYour choice (default: 1): ").strip() or "1"

        provider_map = {"1": "ollama", "2": "claude", "3": "openai"}
        provider = provider_map.get(provider_choice, "ollama")

        # Get model
        model = None
        if provider == "ollama":
            print("\n📦 Ollama Model")
            print("  [1] llama3.1:latest (Recommended)")
            print("  [2] mistral:latest")
            print("  [3] llama2:latest")
            print("  [4] Custom model")

            model_choice = input("\nYour choice (default: 1): ").strip() or "1"

            model_map = {
                "1": "llama3.1:latest",
                "2": "mistral:latest",
                "3": "llama2:latest",
            }

            if model_choice == "4":
                model = input("Enter model name: ").strip()
            else:
                model = model_map.get(model_choice, "llama3.1:latest")

        # Build configuration
        config = {
            "vault_path": str(vault_path),
            "provider": provider,
            "model": model,
            "clients": selected_clients,
        }

        # Configure each client
        print("\n⚙️  Configuring clients...")
        success_count = 0

        for client in selected_clients:
            try:
                self._configure_client(client, config)
                print(f"  ✓ {client.name} configured")
                success_count += 1
            except Exception as e:
                print(f"  ✗ {client.name} failed: {e}")

        # Summary
        print("\n" + "=" * 50)
        print("✅ Setup Complete!")
        print(f"\nConfigured {success_count}/{len(selected_clients)} client(s)")

        if success_count > 0:
            print("\n📋 Next Steps:")
            print("  1. Restart your MCP client(s)")
            print("  2. Test with: 'Search my MemoGraph vault'")
            print("  3. Run: memograph verify-mcp (to verify setup)")

        return config

    def _configure_client(self, client: MCPClient, config: dict[str, Any]) -> None:
        """Configure a specific MCP client."""
        vault_path = config["vault_path"]
        provider = config["provider"]
        model = config.get("model")

        # Prepare configuration based on client type
        if "Cursor" in client.name:
            # Cursor uses the same ``mcpServers`` shape as Claude Desktop
            # but its config lives at a different path. Merge so we
            # don't blow away other servers the user has wired up.
            cursor_config: dict[str, Any] = {
                "mcpServers": {
                    "memograph": {
                        "command": "python",
                        "args": ["-m", "memograph.mcp.run_server"],
                        "env": {
                            "MEMOGRAPH_VAULT": vault_path,
                            "MEMOGRAPH_PROVIDER": provider,
                        },
                    }
                }
            }
            if model:
                cursor_config["mcpServers"]["memograph"]["env"]["MEMOGRAPH_MODEL"] = (
                    model
                )
            self._write_config(client.config_path, cursor_config, merge=True)
            return

        if "Claude Desktop" in client.name:
            mcp_config: dict[str, Any] = {
                "mcpServers": {
                    "memograph": {
                        "command": "python",
                        "args": ["-m", "memograph.mcp.run_server"],
                        "env": {
                            "MEMOGRAPH_VAULT": vault_path,
                            "MEMOGRAPH_PROVIDER": provider,
                        },
                    }
                }
            }

            if model:
                mcp_config["mcpServers"]["memograph"]["env"]["MEMOGRAPH_MODEL"] = model

            self._write_config(client.config_path, mcp_config, merge=True)

        elif "Cline" in client.name:
            # Cline uses similar format but different structure
            cline_config: dict[str, Any] = {
                "mcp": {
                    "servers": {
                        "memograph": {
                            "command": "python",
                            "args": ["-m", "memograph.mcp.run_server"],
                            "env": {
                                "MEMOGRAPH_VAULT": vault_path,
                                "MEMOGRAPH_PROVIDER": provider,
                            },
                        }
                    }
                }
            }

            if model:
                cline_config["mcp"]["servers"]["memograph"]["env"][
                    "MEMOGRAPH_MODEL"
                ] = model

            self._write_config(client.config_path, cline_config, merge=False)

        elif "VS Code" in client.name:
            # VS Code settings.json integration
            vscode_setting: dict[str, Any] = {
                "cline.mcpServers": {
                    "memograph": {
                        "command": "python",
                        "args": ["-m", "memograph.mcp.run_server"],
                        "env": {
                            "MEMOGRAPH_VAULT": vault_path,
                            "MEMOGRAPH_PROVIDER": provider,
                        },
                    }
                }
            }

            if model:
                vscode_setting["cline.mcpServers"]["memograph"]["env"][
                    "MEMOGRAPH_MODEL"
                ] = model

            self._write_config(client.config_path, vscode_setting, merge=True)

    def _write_config(
        self, path: Path, config: dict[str, Any], merge: bool = True
    ) -> None:
        """Write configuration to file."""
        # Create parent directory if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config if merging
        existing = {}
        if merge and path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    existing = json.load(f)
            except (OSError, json.JSONDecodeError):
                pass

        # Merge configurations
        if merge:
            # Deep merge for nested dicts
            self._deep_merge(existing, config)
            final_config = existing
        else:
            final_config = config

        # Write configuration
        with open(path, "w", encoding="utf-8") as f:
            json.dump(final_config, f, indent=2)

    def _deep_merge(self, target: dict, source: dict) -> None:
        """Deep merge source into target dictionary."""
        for key, value in source.items():
            if (
                key in target
                and isinstance(target[key], dict)
                and isinstance(value, dict)
            ):
                self._deep_merge(target[key], value)
            else:
                target[key] = value

    def verify_setup(self) -> dict[str, Any]:
        """Verify MCP setup and return status."""
        results = {
            "python": self._check_python(),
            "memograph": self._check_memograph(),
            "mcp_sdk": self._check_mcp_sdk(),
            "vault": self._check_vault(),
            "clients": self._check_clients(),
            "server": self._check_server(),
        }

        return results

    def _check_python(self) -> tuple[bool, str]:
        """Check if Python is available."""
        try:
            result = subprocess.run(
                [sys.executable, "--version"], capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                version = result.stdout.strip() or result.stderr.strip()
                return True, f"Found at {sys.executable} ({version})"
            return False, "Python not responding"
        except Exception as e:
            return False, str(e)

    def _check_memograph(self) -> tuple[bool, str]:
        """Check if memograph is installed."""
        try:
            import memograph

            version = getattr(memograph, "__version__", "unknown")
            return True, f"Installed (v{version})"
        except ImportError:
            return False, "Not installed - run: pip install -e ."

    def _check_mcp_sdk(self) -> tuple[bool, str]:
        """Check if MCP SDK is installed."""
        try:
            import mcp

            version = getattr(mcp, "__version__", "unknown")
            return True, f"Installed (v{version})"
        except ImportError:
            return False, "Not installed - run: pip install mcp"

    def _check_vault(self) -> tuple[bool, str]:
        """Check if vault exists."""
        if not self.vault_path:
            return False, "No vault path configured"

        vault = Path(self.vault_path)
        if vault.exists():
            return True, f"Found at {vault}"
        return False, f"Not found at {vault}"

    def _check_clients(self) -> list[tuple[str, bool, str]]:
        """Check configured MCP clients."""
        results = []
        clients = self.detect_clients()

        for client in clients:
            if client.config_path.exists():
                try:
                    with open(client.config_path) as f:
                        config = json.load(f)

                    # Check if memograph is configured
                    configured = False
                    if "Claude" in client.name:
                        configured = "memograph" in config.get("mcpServers", {})
                    elif "Cline" in client.name:
                        configured = "memograph" in config.get("mcp", {}).get(
                            "servers", {}
                        )
                    elif "VS Code" in client.name:
                        configured = "memograph" in config.get("cline.mcpServers", {})

                    status = "Configured" if configured else "Not configured"
                    results.append((client.name, configured, status))
                except Exception as e:
                    results.append((client.name, False, f"Error: {e}"))
            else:
                results.append((client.name, False, "Config file not found"))

        return results

    def _check_server(self) -> tuple[bool, str]:
        """Check if MCP server can start."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "memograph.mcp.run_server", "--help"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return True, "Server module OK"
            return False, f"Server error: {result.stderr}"
        except Exception as e:
            return False, str(e)

    def print_verification_results(self, results: dict[str, Any]) -> None:
        """Print formatted verification results."""
        print("\n=== MemoGraph MCP Verification ===")
        print("=" * 50)

        # Python
        success, msg = results["python"]
        icon = "[OK]" if success else "[FAIL]"
        print(f"{icon} Python: {msg}")

        # MemoGraph
        success, msg = results["memograph"]
        icon = "[OK]" if success else "[FAIL]"
        print(f"{icon} MemoGraph: {msg}")

        # MCP SDK
        success, msg = results["mcp_sdk"]
        icon = "[OK]" if success else "[FAIL]"
        print(f"{icon} MCP SDK: {msg}")

        # Vault
        success, msg = results["vault"]
        icon = "[OK]" if success else "[FAIL]"
        print(f"{icon} Vault: {msg}")

        # Server
        success, msg = results["server"]
        icon = "[OK]" if success else "[FAIL]"
        print(f"{icon} Server: {msg}")

        # Clients
        print("\n=== MCP Clients ===")
        clients_results = results["clients"]
        if clients_results:
            for name, configured, status in clients_results:
                icon = "[OK]" if configured else "[--]"
                print(f"  {icon} {name}: {status}")
        else:
            print("  No clients detected")

        # Overall status
        print("\n" + "=" * 50)
        all_critical_ok = (
            results["python"][0]
            and results["memograph"][0]
            and results["mcp_sdk"][0]
            and results["server"][0]
        )

        if all_critical_ok:
            print("[SUCCESS] MCP setup is functional!")
            if not any(c[1] for c in clients_results):
                print("\n[WARNING] No clients configured yet.")
                print("          Run: memograph setup-mcp")
        else:
            print("[ERROR] MCP setup has issues. Please fix the errors above.")
