"""Live query result caps, including caller-authored SQL LIMIT."""

import asyncio
import json
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import create_async_engine

from db_connect_mcp.server import DatabaseMCPServer, _structured_tool_result
from db_connect_mcp.adapters import create_adapter
from db_connect_mcp.core.connection import DatabaseConnection
from db_connect_mcp.core.executor import QueryExecutor
from db_connect_mcp.models.config import DatabaseConfig


@pytest.mark.asyncio
async def test_pg_setval_cannot_persist_even_in_current_transaction(
    pg_database_url: str,
) -> None:
    # Create a unique synthetic object with a separate setup connection; never
    # modify pre-existing tables or production data.
    name = f"mcp_readonly_{uuid4().hex}"
    setup = create_async_engine(pg_database_url)
    try:
        async with setup.begin() as conn:
            await conn.execute(text(f"CREATE SEQUENCE {name}"))
        config = DatabaseConfig(url=pg_database_url)
        connection = DatabaseConnection(config)
        await connection.initialize()
        try:
            executor = QueryExecutor(connection, create_adapter(config))
            with pytest.raises(Exception, match="read-only transaction"):
                await executor.execute_query(
                    f"SELECT setval('{name}', 50) AS sequence_value", limit=1
                )
            async with setup.connect() as conn:
                value = await conn.scalar(text(f"SELECT last_value FROM {name}"))
                assert value == 1
        finally:
            await connection.dispose()
    finally:
        async with setup.begin() as conn:
            await conn.execute(text(f"DROP SEQUENCE IF EXISTS {name}"))
        await setup.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_checkout", [False, True])
async def test_pg_advisory_lock_cannot_survive_mcp_checkout(
    pg_database_url: str, fail_checkout: bool
) -> None:
    # The advisory key is synthetic, and an observer releases it if it acquires
    # it. Dispose the MCP engine even on assertion failures to release its lock.
    lock_key = uuid4().int & ((1 << 63) - 1)
    config = DatabaseConfig(url=pg_database_url)
    connection = DatabaseConnection(config)
    observer = create_async_engine(pg_database_url)
    await connection.initialize()
    try:
        try:
            async with connection.get_connection() as conn:
                result = await conn.execute(
                    text("SELECT pg_advisory_lock(:key)"), {"key": lock_key}
                )
                result.close()
                if fail_checkout:
                    raise ValueError("synthetic checkout failure")
        except ValueError:
            if not fail_checkout:
                raise
        async with observer.connect() as conn:
            acquired = await conn.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key}
            )
            if acquired:
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key}
                )
            assert acquired is True
    finally:
        await observer.dispose()
        await connection.dispose()


@pytest.mark.asyncio
async def test_quoted_pg_advisory_lock_cannot_block_mcp_query(
    pg_database_url: str,
) -> None:
    lock_key = uuid4().int & ((1 << 63) - 1)
    blocker = create_async_engine(pg_database_url)
    config = DatabaseConfig(url=pg_database_url, statement_timeout=1)
    connection = DatabaseConnection(config)
    await connection.initialize()
    try:
        async with blocker.connect() as conn:
            await conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock_key})
            try:
                executor = QueryExecutor(connection, create_adapter(config))
                with pytest.raises(ValueError, match="advisory lock"):
                    await asyncio.wait_for(
                        executor.execute_query(
                            'SELECT "pg_advisory_lock"(:key)', {"key": lock_key}
                        ),
                        timeout=3,
                    )
            finally:
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key}
                )
    finally:
        await connection.dispose()
        await blocker.dispose()


@pytest.mark.asyncio
async def test_unicode_quoted_pg_advisory_lock_cannot_block_mcp_query(
    pg_database_url: str,
) -> None:
    lock_key = uuid4().int & ((1 << 63) - 1)
    blocker = create_async_engine(pg_database_url)
    config = DatabaseConfig(url=pg_database_url, statement_timeout=1)
    connection = DatabaseConnection(config)
    await connection.initialize()
    try:
        async with blocker.connect() as conn:
            await conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock_key})
            try:
                executor = QueryExecutor(connection, create_adapter(config))
                with pytest.raises(ValueError, match="Unicode quoted identifier"):
                    await asyncio.wait_for(
                        executor.execute_query(
                            'SELECT U&"pg_advisory_lock"(:key)', {"key": lock_key}
                        ),
                        timeout=3,
                    )
            finally:
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key}
                )
    finally:
        await connection.dispose()
        await blocker.dispose()


@pytest.mark.asyncio
async def test_pg_escaped_string_cannot_hide_advisory_lock(
    pg_database_url: str,
) -> None:
    key = uuid4().int & ((1 << 63) - 1)
    config = DatabaseConfig(url=pg_database_url)
    connection = DatabaseConnection(config)
    await connection.initialize()
    try:
        executor = QueryExecutor(connection, create_adapter(config))
        with pytest.raises(ValueError, match="backslash escape"):
            await executor.execute_query(
                r"SELECT E'it\'s', pg_advisory_lock(:key) -- '", {"key": key}
            )
        observer = create_async_engine(pg_database_url)
        try:
            async with observer.connect() as conn:
                assert await conn.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
                )
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                )
        finally:
            await observer.dispose()
    finally:
        await connection.dispose()


@pytest.mark.asyncio
async def test_mysql_escaped_string_cannot_hide_named_lock(
    mysql_database_url: str,
) -> None:
    name = f"mcp_readonly_{uuid4().hex}"
    config = DatabaseConfig(url=mysql_database_url)
    connection = DatabaseConnection(config)
    await connection.initialize()
    try:
        executor = QueryExecutor(connection, create_adapter(config))
        for query in (
            r"SELECT 'it\'s', GET_LOCK(:name, 0) -- '",
            r'SELECT "it\"s", GET_LOCK(:name, 0) -- "',
        ):
            with pytest.raises(ValueError, match="backslash escape"):
                await executor.execute_query(query, {"name": name})
        observer = create_async_engine(mysql_database_url)
        try:
            async with observer.connect() as conn:
                assert (
                    await conn.scalar(
                        text("SELECT IS_FREE_LOCK(:name)"), {"name": name}
                    )
                    == 1
                )
        finally:
            await observer.dispose()
    finally:
        await connection.dispose()


@pytest.mark.asyncio
async def test_mysql_executable_comment_cannot_acquire_named_lock(
    mysql_database_url: str,
) -> None:
    lock_name = f"mcp_readonly_{uuid4().hex}"
    config = DatabaseConfig(url=mysql_database_url)
    connection = DatabaseConnection(config)
    observer = create_async_engine(mysql_database_url)
    await connection.initialize()
    try:
        executor = QueryExecutor(connection, create_adapter(config))
        with pytest.raises(ValueError, match="executable comment"):
            await executor.execute_query(
                "SELECT /*!50000 GET_LOCK(:name, 0) AS locked, */ 1 AS marker",
                {"name": lock_name},
            )
        async with observer.connect() as conn:
            assert (
                await conn.scalar(
                    text("SELECT IS_FREE_LOCK(:name)"), {"name": lock_name}
                )
                == 1
            )
    finally:
        await observer.dispose()
        await connection.dispose()


@pytest.mark.asyncio
async def test_mysql_named_lock_cannot_survive_mcp_checkout(
    mysql_database_url: str,
) -> None:
    lock_name = f"mcp_readonly_{uuid4().hex}"
    config = DatabaseConfig(url=mysql_database_url)
    connection = DatabaseConnection(config)
    await connection.initialize()
    observer = create_async_engine(mysql_database_url)
    try:
        executor = QueryExecutor(connection, create_adapter(config))
        with pytest.raises(ValueError, match="session side effect"):
            await executor.execute_query(
                "SELECT GET_LOCK(:name, 0)", {"name": lock_name}
            )
        async with connection.get_connection() as conn:
            # Validate isolation even for a session effect outside execute_query:
            # closing this checkout must close its underlying MySQL session.
            result = await conn.execute(
                text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name}
            )
            assert result.scalar() == 1
        async with observer.connect() as conn:
            result = await conn.execute(
                text("SELECT IS_FREE_LOCK(:name)"), {"name": lock_name}
            )
            assert result.scalar() == 1
    finally:
        await observer.dispose()
        await connection.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("database_url", ["pg_database_url", "mysql_database_url"])
async def test_null_pool_respects_one_connection_budget_live(
    request: pytest.FixtureRequest, database_url: str
) -> None:
    url = request.getfixturevalue(database_url)
    config = DatabaseConfig(url=url, pool_size=1, max_overflow=0, pool_timeout=1)
    connection = DatabaseConnection(config)
    await connection.initialize()
    try:
        async with connection.get_connection() as conn:
            await conn.execute(text("SELECT 1"))
            with pytest.raises(PoolTimeoutError, match="timed out"):
                async with connection.get_connection():
                    pass
        async with connection.get_connection() as conn:
            assert await conn.scalar(text("SELECT 1")) == 1
    finally:
        await connection.dispose()


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
async def test_sample_data_live_pg_large_text_and_bytea_fit_mcp(
    pg_database_url: str,
) -> None:
    config = DatabaseConfig(url=pg_database_url)
    connection = DatabaseConnection(config)
    await connection.initialize()
    try:
        server = DatabaseMCPServer.__new__(DatabaseMCPServer)
        server.executor = QueryExecutor(connection, create_adapter(config))
        for expression, column in [
            ("repeat('x', 500)", "description"),
            ("decode(repeat('78', 800000), 'hex')", "blob"),
        ]:
            # No DDL or fixture mutations: sampling a read-only set-returning
            # query exercises real PG streaming and MCP serialization.
            query = (
                f"SELECT {expression} AS {column} "
                "FROM generate_series(1, 300) AS n LIMIT 300"
            )
            server.executor.adapter.get_sample_query = AsyncMock(return_value=query)
            content = await server.handle_sample_data(
                {"table": "synthetic", "limit": 300}
            )
            payload = json.loads(content[0].text)
            assert "error" not in payload
            assert len(content[0].text) <= 100_000
            structured, is_error = _structured_tool_result("sample_data", content)
            assert not is_error
            assert structured["rows"]
            assert structured["row_count"] == len(structured["rows"])
            assert structured["truncated"] is True
            assert "rows" in structured["_truncation_info"]["truncated_fields"]
            if column == "blob":
                assert len(structured["rows"][0][column]) == 500
                assert (
                    f"rows[].{column}"
                    in structured["_truncation_info"]["truncated_fields"]
                )
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
