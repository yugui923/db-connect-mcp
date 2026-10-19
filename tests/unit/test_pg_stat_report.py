"""Contract tests for opt-in PostgreSQL statement statistics."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import CallToolRequestParams

from db_connect_mcp.models.config import DatabaseConfig
from db_connect_mcp.server import DatabaseMCPServer


@pytest.mark.asyncio
async def test_pg_stat_tool_requires_opt_in_and_postgres() -> None:
    pg = DatabaseMCPServer(DatabaseConfig(url="postgresql://user@localhost/db"))
    mysql = DatabaseMCPServer(
        DatabaseConfig(url="mysql://user@localhost/db", enable_pg_stat_statements=True)
    )
    enabled = DatabaseMCPServer(
        DatabaseConfig(
            url="postgresql://user@localhost/db", enable_pg_stat_statements=True
        )
    )

    assert "get_top_queries" not in {tool.name for tool in pg._available_tools()}
    assert "get_top_queries" not in {tool.name for tool in mysql._available_tools()}
    assert "get_top_queries" in {tool.name for tool in enabled._available_tools()}
    unavailable = await pg._call_tool(
        MagicMock(), CallToolRequestParams(name="get_top_queries", arguments={})
    )
    assert unavailable.structured_content["error"]["code"] == "tool_unavailable"


@pytest.mark.asyncio
async def test_pg_stat_tool_validates_bounds_and_preserves_structured_text() -> None:
    server = DatabaseMCPServer(
        DatabaseConfig(
            url="postgresql://user@localhost/db", enable_pg_stat_statements=True
        )
    )
    server.pg_stat_reporter = MagicMock()
    from db_connect_mcp.models.pg_stat import TopQueriesReport

    server.pg_stat_reporter.get_top_queries = AsyncMock(
        return_value=TopQueriesReport(status="extension_not_installed", queries=[])
    )
    for arguments in (
        {"limit": 51},
        {"query_text_limit": 2001},
        {"include_query_text": 1},
    ):
        invalid = await server._call_tool(
            MagicMock(),
            CallToolRequestParams(name="get_top_queries", arguments=arguments),
        )
        assert invalid.structured_content["error"]["code"] == "invalid_arguments"

    result = await server._call_tool(
        MagicMock(), CallToolRequestParams(name="get_top_queries", arguments={})
    )
    assert not result.is_error
    assert result.structured_content == json.loads(result.content[0].text)
    assert result.structured_content["status"] == "extension_not_installed"
