"""
Interactive setup wizard for db-connect-mcp.

This module provides a user-friendly wizard that:
1. Prompts user for database connection string
2. Validates the connection by attempting to connect
3. Generates MCP config files for Claude Code and ChatGPT
4. Saves configs to appropriate platform-specific locations
"""

import asyncio
import json
import os
import platform
import sys
from pathlib import Path
from typing import Dict

from db_connect_mcp.adapters import create_adapter
from db_connect_mcp.core.connection import DatabaseConnection


class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_header(text: str):
    """Print formatted header."""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{text}{Colors.ENDC}")


def print_success(text: str):
    """Print success message."""
    print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")


def print_error(text: str):
    """Print error message."""
    print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")


def print_info(text: str):
    """Print info message."""
    print(f"{Colors.OKCYAN}ℹ {text}{Colors.ENDC}")


def print_warning(text: str):
    """Print warning message."""
    print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")


def get_config_paths() -> Dict[str, Path]:
    """Get platform-specific config file paths for Claude Code and ChatGPT."""
    system = platform.system()

    if system == "Windows":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        claude_config = appdata / "Claude" / "claude_desktop_config.json"
        # ChatGPT Desktop is not yet available on Windows, use user dir
        chatgpt_config = Path.home() / ".chatgpt" / "mcp_config.json"
    elif system == "Darwin":  # macOS
        claude_config = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        chatgpt_config = Path.home() / "Library" / "Application Support" / "ChatGPT" / "mcp_config.json"
    else:  # Linux and others
        claude_config = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
        chatgpt_config = Path.home() / ".config" / "chatgpt" / "mcp_config.json"

    return {
        "claude": claude_config,
        "chatgpt": chatgpt_config
    }


def get_database_url() -> str:
    """Prompt user for database connection string."""
    print_header("Database Connection Setup")
    print_info("Enter your database connection string.")
    print_info("Supported formats:")
    print("  • PostgreSQL: postgresql+asyncpg://user:pass@host:port/dbname")
    print("  • MySQL:      mysql+aiomysql://user:pass@host:port/dbname")
    print("  • ClickHouse: clickhouse+asynch://user:pass@host:port/dbname")
    print()

    while True:
        database_url = input(f"{Colors.BOLD}Database URL: {Colors.ENDC}").strip()

        if not database_url:
            print_error("Database URL cannot be empty.")
            continue

        # Basic validation
        valid_prefixes = [
            "postgresql+asyncpg://",
            "mysql+aiomysql://",
            "clickhouse+asynch://",
            # Also accept without explicit driver (will be added by the server)
            "postgresql://",
            "postgres://",
            "mysql://",
            "mariadb://",
            "clickhouse://",
        ]

        if not any(database_url.startswith(prefix) for prefix in valid_prefixes):
            print_error("Invalid database URL format.")
            print_warning("Make sure to use a supported database URL format.")
            continue

        return database_url


async def validate_connection(database_url: str) -> bool:
    """Validate database connection by attempting to connect."""
    print_info("Validating database connection...")

    try:
        # Create adapter
        adapter = create_adapter(database_url)

        # Create connection
        connection = DatabaseConnection(database_url, adapter)
        await connection.connect()

        # Test the connection
        async with connection.get_connection() as conn:
            # Simple query to verify connection works
            result = await conn.execute(adapter.get_database_info_query())
            db_info = result.mappings().first()

            print_success("Connection successful!")
            print_info(f"Connected to: {db_info.get('database_type', 'Unknown')} {db_info.get('version', '')}")

        await connection.disconnect()
        return True

    except Exception as e:
        print_error(f"Connection failed: {str(e)}")
        return False


def create_mcp_config(database_url: str) -> Dict:
    """Create MCP server configuration."""
    # Get the Python executable path (use uv if available, otherwise current python)
    python_path = sys.executable

    config = {
        "mcpServers": {
            "db-connect": {
                "command": str(python_path),
                "args": [
                    "-m",
                    "db_connect_mcp"
                ],
                "env": {
                    "DATABASE_URL": database_url
                }
            }
        }
    }

    return config


def merge_config(existing_config: Dict, new_server_config: Dict) -> Dict:
    """Merge new server config into existing config."""
    if "mcpServers" not in existing_config:
        existing_config["mcpServers"] = {}

    # Add or update the db-connect server
    existing_config["mcpServers"]["db-connect"] = new_server_config["mcpServers"]["db-connect"]

    return existing_config


def save_config(config_path: Path, config: Dict, backup: bool = True):
    """Save config file with optional backup."""
    # Create parent directories if they don't exist
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Backup existing config
    if backup and config_path.exists():
        backup_path = config_path.with_suffix(".json.backup")
        print_info(f"Creating backup: {backup_path}")
        backup_path.write_text(config_path.read_text())

    # Load existing config if present
    if config_path.exists():
        try:
            existing_config = json.loads(config_path.read_text())
            config = merge_config(existing_config, config)
            print_info("Merged with existing configuration")
        except json.JSONDecodeError:
            print_warning("Existing config is invalid, will be replaced")

    # Write config
    config_path.write_text(json.dumps(config, indent=2))
    print_success(f"Config saved to: {config_path}")


def run_setup() -> int:
    """Main setup flow."""
    print_header("🗄️  db-connect-mcp Setup Wizard")
    print()
    print("This wizard will help you configure the MCP server for database exploration.")
    print()

    # Step 1: Get database URL
    database_url = get_database_url()

    # Step 2: Validate connection
    print()
    validation_result = asyncio.run(validate_connection(database_url))

    if not validation_result:
        print()
        retry = input(f"{Colors.BOLD}Would you like to try a different URL? (y/n): {Colors.ENDC}").strip().lower()
        if retry == 'y':
            return run_setup()  # Restart
        else:
            print_error("Setup cancelled.")
            return 1

    # Step 3: Generate config
    print()
    print_header("Generating MCP Configuration")
    mcp_config = create_mcp_config(database_url)

    # Step 4: Get config paths
    config_paths = get_config_paths()

    # Step 5: Ask which clients to configure
    print()
    print_info("Which MCP clients would you like to configure?")
    print("  1. Claude Code (recommended)")
    print("  2. ChatGPT")
    print("  3. Both")
    print()

    while True:
        choice = input(f"{Colors.BOLD}Choose (1/2/3): {Colors.ENDC}").strip()
        if choice in ["1", "2", "3"]:
            break
        print_error("Invalid choice. Please enter 1, 2, or 3.")

    # Step 6: Save configs
    print()
    print_header("Saving Configuration Files")

    if choice in ["1", "3"]:
        save_config(config_paths["claude"], mcp_config)

    if choice in ["2", "3"]:
        save_config(config_paths["chatgpt"], mcp_config)

    # Step 7: Success message
    print()
    print_header("✅ Setup Complete!")
    print()
    print_info("Next steps:")

    if choice in ["1", "3"]:
        print("  1. Restart Claude Code")
        print("  2. The 'db-connect' MCP server should appear in your tools")

    if choice in ["2", "3"]:
        print("  1. Restart ChatGPT Desktop")
        print("  2. The 'db-connect' MCP server should appear in your tools")

    print()
    print_info("To test the connection, try asking:")
    print('  "What databases are available?" or "Show me the schema"')
    print()

    return 0
