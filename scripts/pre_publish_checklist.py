#!/usr/bin/env python3
"""Pre-publish checklist for MemoGraph marketplace release."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


def check_mark(passed: bool) -> str:
    """Return checkmark or X based on pass/fail."""
    return f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"


def print_section(title: str) -> None:
    """Print a section header."""
    print(f"\n{BLUE}{'=' * 60}{RESET}")
    print(f"{BLUE}{title}{RESET}")
    print(f"{BLUE}{'=' * 60}{RESET}\n")


def check_version_consistency() -> bool:
    """Check if versions are consistent across files."""
    print_section("📦 Version Consistency Check")

    versions = {}
    files_to_check = {
        "pyproject.toml": r'version = "([^"]+)"',
        "smithery.json": r'"version": "([^"]+)"',
    }

    for file_path, pattern in files_to_check.items():
        try:
            with open(file_path, "r") as f:
                content = f.read()
                match = re.search(pattern, content)
                if match:
                    versions[file_path] = match.group(1)
                    print(f"{check_mark(True)} {file_path}: {versions[file_path]}")
                else:
                    print(f"{check_mark(False)} {file_path}: Version not found")
                    return False
        except FileNotFoundError:
            print(f"{check_mark(False)} {file_path}: File not found")
            return False

    # Check if all versions match
    version_values = list(versions.values())
    if len(set(version_values)) == 1:
        print(f"\n{GREEN}✓ All versions are consistent: {version_values[0]}{RESET}")
        return True
    else:
        print(f"\n{RED}✗ Version mismatch detected!{RESET}")
        print("  Please sync versions across all files.")
        return False


def check_git_status() -> bool:
    """Check if git working directory is clean."""
    print_section("🔍 Git Status Check")

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        )

        if result.stdout.strip():
            print(f"{check_mark(False)} Working directory has uncommitted changes:")
            print(result.stdout)
            print(f"\n{YELLOW}Commit or stash changes before publishing.{RESET}")
            return False
        else:
            print(f"{check_mark(True)} Working directory is clean")
            return True
    except subprocess.CalledProcessError as e:
        print(f"{check_mark(False)} Error checking git status: {e}")
        return False


def check_tests() -> bool:
    """Check if tests pass."""
    print_section("🧪 Test Suite Check")

    print("Running pytest...")
    try:
        result = subprocess.run(
            ["pytest", "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode == 0:
            print(f"{check_mark(True)} All tests passed")
            # Show summary
            for line in result.stdout.split("\n"):
                if "passed" in line.lower() or "failed" in line.lower():
                    print(f"  {line}")
            return True
        else:
            print(f"{check_mark(False)} Some tests failed")
            print("\nFailed test output:")
            print(result.stdout[-1000:])  # Last 1000 chars
            return False
    except FileNotFoundError:
        print(f"{check_mark(False)} pytest not found. Install with: pip install pytest")
        return False
    except subprocess.TimeoutExpired:
        print(f"{check_mark(False)} Tests timed out after 5 minutes")
        return False
    except Exception as e:
        print(f"{check_mark(False)} Error running tests: {e}")
        return False


def check_pypi_credentials() -> bool:
    """Check if PyPI credentials are configured."""
    print_section("🔑 PyPI Credentials Check")

    pypirc_path = Path.home() / ".pypirc"
    has_pypirc = pypirc_path.exists()
    has_env = "TWINE_USERNAME" in os.environ and "TWINE_PASSWORD" in os.environ

    if has_pypirc:
        print(f"{check_mark(True)} Found ~/.pypirc configuration")
        return True
    elif has_env:
        print(
            f"{check_mark(True)} Found TWINE_USERNAME and TWINE_PASSWORD environment variables"
        )
        return True
    else:
        print(f"{check_mark(False)} No PyPI credentials found")
        print(f"\n{YELLOW}Configure credentials before publishing:{RESET}")
        print("  1. Create ~/.pypirc with your PyPI token")
        print("  2. Or set TWINE_USERNAME and TWINE_PASSWORD env vars")
        print("\nSee MARKETPLACE_PUBLISHING_GUIDE.md for details.")
        return False


def check_smithery_json() -> bool:
    """Validate smithery.json configuration."""
    print_section("📝 Smithery Config Check")

    try:
        with open("smithery.json", "r") as f:
            config = json.load(f)

        required_fields = ["name", "version", "description", "author", "tools"]
        missing = [f for f in required_fields if f not in config]

        if missing:
            print(f"{check_mark(False)} Missing required fields: {', '.join(missing)}")
            return False

        print(f"{check_mark(True)} All required fields present")
        print(f"  Name: {config['name']}")
        print(f"  Version: {config['version']}")
        print(f"  Tools: {len(config['tools'])} tools configured")
        return True

    except FileNotFoundError:
        print(f"{check_mark(False)} smithery.json not found")
        return False
    except json.JSONDecodeError as e:
        print(f"{check_mark(False)} Invalid JSON in smithery.json: {e}")
        return False


def check_mcp_server() -> bool:
    """Check if MCP server can start."""
    print_section("🔌 MCP Server Check")

    print("Testing if MCP server can start...")
    try:
        result = subprocess.run(
            ["python", "-m", "memograph.mcp.run_server", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            print(f"{check_mark(True)} MCP server module loads successfully")
            return True
        else:
            print(f"{check_mark(False)} MCP server failed to start")
            print(result.stderr)
            return False
    except subprocess.TimeoutExpired:
        print(f"{check_mark(False)} MCP server startup timed out")
        return False
    except Exception as e:
        print(f"{check_mark(False)} Error testing MCP server: {e}")
        return False


def check_build_tools() -> bool:
    """Check if build tools are installed."""
    print_section("🛠️  Build Tools Check")

    tools = ["build", "twine"]
    all_present = True

    for tool in tools:
        try:
            if tool == "build":
                result = subprocess.run(
                    ["python", "-m", "build", "--help"], capture_output=True, timeout=5
                )
            else:
                result = subprocess.run(
                    [tool, "--version"], capture_output=True, timeout=5
                )

            if result.returncode == 0:
                print(f"{check_mark(True)} {tool} is installed")
            else:
                print(f"{check_mark(False)} {tool} is not working properly")
                all_present = False
        except FileNotFoundError:
            print(f"{check_mark(False)} {tool} not found")
            all_present = False

    if not all_present:
        print(f"\n{YELLOW}Install missing tools with: pip install build twine{RESET}")

    return all_present


def main():
    """Run all pre-publishing checks."""
    print(f"\n{BLUE}{'=' * 60}{RESET}")
    print(f"{BLUE}🚀 MemoGraph Pre-Publish Checklist{RESET}")
    print(f"{BLUE}{'=' * 60}{RESET}")

    checks = [
        ("Version Consistency", check_version_consistency),
        ("Git Status", check_git_status),
        ("Build Tools", check_build_tools),
        ("Smithery Config", check_smithery_json),
        ("MCP Server", check_mcp_server),
        ("PyPI Credentials", check_pypi_credentials),
        ("Test Suite", check_tests),
    ]

    results = {}
    for name, check_func in checks:
        try:
            results[name] = check_func()
        except Exception as e:
            print(f"\n{RED}Error during {name}: {e}{RESET}")
            results[name] = False

    # Print summary
    print_section("📊 Summary")

    passed = sum(results.values())
    total = len(results)

    for name, result in results.items():
        status = f"{GREEN}PASS{RESET}" if result else f"{RED}FAIL{RESET}"
        print(f"{check_mark(result)} {name}: {status}")

    print(f"\n{BLUE}{'=' * 60}{RESET}")
    print(f"Results: {passed}/{total} checks passed")

    if passed == total:
        print(f"\n{GREEN}✅ All checks passed! You're ready to publish.{RESET}")
        print("\nNext step:")
        print("  bash scripts/publish_to_marketplace.sh")
        return 0
    else:
        print(
            f"\n{RED}❌ {total - passed} check(s) failed. Please fix issues before publishing.{RESET}"
        )
        print("\nSee MARKETPLACE_PUBLISHING_GUIDE.md for help.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
