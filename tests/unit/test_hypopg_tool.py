"""Tool visibility is explicitly gated by operator configuration."""

from db_connect_mcp.models.config import DatabaseConfig
from db_connect_mcp.server import DatabaseMCPServer


def test_hypopg_tool_hidden_by_default_and_on_other_dialects():
    pg = DatabaseMCPServer(DatabaseConfig(url="postgresql+asyncpg://u:p@localhost/db"))
    assert "compare_hypothetical_index" not in {
        tool.name for tool in pg._available_tools()
    }
    mysql = DatabaseMCPServer(
        DatabaseConfig(url="mysql+aiomysql://u:p@localhost/db", hypopg_enabled=True)
    )
    assert "compare_hypothetical_index" not in {
        tool.name for tool in mysql._available_tools()
    }


def test_hypopg_tool_requires_explicit_call_opt_in():
    pg = DatabaseMCPServer(
        DatabaseConfig(url="postgresql+asyncpg://u:p@localhost/db", hypopg_enabled=True)
    )
    tool = next(
        tool
        for tool in pg._available_tools()
        if tool.name == "compare_hypothetical_index"
    )
    assert tool.input_schema["properties"]["opt_in"]["const"] is True
    assert "opt_in" in tool.input_schema["required"]
