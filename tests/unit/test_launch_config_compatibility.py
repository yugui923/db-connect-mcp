"""Protect existing user launch configurations and CLI defaults."""

import json
from pathlib import Path

from db_connect_mcp.models.config import DatabaseConfig

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_stdio_launch_configs_preserve_entry_points() -> None:
    desktop = json.loads((ROOT / "claude_desktop_config.example.json").read_text())
    local = json.loads((ROOT / ".mcp.json").read_text())
    manifest = json.loads((ROOT / "manifest.json").read_text())
    registry = json.loads((ROOT / "server.json").read_text())

    for config in desktop["mcpServers"].values():
        assert config["args"] == ["-m", "db_connect_mcp"]
        assert "DATABASE_URL" in config["env"]
    assert local["mcpServers"]["db-connect-mcp"]["args"] == [
        "run",
        "python",
        "-m",
        "db_connect_mcp",
    ]
    assert manifest["server"]["mcp_config"]["args"] == ["-m", "db_connect_mcp"]
    assert registry["packages"][0]["transport"]["type"] == "stdio"


def test_legacy_database_urls_keep_normalized_drivers() -> None:
    desktop = json.loads((ROOT / "claude_desktop_config.example.json").read_text())
    expected = {"postgresql": "asyncpg", "mysql": "aiomysql", "clickhouse": "connect"}
    for config in desktop["mcpServers"].values():
        database = DatabaseConfig(url=config["env"]["DATABASE_URL"])
        assert database.driver == expected[database.dialect]
