"""Module Tests for QueryExecutor

Tests the QueryExecutor component directly without MCP protocol overhead.
Validates:
- Query execution with proper validation
- Data sampling from tables
- Read-only enforcement
- Query result serialization
- Data type handling
"""

import json

import pytest

from db_connect_mcp.adapters.base import BaseAdapter
from db_connect_mcp.core import DatabaseConnection, MetadataInspector, QueryExecutor

pytestmark = [pytest.mark.postgresql, pytest.mark.integration]


class TestQueryExecutorBasic:
    """Test basic query execution functionality."""

    @pytest.mark.asyncio
    async def test_execute_query(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test execute_query runs SELECT queries correctly."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        # Simple query
        result = await executor.execute_query("SELECT 1 as test_col", limit=10)

        # Validate result structure
        assert result.query is not None
        assert result.row_count == 1
        assert len(result.columns) == 1
        assert result.columns[0] == "test_col"
        assert len(result.rows) == 1
        assert result.rows[0]["test_col"] == 1
        assert result.execution_time_ms is not None
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_execute_query_with_limit(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test that query limit is enforced."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        # Query that would return multiple rows
        result = await executor.execute_query(
            "SELECT generate_series(1, 100) as num", limit=5
        )

        # Should be limited to 5 rows
        assert result.row_count <= 5
        assert len(result.rows) <= 5

    @pytest.mark.asyncio
    async def test_execute_query_with_cte(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test executing queries with CTEs."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        query = """
        WITH sample AS (
            SELECT 1 as id, 'test' as name
            UNION ALL
            SELECT 2, 'test2'
        )
        SELECT * FROM sample
        """

        result = await executor.execute_query(query, limit=10)

        assert result.row_count == 2
        assert "id" in result.columns
        assert "name" in result.columns


class TestQueryExecutorSampling:
    """Test data sampling functionality."""

    @pytest.mark.asyncio
    async def test_sample_data(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test sample_data with various data types."""
        executor = QueryExecutor(pg_connection, pg_adapter)
        inspector = MetadataInspector(pg_connection, pg_adapter)

        # Get a table
        tables = await inspector.get_tables("public")
        if not tables:
            pytest.skip("No tables available for testing")

        table_name = tables[0].name

        # Sample data
        result = await executor.sample_data(table_name, "public", limit=5)

        # Validate result
        assert result.row_count >= 0
        assert len(result.columns) > 0

    @pytest.mark.asyncio
    async def test_sample_data_json_serialization(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test sample_data with JSON serialization - this was BROKEN."""
        executor = QueryExecutor(pg_connection, pg_adapter)
        inspector = MetadataInspector(pg_connection, pg_adapter)

        # Get a table
        tables = await inspector.get_tables("public")
        if not tables:
            pytest.skip("No tables available for testing")

        table_name = tables[0].name

        # Sample data - this used to fail with JSON serialization errors
        result = await executor.sample_data(table_name, "public", limit=5)

        # Critical: Verify JSON serialization works
        try:
            json_str = json.dumps(result.model_dump())
            assert len(json_str) > 0
        except TypeError as e:
            pytest.fail(f"JSON serialization failed: {e}")

        # Verify rows are JSON-safe
        for row in result.rows:
            try:
                json.dumps(row)
            except TypeError as e:
                pytest.fail(f"Row data not JSON-safe: {e}")


class TestQueryExecutorReadOnly:
    """Test read-only enforcement."""

    @pytest.mark.asyncio
    async def test_write_query_rejected(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test that write queries are rejected."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        # Try various write operations - all should be rejected
        write_queries = [
            "DROP TABLE users",
            "DELETE FROM users WHERE id = 1",
            "UPDATE users SET name = 'test'",
            "INSERT INTO users (name) VALUES ('test')",
            "CREATE TABLE test (id INT)",
            "ALTER TABLE users ADD COLUMN test INT",
        ]

        for query in write_queries:
            with pytest.raises(Exception) as exc_info:
                await executor.execute_query(query, limit=10)

            # Verify it's a validation error, not a database error
            error_msg = str(exc_info.value).lower()
            assert any(
                phrase in error_msg
                for phrase in [
                    "read-only",
                    "are allowed",
                    "only",
                    "queries are allowed",
                    "dangerous",
                ]
            )


class TestQueryExecutorDataTypes:
    """Test handling of various data types."""

    @pytest.mark.asyncio
    async def test_timestamp_columns(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test TIMESTAMP columns serialize correctly."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        # Query with timestamp
        result = await executor.execute_query(
            "SELECT NOW() as ts, CURRENT_DATE as dt, CURRENT_TIME as tm", limit=1
        )

        assert len(result.rows) == 1
        row = result.rows[0]

        # Verify timestamp values are JSON-safe (ISO strings)
        assert isinstance(row["ts"], str)
        assert isinstance(row["dt"], str)
        assert isinstance(row["tm"], str)

        # Verify full JSON serialization works
        json.dumps(result.model_dump())

    @pytest.mark.asyncio
    async def test_inet_columns(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test INET columns serialize correctly."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        # Query with INET type
        result = await executor.execute_query(
            "SELECT '192.168.1.1'::inet as ip4, '::1'::inet as ip6", limit=1
        )

        assert len(result.rows) == 1
        row = result.rows[0]

        # Verify IP addresses are strings
        assert isinstance(row["ip4"], str)
        assert isinstance(row["ip6"], str)
        assert "192.168.1.1" in row["ip4"]

        # Verify full JSON serialization works
        json.dumps(result.model_dump())

    @pytest.mark.asyncio
    async def test_uuid_columns(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test UUID columns serialize correctly."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        # Query with UUID
        result = await executor.execute_query("SELECT gen_random_uuid() as id", limit=1)

        assert len(result.rows) == 1
        row = result.rows[0]

        # Verify UUID is string
        assert isinstance(row["id"], str)
        assert len(row["id"]) == 36  # UUID string length

        # Verify full JSON serialization works
        json.dumps(result.model_dump())

    @pytest.mark.asyncio
    async def test_numeric_types(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test various numeric types."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        result = await executor.execute_query(
            """
            SELECT
                1::INTEGER as int_col,
                9223372036854775807::BIGINT as bigint_col,
                3.14::NUMERIC as numeric_col,
                2.718::REAL as real_col,
                1.414::DOUBLE PRECISION as double_col
            """,
            limit=1,
        )

        row = result.rows[0]

        # All numeric types should be JSON-serializable
        assert isinstance(row["int_col"], (int, float, str))
        assert isinstance(row["bigint_col"], (int, float, str))
        assert isinstance(row["numeric_col"], (int, float, str))
        assert isinstance(row["real_col"], (int, float, str))
        assert isinstance(row["double_col"], (int, float, str))

        json.dumps(result.model_dump())


class TestQueryExecutorExplain:
    """Test query explanation functionality."""

    @pytest.mark.asyncio
    async def test_explain_query_format(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test explain_query returns properly formatted plan."""
        if not pg_adapter.capabilities.explain_plans:
            pytest.skip("Database doesn't support EXPLAIN")

        executor = QueryExecutor(pg_connection, pg_adapter)

        # Simple query to explain
        plan = await executor.explain_query("SELECT 1", analyze=False)

        # Validate plan structure
        assert plan.query == "SELECT 1"
        assert plan.plan is not None
        assert len(plan.plan) > 0

        # plan_json should be parsed dict, not escaped string
        if plan.plan_json is not None:
            assert isinstance(plan.plan_json, (dict, list)), (
                f"plan_json should be dict/list, not string: {type(plan.plan_json)}"
            )

            # Verify it's proper JSON structure
            try:
                json.dumps(plan.plan_json)
            except TypeError as e:
                pytest.fail(f"plan_json not JSON-safe: {e}")

    @pytest.mark.asyncio
    async def test_explain_query_with_analyze(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test EXPLAIN ANALYZE (actual query execution)."""
        if not pg_adapter.capabilities.explain_plans:
            pytest.skip("Database doesn't support EXPLAIN")

        executor = QueryExecutor(pg_connection, pg_adapter)

        # Simple query to explain with analyze
        plan = await executor.explain_query("SELECT 1", analyze=True)

        # Should have actual timing information
        assert plan.plan is not None
        # Analyze mode should include actual execution info
        assert "actual" in plan.plan.lower() or plan.actual_rows is not None


class TestQueryExecutorEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_result_set(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test query that returns no rows."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        result = await executor.execute_query("SELECT 1 WHERE FALSE", limit=10)

        assert result.row_count == 0
        assert len(result.rows) == 0
        assert len(result.columns) > 0  # Still has column metadata

    @pytest.mark.asyncio
    async def test_query_with_null_values(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test query with NULL values."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        result = await executor.execute_query(
            "SELECT NULL as null_col, 1 as int_col", limit=1
        )

        row = result.rows[0]
        assert row["null_col"] is None
        assert row["int_col"] == 1

        # Should be JSON-serializable
        json.dumps(result.model_dump())

    @pytest.mark.asyncio
    async def test_invalid_sql_syntax(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test that invalid SQL raises appropriate error."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        with pytest.raises(Exception):
            await executor.execute_query("SELECT * FROM", limit=10)
