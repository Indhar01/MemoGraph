"""Authentication helpers for Notion integration."""

import os
from typing import Optional, Dict, Any
from pathlib import Path
import json


class NotionAuth:
    """Handle Notion authentication and token management.

    Supports both internal integrations (simple token) and OAuth flow
    for public integrations.

    Example:
        ```python
        # For internal integration (development)
        token = NotionAuth.load_token()

        # For OAuth (public integration)
        auth_url = NotionAuth.get_auth_url(client_id, redirect_uri)
        # User authorizes...
        token_data = NotionAuth.exchange_code(code, client_id, client_secret, redirect_uri)
        NotionAuth.save_token(token_data['access_token'])
        ```
    """

    DEFAULT_TOKEN_FILE = ".notion_token"
    DEFAULT_CONFIG_FILE = ".notion_config.json"

    @staticmethod
    def get_auth_url(
        client_id: str, redirect_uri: str, state: Optional[str] = None
    ) -> str:
        """Generate OAuth authorization URL for public integrations.

        Args:
            client_id: OAuth client ID from Notion integration settings
            redirect_uri: URL to redirect to after authorization
            state: Optional state parameter for security

        Returns:
            Full authorization URL to redirect user to.

        Example:
            ```python
            url = NotionAuth.get_auth_url(
                client_id="your_client_id",
                redirect_uri="https://yourapp.com/callback"
            )
            print(f"Visit: {url}")
            ```
        """
        base_url = "https://api.notion.com/v1/oauth/authorize"
        params = f"client_id={client_id}&redirect_uri={redirect_uri}&response_type=code"

        if state:
            params += f"&state={state}"

        return f"{base_url}?{params}"

    @staticmethod
    def exchange_code(
        code: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> Dict[str, Any]:
        """Exchange authorization code for access token.

        This is step 2 of the OAuth flow, called after user authorizes.

        Args:
            code: Authorization code from OAuth callback
            client_id: OAuth client ID
            client_secret: OAuth client secret
            redirect_uri: Same redirect URI used in authorization

        Returns:
            Dictionary containing:
            {
                "access_token": str,
                "bot_id": str,
                "workspace_id": str,
                "workspace_name": str,
                "workspace_icon": str,
                "owner": Dict[str, Any]
            }

        Raises:
            requests.exceptions.RequestException: If API request fails
            ValueError: If response is invalid
        """
        try:
            import requests
        except ImportError:
            raise ImportError(
                "requests package required for OAuth. "
                "Install with: pip install requests"
            )

        response = requests.post(
            "https://api.notion.com/v1/oauth/token",
            auth=(client_id, client_secret),
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        if response.status_code != 200:
            raise ValueError(
                f"OAuth token exchange failed: {response.status_code} - {response.text}"
            )

        return response.json()

    @staticmethod
    def save_token(token: str, config_file: Optional[str] = None) -> None:
        """Save access token to file.

        Saves token to a local file for persistence. The file should be
        added to .gitignore to prevent committing secrets.

        Args:
            token: Notion API access token
            config_file: Path to save token (default: .notion_token)
        """
        file_path = config_file or NotionAuth.DEFAULT_TOKEN_FILE
        path = Path(file_path)

        # Create parent directory if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        # Save token
        with open(path, "w") as f:
            f.write(token)

        # Set restrictive permissions (Unix-like systems)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass  # Windows doesn't support chmod

    @staticmethod
    def load_token(config_file: Optional[str] = None) -> Optional[str]:
        """Load access token from file.

        Args:
            config_file: Path to token file (default: .notion_token)

        Returns:
            Access token if file exists, None otherwise.
        """
        file_path = config_file or NotionAuth.DEFAULT_TOKEN_FILE
        path = Path(file_path)

        if path.exists():
            with open(path, "r") as f:
                return f.read().strip()

        return None

    @staticmethod
    def save_config(config: Dict[str, Any], config_file: Optional[str] = None) -> None:
        """Save full integration configuration to JSON file.

        Args:
            config: Configuration dictionary (may include workspace_id, etc.)
            config_file: Path to config file (default: .notion_config.json)
        """
        file_path = config_file or NotionAuth.DEFAULT_CONFIG_FILE
        path = Path(file_path)

        # Create parent directory if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        # Save config as JSON
        with open(path, "w") as f:
            json.dump(config, f, indent=2)

        # Set restrictive permissions
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass

    @staticmethod
    def load_config(config_file: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Load integration configuration from JSON file.

        Args:
            config_file: Path to config file (default: .notion_config.json)

        Returns:
            Configuration dictionary if file exists, None otherwise.
        """
        file_path = config_file or NotionAuth.DEFAULT_CONFIG_FILE
        path = Path(file_path)

        if path.exists():
            with open(path, "r") as f:
                return json.load(f)

        return None

    @staticmethod
    def get_token_from_env() -> Optional[str]:
        """Get token from environment variable.

        Checks NOTION_API_TOKEN and NOTION_TOKEN environment variables.

        Returns:
            Token if found in environment, None otherwise.
        """
        return os.getenv("NOTION_API_TOKEN") or os.getenv("NOTION_TOKEN")

    @staticmethod
    def get_token(
        token: Optional[str] = None, config_file: Optional[str] = None
    ) -> Optional[str]:
        """Get token from multiple sources in priority order.

        Priority:
        1. Explicitly provided token parameter
        2. Environment variable (NOTION_API_TOKEN or NOTION_TOKEN)
        3. Token file (.notion_token)
        4. Config file (.notion_config.json)

        Args:
            token: Explicit token (highest priority)
            config_file: Path to config/token file

        Returns:
            Token if found, None otherwise.
        """
        # 1. Explicit token
        if token:
            return token

        # 2. Environment variable
        env_token = NotionAuth.get_token_from_env()
        if env_token:
            return env_token

        # 3. Token file
        file_token = NotionAuth.load_token(config_file)
        if file_token:
            return file_token

        # 4. Config file
        config = NotionAuth.load_config(config_file)
        if config and "access_token" in config:
            return config["access_token"]

        return None

    @staticmethod
    def validate_token_format(token: str) -> bool:
        """Validate that token has the expected format.

        Notion tokens typically start with "secret_" for internal integrations
        or "ntn_" for OAuth tokens.

        Args:
            token: Token to validate

        Returns:
            True if token format looks valid, False otherwise.
        """
        if not token:
            return False

        # Check for common Notion token prefixes
        valid_prefixes = ("secret_", "ntn_")
        return token.startswith(valid_prefixes)

    @staticmethod
    def setup_integration_interactive() -> str:
        """Interactive setup for Notion integration (CLI helper).

        Prompts user for token and saves it securely.

        Returns:
            The configured token.

        Raises:
            KeyboardInterrupt: If user cancels
        """
        print("=" * 60)
        print("Notion Integration Setup")
        print("=" * 60)
        print()
        print("To get your Notion API token:")
        print("1. Go to https://www.notion.so/my-integrations")
        print("2. Create a new integration (or use existing)")
        print("3. Copy the 'Internal Integration Token'")
        print()

        token = input("Paste your Notion API token: ").strip()

        if not token:
            raise ValueError("No token provided")

        if not NotionAuth.validate_token_format(token):
            print(
                "Warning: Token format doesn't look standard (should start with 'secret_')"
            )
            confirm = input("Continue anyway? (y/n): ").strip().lower()
            if confirm != "y":
                raise ValueError("Setup cancelled")

        # Save token
        NotionAuth.save_token(token)
        print()
        print(f"✓ Token saved to {NotionAuth.DEFAULT_TOKEN_FILE}")
        print("✓ Setup complete!")
        print()
        print("Note: Add .notion_token to your .gitignore to keep it secret")

        return token
