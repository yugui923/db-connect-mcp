"""Contract tests for opt-in PostgreSQL statement statistics."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import CallToolRequestParams

from db_connect_mcp.models.config import DatabaseConfig
from db_connect_mcp.models.pg_stat import TopQueriesReport, TopQuery
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
async def test_pg_stat_tool_without_initialized_reporter_returns_error() -> None:
    server = DatabaseMCPServer(
        DatabaseConfig(
            url="postgresql://user@localhost/db", enable_pg_stat_statements=True
        )
    )
    result = await server._call_tool(
        MagicMock(), CallToolRequestParams(name="get_top_queries", arguments={})
    )
    assert result.is_error
    assert result.structured_content["error"]["code"] == "tool_execution_error"
    assert "not initialized" in result.structured_content["error"]["message"]


@pytest.mark.asyncio
async def test_pg_stat_tool_validates_bounds_and_preserves_structured_text() -> None:
    server = DatabaseMCPServer(
        DatabaseConfig(
            url="postgresql://user@localhost/db", enable_pg_stat_statements=True
        )
    )
    server.pg_stat_reporter = MagicMock()
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


@pytest.mark.asyncio
async def test_pg_stat_tool_caps_serialized_output_without_invalid_json() -> None:
    server = DatabaseMCPServer(
        DatabaseConfig(
            url="postgresql://user@localhost/db", enable_pg_stat_statements=True
        )
    )
    server.pg_stat_reporter = MagicMock()
    server.pg_stat_reporter.get_top_queries = AsyncMock(
        return_value=TopQueriesReport(
            status="available",
            queries=[
                TopQuery(
                    query_id=i,
                    calls=1,
                    total_exec_time_ms=1,
                    mean_exec_time_ms=1,
                    rows=1,
                    query='"\\\n😀' * 500,
                )
                for i in range(50)
            ],
        )
    )
    result = await server._call_tool(
        MagicMock(),
        CallToolRequestParams(
            name="get_top_queries", arguments={"include_query_text": True}
        ),
    )
    assert not result.is_error
    assert result.structured_content == json.loads(result.content[0].text)
    assert len(result.content[0].text.encode("utf-8")) <= 50000
    assert result.structured_content["status"] == "available"
    assert result.structured_content["truncated"] is True
    assert 0 < len(result.structured_content["queries"]) <= 50
    assert all(query["query"] is None for query in result.structured_content["queries"])


@pytest.mark.asyncio
async def test_pg_stat_tool_keeps_small_query_text() -> None:
    server = DatabaseMCPServer(
        DatabaseConfig(
            url="postgresql://user@localhost/db", enable_pg_stat_statements=True
        )
    )
    server.pg_stat_reporter = MagicMock()
    server.pg_stat_reporter.get_top_queries = AsyncMock(
        return_value=TopQueriesReport(
            status="available",
            queries=[
                TopQuery(
                    query_id=1,
                    calls=2,
                    total_exec_time_ms=3,
                    mean_exec_time_ms=1.5,
                    rows=1,
                    query="SELECT 1",
                )
            ],
        )
    )
    result = await server._call_tool(
        MagicMock(),
        CallToolRequestParams(
            name="get_top_queries", arguments={"include_query_text": True}
        ),
    )
    assert result.structured_content == json.loads(result.content[0].text)
    assert result.structured_content["truncated"] is False
    assert result.structured_content["queries"][0]["query"] == "SELECT 1"
