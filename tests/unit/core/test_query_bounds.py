"""Query result upper-bound regressions."""

from unittest.mock import AsyncMock, MagicMock
from contextlib import asynccontextmanager

import orjson

import pytest

from db_connect_mcp.core.executor import QueryExecutor


@pytest.mark.parametrize("limit", [None, 0, -1, 10001])
def test_query_rejects_unbounded_or_invalid_limit(limit: int | None) -> None:
    executor = QueryExecutor(MagicMock(), MagicMock())
    with pytest.raises(ValueError, match="limit"):
        executor._validate_limit(limit)


@pytest.mark.parametrize("query", ["SHOW TABLES", "DESCRIBE users", "EXPLAIN SELECT 1"])
def test_query_rejects_unbounded_statement_types(query: str) -> None:
    executor = QueryExecutor(MagicMock(), MagicMock())
    with pytest.raises(ValueError, match="SELECT or WITH"):
        executor._validate_query(query)


def test_query_accepts_semicolon_inside_string() -> None:
    executor = QueryExecutor(MagicMock(), MagicMock())
    executor._validate_query("SELECT ';' AS separator")


def test_query_rejects_multiple_sql_statements() -> None:
    executor = QueryExecutor(MagicMock(), MagicMock())
    with pytest.raises(ValueError, match="statement"):
        executor._validate_query("SELECT 1; SELECT 2")


@pytest.mark.asyncio
async def test_stream_stops_before_fetching_remaining_rows_and_closes() -> None:
    result = MagicMock()
    result.keys.return_value = ["value"]
    result.fetchone = AsyncMock(side_effect=[("a" * 500,), ("b" * 500,)])
    result.close = AsyncMock()
    conn = MagicMock()
    conn.stream = AsyncMock(return_value=result)

    @asynccontextmanager
    async def get_connection():
        yield conn

    connection = MagicMock(dialect="postgresql")
    connection.get_connection = get_connection
    executor = QueryExecutor(connection, MagicMock())
    with pytest.raises(ValueError, match="bytes"):
        await executor.execute_query("SELECT value FROM t", max_result_bytes=400)
    assert result.fetchone.await_count == 1
    result.close.assert_awaited_once()
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_stream_metadata_budget_and_truncation() -> None:
    result = MagicMock()
    result.keys.return_value = ["n"]
    result.fetchone = AsyncMock(side_effect=[(1,), (2,), (3,)])
    result.close = AsyncMock()
    conn = MagicMock()
    conn.stream = AsyncMock(return_value=result)

    @asynccontextmanager
    async def get_connection():
        yield conn

    connection = MagicMock(dialect="mysql")
    connection.get_connection = get_connection
    executor = QueryExecutor(connection, MagicMock())
    output = await executor.execute_query("SELECT n FROM t", limit=2)
    assert output.rows == [{"n": 1}, {"n": 2}]
    assert output.truncated
    assert output.row_count == 2
    assert result.fetchone.await_count == 3
    result.close.assert_awaited_once()
    assert len(orjson.dumps(output.model_dump(mode="json"))) > 0
