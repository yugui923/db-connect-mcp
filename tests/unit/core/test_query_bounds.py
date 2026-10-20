"""Query result upper-bound regressions."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import orjson

import pytest

from db_connect_mcp.core.executor import QueryExecutor
from db_connect_mcp.server import DatabaseMCPServer, _structured_tool_result


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


@pytest.mark.parametrize(
    "query",
    [
        "SELECT GET_LOCK('health-check', 0)",
        "WITH q AS (SELECT GET_LOCK('health-check', 0)) SELECT * FROM q",
        "SELECT RELEASE_LOCK('health-check')",
        "SELECT RELEASE_ALL_LOCKS()",
        "SELECT @session_key := 'persisted'",
    ],
)
def test_mysql_rejects_session_side_effects(query: str) -> None:
    connection = MagicMock(dialect="mysql")
    executor = QueryExecutor(connection, MagicMock())
    with pytest.raises(ValueError, match="session side effect"):
        executor._validate_query(query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT pg_advisory_lock(42)",
        "WITH q AS (SELECT pg_advisory_lock_shared(42)) SELECT * FROM q",
        "SELECT pg_try_advisory_lock(42)",
        "SELECT pg_advisory_xact_lock(42)",
        'SELECT "pg_advisory_lock"(42)',
        'SELECT pg_catalog."pg_try_advisory_lock_shared"(42)',
        'WITH q AS (SELECT "pg_advisory_xact_lock"(42)) SELECT * FROM q',
    ],
)
def test_postgres_rejects_session_and_transaction_advisory_locks(query: str) -> None:
    executor = QueryExecutor(MagicMock(dialect="postgresql"), MagicMock())
    with pytest.raises(ValueError, match="advisory lock"):
        executor._validate_query(query)


def test_postgres_allows_advisory_lock_name_in_literal_and_comment() -> None:
    executor = QueryExecutor(MagicMock(dialect="postgresql"), MagicMock())
    executor._validate_query("SELECT 'pg_advisory_lock(42)' /* pg_advisory_lock(42) */")


@pytest.mark.parametrize(
    "query",
    [
        "SELECT /*!50000 GET_LOCK('name', 0) AS locked, */ 1 AS marker",
        "SELECT /*! SET @session_key := 1 */ 1",
        "SELECT /*+ MAX_EXECUTION_TIME(1000) */ 1",
    ],
)
def test_mysql_rejects_executable_comments(query: str) -> None:
    executor = QueryExecutor(MagicMock(dialect="mysql"), MagicMock())
    with pytest.raises(ValueError, match="executable comment"):
        executor._validate_query(query)


def test_mysql_allows_executable_comment_text_in_literal() -> None:
    executor = QueryExecutor(MagicMock(dialect="mysql"), MagicMock())
    executor._validate_query("SELECT '/*!50000 GET_LOCK(42, 0) */' AS note")


def test_mysql_allows_lock_name_as_string_literal() -> None:
    executor = QueryExecutor(MagicMock(dialect="mysql"), MagicMock())
    executor._validate_query("SELECT 'GET_LOCK' AS function_name")


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


@pytest.mark.asyncio
async def test_execute_query_handler_transmits_many_short_rows() -> None:
    result = MagicMock()
    result.keys.return_value = ["n"]
    result.fetchone = AsyncMock(side_effect=[(i,) for i in range(7000)] + [None])
    result.close = AsyncMock()
    conn = MagicMock()
    conn.stream = AsyncMock(return_value=result)

    @asynccontextmanager
    async def get_connection():
        yield conn

    connection = MagicMock(dialect="postgresql")
    connection.get_connection = get_connection
    server = DatabaseMCPServer.__new__(DatabaseMCPServer)
    server.executor = QueryExecutor(connection, MagicMock())
    content = await server.handle_execute_query(
        {"query": "SELECT n FROM t", "limit": 7000}
    )
    payload = json.loads(content[0].text)
    assert payload["row_count"] == 7000
    assert len(payload["rows"]) == 7000
    assert len(content[0].text) <= 100_000


@pytest.mark.asyncio
async def test_sample_data_marks_full_adapter_limited_result_as_possibly_truncated() -> (
    None
):
    result = MagicMock()
    result.keys.return_value = ["n"]
    result.fetchone = AsyncMock(side_effect=[(1,), (2,), None])
    result.close = AsyncMock()
    conn = MagicMock()
    conn.stream = AsyncMock(return_value=result)

    @asynccontextmanager
    async def get_connection():
        yield conn

    connection = MagicMock(dialect="postgresql")
    connection.get_connection = get_connection
    adapter = MagicMock()
    adapter.get_sample_query = AsyncMock(return_value="SELECT n FROM t LIMIT 2")
    output = await QueryExecutor(connection, adapter).sample_data("t", limit=2)
    assert output.row_count == 2
    assert output.truncated is True
    assert output.warning


@pytest.mark.asyncio
async def test_sample_data_truncates_large_cell_before_byte_budget() -> None:
    result = MagicMock()
    result.keys.return_value = ["description"]
    result.fetchone = AsyncMock(side_effect=[("x" * 1_100_000,), None])
    result.close = AsyncMock()
    conn = MagicMock()
    conn.stream = AsyncMock(return_value=result)

    @asynccontextmanager
    async def get_connection():
        yield conn

    connection = MagicMock(dialect="postgresql")
    connection.get_connection = get_connection
    adapter = MagicMock()
    adapter.get_sample_query = AsyncMock(
        return_value="SELECT description FROM t LIMIT 2"
    )
    server = DatabaseMCPServer.__new__(DatabaseMCPServer)
    server.executor = QueryExecutor(connection, adapter)
    content = await server.handle_sample_data({"table": "t", "limit": 2})
    payload = json.loads(content[0].text)
    assert payload["data"]["rows"][0]["description"] == "x" * 497 + "..."
    assert "rows[].description" in payload["_truncation_info"]["truncated_fields"]


@pytest.mark.asyncio
async def test_sample_data_preserves_rows_within_mcp_budget() -> None:
    result = MagicMock()
    result.keys.return_value = ["description"]
    result.fetchone = AsyncMock(side_effect=[("x" * 500,) for _ in range(300)] + [None])
    result.close = AsyncMock()
    conn = MagicMock()
    conn.stream = AsyncMock(return_value=result)

    @asynccontextmanager
    async def get_connection():
        yield conn

    connection = MagicMock(dialect="postgresql")
    connection.get_connection = get_connection
    adapter = MagicMock()
    adapter.get_sample_query = AsyncMock(
        return_value="SELECT description FROM t LIMIT 300"
    )
    server = DatabaseMCPServer.__new__(DatabaseMCPServer)
    server.executor = QueryExecutor(connection, adapter)
    content = await server.handle_sample_data({"table": "t", "limit": 300})
    payload = json.loads(content[0].text)
    assert "error" not in payload
    structured, is_error = _structured_tool_result("sample_data", content)
    assert not is_error
    assert len(content[0].text) <= 100_000
    assert 0 < structured["row_count"] == len(structured["rows"]) < 300
    assert structured["truncated"] is True
    assert "rows" in structured["_truncation_info"]["truncated_fields"]
    assert result.close.await_count == 1


@pytest.mark.asyncio
async def test_sample_data_omits_preview_marker_when_only_dropped_row_is_previewed() -> (
    None
):
    result = MagicMock()
    result.keys.return_value = ["description"]
    result.fetchone = AsyncMock(
        side_effect=[("x" * 500,) for _ in range(300)] + [("y" * 1000,), None]
    )
    result.close = AsyncMock()
    conn = MagicMock()
    conn.stream = AsyncMock(return_value=result)

    @asynccontextmanager
    async def get_connection():
        yield conn

    connection = MagicMock(dialect="postgresql")
    connection.get_connection = get_connection
    adapter = MagicMock()
    adapter.get_sample_query = AsyncMock(
        return_value="SELECT description FROM t LIMIT 301"
    )
    server = DatabaseMCPServer.__new__(DatabaseMCPServer)
    server.executor = QueryExecutor(connection, adapter)
    content = await server.handle_sample_data({"table": "t", "limit": 301})
    legacy = json.loads(content[0].text)
    structured, is_error = _structured_tool_result("sample_data", content)

    assert not is_error
    assert legacy["data"]["rows"] == structured["rows"]
    assert legacy["_truncation_info"] == structured["_truncation_info"]
    assert 0 < structured["row_count"] == len(structured["rows"]) < 300
    assert structured["truncated"] is True
    assert structured["_truncation_info"]["truncated_fields"] == ["rows"]
    assert result.close.await_count == 1


@pytest.mark.asyncio
async def test_sample_data_previews_binary_before_byte_budget() -> None:
    result = MagicMock()
    result.keys.return_value = ["blob"]
    result.fetchone = AsyncMock(side_effect=[(b"x" * 1_100_000,), None])
    result.close = AsyncMock()
    conn = MagicMock()
    conn.stream = AsyncMock(return_value=result)

    @asynccontextmanager
    async def get_connection():
        yield conn

    connection = MagicMock(dialect="postgresql")
    connection.get_connection = get_connection
    adapter = MagicMock()
    adapter.get_sample_query = AsyncMock(return_value="SELECT blob FROM t LIMIT 2")
    server = DatabaseMCPServer.__new__(DatabaseMCPServer)
    server.executor = QueryExecutor(connection, adapter)
    content = await server.handle_sample_data({"table": "t", "limit": 2})
    payload = json.loads(content[0].text)
    assert len(payload["data"]["rows"][0]["blob"]) == 500
    assert payload["data"]["rows"][0]["blob"].endswith("...")
    assert "rows[].blob" in payload["_truncation_info"]["truncated_fields"]


def test_execute_query_description_excludes_rejected_explain() -> None:
    server = DatabaseMCPServer.__new__(DatabaseMCPServer)
    tool = server._create_execute_query_tool()
    assert "SELECT" in tool.description
    assert "WITH" in tool.description
    assert "EXPLAIN" not in tool.description
