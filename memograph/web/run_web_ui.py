#!/usr/bin/env python3
"""
Simple script to run the MemoGraph web UI.

Usage:
    python memograph/web/run_web_ui.py [vault_path]

Example:
    python memograph/web/run_web_ui.py C:\\Users\\INDIRAKUMARS\\Documents\\my-vault
"""

import sys
from pathlib import Path


def main():
    # Get vault path from argument or use default
    if len(sys.argv) > 1:
        vault_path = sys.argv[1]
    else:
        vault_path = input(
            "Enter vault path (or press Enter for default './vault'): "
        ).strip()
        if not vault_path:
            vault_path = "./vault"

    # Validate path
    vault_path_obj = Path(vault_path).expanduser()
    if not vault_path_obj.exists():
        print(f"⚠️  Vault path does not exist: {vault_path_obj}")
        create = input("Would you like to create it? (y/n): ").strip().lower()
        if create == "y":
            vault_path_obj.mkdir(parents=True, exist_ok=True)
            print(f"✅ Created vault directory: {vault_path_obj}")
        else:
            print("❌ Exiting...")
            sys.exit(1)

    print("\n" + "=" * 60)
    print("🧠 MemoGraph Web UI Server")
    print("=" * 60)
    print(f"📁 Vault Path: {vault_path_obj.absolute()}")
    print("🌐 API URL: http://localhost:8000")
    print("📚 API Docs: http://localhost:8000/api/docs")
    print("💚 Health Check: http://localhost:8000/api/health")
    print("=" * 60)
    print("\n⏳ Starting server...\n")

    # Import and run server
    try:
        from memograph.web.backend.server import run_dev_server

        run_dev_server(
            str(vault_path_obj),
            # Documented dev-server entry point.
            host="0.0.0.0",  # nosec B104
            port=8000,
            use_gam=True,
        )
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped by user")
    except Exception as e:
        print(f"\n❌ Error starting server: {e}")
        print("\nMake sure you have installed all dependencies:")
        print("  pip install fastapi uvicorn")
        sys.exit(1)


if __name__ == "__main__":
    main()
