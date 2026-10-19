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
@pytest.mark.parametrize(
    "query",
    [
        "-- heading\nSELECT n FROM generate_series(1, 500) AS n LIMIT 500",
        "SELECT\nn FROM generate_series(1, 500) AS n LIMIT 500",
        "/* heading */ SELECT n FROM generate_series(1, 500) AS n LIMIT 500",
        "SELECT n FROM generate_series(1, 500) AS n -- trailing comment",
    ],
)
async def test_commented_or_multiline_query_stays_bounded(
    pg_database_url: str, query: str
) -> None:
    config = DatabaseConfig(url=pg_database_url)
    connection = DatabaseConnection(config)
    await connection.initialize()
    try:
        result = await QueryExecutor(connection, create_adapter(config)).execute_query(
            query, limit=5
        )
        assert result.row_count == 5
        assert result.truncated
        assert result.query.startswith("SELECT * FROM (")
        assert result.query.endswith("LIMIT 6")
    finally:
        await connection.dispose()


@pytest.mark.asyncio
async def test_query_metadata_counts_toward_response_budget(
    pg_database_url: str,
) -> None:
    config = DatabaseConfig(url=pg_database_url)
    connection = DatabaseConnection(config)
    await connection.initialize()
    try:
        with pytest.raises(ValueError, match="bytes"):
            await QueryExecutor(connection, create_adapter(config)).execute_query(
                "SELECT 1 AS " + "x" * 180, limit=1, max_result_bytes=100
            )
    finally:
        await connection.dispose()


@pytest.mark.asyncio
async def test_mysql_existing_limit_is_bounded(mysql_database_url: str) -> None:
    config = DatabaseConfig(url=mysql_database_url)
    connection = DatabaseConnection(config)
    await connection.initialize()
    try:
        result = await QueryExecutor(connection, create_adapter(config)).execute_query(
            "SELECT 1 AS n UNION ALL SELECT 2 AS n LIMIT 2", limit=1
        )
        assert result.row_count == 1
        assert result.truncated
        assert result.rows[0]["n"] == 1
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
