"""Live query result caps, including caller-authored SQL LIMIT."""

import pytest

from db_connect_mcp.adapters import create_adapter
from db_connect_mcp.core.connection import DatabaseConnection
from db_connect_mcp.core.executor import QueryExecutor
from db_connect_mcp.models.config import DatabaseConfig


@pytest.mark.asyncio
async def test_existing_sql_limit_cannot_expand_result(pg_database_url: str) -> None:
    config = DatabaseConfig(url=pg_database_url)
    connection = DatabaseConnection(config)
    await connection.initialize()
    try:
        result = await QueryExecutor(connection, create_adapter(config)).execute_query(
            "SELECT n FROM generate_series(1, 500) AS n LIMIT 500", limit=5
        )
        assert result.row_count == 5
        assert result.truncated is True
        assert [row["n"] for row in result.rows] == [1, 2, 3, 4, 5]
    finally:
        await connection.dispose()


@pytest.mark.asyncio
async def test_one_large_value_cannot_exhaust_response(pg_database_url: str) -> None:
    config = DatabaseConfig(url=pg_database_url)
    connection = DatabaseConnection(config)
    await connection.initialize()
    try:
        with pytest.raises(ValueError, match="100000 bytes"):
            await QueryExecutor(connection, create_adapter(config)).execute_query(
                "SELECT repeat('x', 200000) AS oversized", limit=1
            )
    finally:
        await connection.dispose()
