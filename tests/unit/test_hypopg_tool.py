"""Tool visibility is explicitly gated by operator configuration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import CallToolRequestParams

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


@pytest.mark.asyncio
async def test_hypopg_tool_dispatch_validates_opt_in_and_returns_structured_result():
    pg = DatabaseMCPServer(
        DatabaseConfig(url="postgresql+asyncpg://u:p@localhost/db", hypopg_enabled=True)
    )
    arguments = {
        "query": "SELECT * FROM users",
        "schema": "public",
        "table": "users",
        "columns": ["id"],
    }
    with patch("db_connect_mcp.server.HypoPGComparison") as comparison:
        invalid = await pg._call_tool(
            None,
            CallToolRequestParams(
                name="compare_hypothetical_index", arguments=arguments
            ),
        )
        assert invalid.is_error
        assert invalid.structured_content["error"]["code"] == "invalid_arguments"
        comparison.assert_not_called()

        comparison.return_value.compare = AsyncMock(
            side_effect=ValueError("HypoPG is not installed")
        )
        failure = await pg._call_tool(
            None,
            CallToolRequestParams(
                name="compare_hypothetical_index",
                arguments={**arguments, "opt_in": True},
            ),
        )
        assert failure.is_error
        assert failure.structured_content["error"]["code"] == "tool_execution_error"
        comparison.return_value.compare.assert_awaited_once_with(
            "SELECT * FROM users", "public", "users", ["id"], opt_in=True
        )

        comparison.return_value.compare = AsyncMock(
            return_value=MagicMock(
                model_dump_json=MagicMock(
                    return_value='{"baseline_estimated_cost": 15, "hypothetical_estimated_cost": 5}'
                )
            )
        )
        success = await pg._call_tool(
            None,
            CallToolRequestParams(
                name="compare_hypothetical_index",
                arguments={**arguments, "opt_in": True},
            ),
        )
        assert not success.is_error
        assert success.structured_content["baseline_estimated_cost"] == 15
