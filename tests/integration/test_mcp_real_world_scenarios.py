"""Real-world scenario tests using MCP client.

These tests simulate realistic usage patterns that an LLM client would perform,
testing complete workflows rather than individual tool calls.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import pytest
from mcp import ClientSession

from db_connect_mcp.models.config import DatabaseConfig
from .test_mcp_protocol import MCPProtocolHelper


@asynccontextmanager
async def mcp_client(config: DatabaseConfig) -> AsyncGenerator[ClientSession, None]:
    """Context manager that creates MCP server and client, handles cleanup."""
    server, client = await MCPProtocolHelper.create_test_server_and_client(config)
    try:
        yield client
    finally:
        await server.cleanup()


async def call_tool(client: ClientSession, name: str, args: dict) -> dict[str, Any]:
    """Helper to call a tool and parse response."""
    response = await client.call_tool(name, arguments=args)
    return MCPProtocolHelper.check_and_parse_response(response)


@pytest.fixture
async def pg_client(pg_config: DatabaseConfig) -> AsyncGenerator[ClientSession, None]:
    """PostgreSQL MCP client fixture."""
    async with mcp_client(pg_config) as client:
        yield client


@pytest.mark.postgresql
@pytest.mark.integration
@pytest.mark.xdist_group(name="mcp_real_world")
class TestDatabaseExplorationWorkflow:
    """Tests simulating a user exploring an unknown database."""

    @pytest.mark.asyncio
    async def test_discover_database_structure(self, pg_client: ClientSession):
        """Simulate discovering database structure from scratch.

        Workflow:
        1. Get database info to understand the system
        2. List all schemas
        3. List tables in public schema
        4. Describe a specific table
        5. Get sample data to understand data patterns
        """
        # Step 1: Get database info
        db_info = await call_tool(pg_client, "get_database_info", {})
        assert db_info["dialect"] == "postgresql"
        assert db_info["read_only"] is True

        # Step 2: List schemas
        schemas = await call_tool(pg_client, "list_schemas", {})
        schema_names = [s["name"] for s in schemas]
        assert "public" in schema_names

        # Step 3: List tables in public schema
        tables = await call_tool(pg_client, "list_tables", {"schema": "public"})
        table_names = [t["name"] for t in tables]
        assert len(table_names) > 0

        # Step 4: Describe first table
        first_table = table_names[0]
        table_info = await call_tool(
            pg_client, "describe_table", {"table": first_table, "schema": "public"}
        )
        assert "columns" in table_info
        assert len(table_info["columns"]) > 0

        # Step 5: Get sample data
        sample = await call_tool(
            pg_client,
            "sample_data",
            {"table": first_table, "schema": "public", "limit": 5},
        )
        assert "rows" in sample

    @pytest.mark.asyncio
    async def test_analyze_data_quality(self, pg_client: ClientSession):
        """Simulate analyzing data quality of a table.

        Workflow:
        1. Describe the table to get column list
        2. Analyze each column to check for nulls, cardinality
        3. Look for potential data issues
        """
        # Get table structure
        table_info = await call_tool(
            pg_client, "describe_table", {"table": "users", "schema": "public"}
        )

        columns = [c["name"] for c in table_info["columns"]]

        # Analyze key columns
        for col in ["email", "created_at"]:
            if col in columns:
                stats = await call_tool(
                    pg_client,
                    "analyze_column",
                    {"table": "users", "column": col, "schema": "public"},
                )

                # Verify we got meaningful statistics
                assert stats["column"] == col
                assert stats["total_rows"] >= 0
                assert stats["null_count"] >= 0

    @pytest.mark.asyncio
    async def test_discover_relationships(self, pg_client: ClientSession):
        """Simulate discovering table relationships.

        Workflow:
        1. List all tables
        2. Get relationships for each table
        3. Build a mental model of the database
        """
        tables = await call_tool(pg_client, "list_tables", {"schema": "public"})
        # Filter for base tables (excludes views)
        table_names = [
            t["name"]
            for t in tables
            if t["table_type"].upper() in ("TABLE", "BASE TABLE")
        ]

        relationship_map = {}

        for table_name in table_names[:5]:  # Check first 5 tables
            try:
                rels = await call_tool(
                    pg_client,
                    "get_table_relationships",
                    {"table": table_name, "schema": "public"},
                )
                if rels:
                    relationship_map[table_name] = [
                        {"to": r["to_table"], "columns": r["from_columns"]}
                        for r in rels
                    ]
            except Exception:
                # Some tables may not have relationships
                pass

        # Verify we found some relationships
        assert len(relationship_map) > 0


@pytest.mark.postgresql
@pytest.mark.integration
@pytest.mark.xdist_group(name="mcp_real_world")
class TestQueryWorkflow:
    """Tests simulating various query workflows."""

    @pytest.mark.asyncio
    async def test_build_complex_query_step_by_step(self, pg_client: ClientSession):
        """Simulate building a complex query step by step.

        Workflow:
        1. Start with simple SELECT to verify data
        2. Add WHERE clause
        3. Add JOIN
        4. Check explain plan
        """
        # Step 1: Simple SELECT
        simple = await call_tool(
            pg_client,
            "execute_query",
            {"query": "SELECT * FROM products LIMIT 3"},
        )
        assert simple["row_count"] == 3

        # Step 2: Add WHERE clause
        filtered = await call_tool(
            pg_client,
            "execute_query",
            {"query": "SELECT * FROM products WHERE price > 10 LIMIT 10"},
        )
        assert "rows" in filtered

        # Step 3: Add JOIN
        joined = await call_tool(
            pg_client,
            "execute_query",
            {
                "query": """
                SELECT p.name, c.name as category
                FROM products p
                JOIN categories c ON p.category_id = c.category_id
                LIMIT 10
                """
            },
        )
        assert "category" in joined["columns"]

        # Step 4: Explain the query
        plan = await call_tool(
            pg_client,
            "explain_query",
            {
                "query": """
                SELECT p.name, c.name as category
                FROM products p
                JOIN categories c ON p.category_id = c.category_id
                WHERE p.price > 50
                """
            },
        )
        assert "plan" in plan
        assert len(plan["plan"]) > 0

    @pytest.mark.asyncio
    async def test_aggregate_query_workflow(self, pg_client: ClientSession):
        """Simulate running aggregate queries for reporting."""
        # Count by category
        count_query = await call_tool(
            pg_client,
            "execute_query",
            {
                "query": """
                SELECT c.name as category, COUNT(*) as product_count
                FROM products p
                JOIN categories c ON p.category_id = c.category_id
                GROUP BY c.name
                ORDER BY product_count DESC
                """
            },
        )
        assert "category" in count_query["columns"]
        assert "product_count" in count_query["columns"]

        # Average price by category
        avg_query = await call_tool(
            pg_client,
            "execute_query",
            {
                "query": """
                SELECT c.name as category, AVG(p.price) as avg_price
                FROM products p
                JOIN categories c ON p.category_id = c.category_id
                GROUP BY c.name
                HAVING COUNT(*) > 1
                """
            },
        )
        assert "avg_price" in avg_query["columns"]


@pytest.mark.postgresql
@pytest.mark.integration
@pytest.mark.xdist_group(name="mcp_real_world")
class TestEdgeCasesAndErrorHandling:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_table_handling(self, pg_client: ClientSession):
        """Test handling of table that might be empty."""
        # Create a query that returns no rows
        result = await call_tool(
            pg_client,
            "execute_query",
            {"query": "SELECT * FROM products WHERE 1 = 0"},
        )
        assert result["row_count"] == 0
        assert result["rows"] == []

    @pytest.mark.asyncio
    async def test_large_limit_handling(self, pg_client: ClientSession):
        """Test that large limits are handled gracefully."""
        result = await call_tool(
            pg_client,
            "execute_query",
            {"query": "SELECT product_id, name FROM products", "limit": 500},
        )
        # Should return data without error
        # Either we get rows or a "too large" error (both are graceful handling)
        if "rows" in result:
            assert result["row_count"] >= 0
        else:
            # Response was too large - this is valid graceful handling
            assert "error" in result
            assert result["error"] == "Response too large"

    @pytest.mark.asyncio
    async def test_special_characters_in_query(self, pg_client: ClientSession):
        """Test queries with special characters."""
        result = await call_tool(
            pg_client,
            "execute_query",
            {
                "query": "SELECT 'hello''s world' as greeting, E'line1\\nline2' as multiline"
            },
        )
        assert result["row_count"] == 1
        assert "hello's world" in result["rows"][0]["greeting"]

    @pytest.mark.asyncio
    async def test_null_values_handling(self, pg_client: ClientSession):
        """Test that NULL values are properly serialized."""
        result = await call_tool(
            pg_client,
            "execute_query",
            {"query": "SELECT NULL as null_val, 1 as int_val"},
        )
        assert result["rows"][0]["null_val"] is None
        assert result["rows"][0]["int_val"] == 1

    @pytest.mark.asyncio
    async def test_unicode_data_handling(self, pg_client: ClientSession):
        """Test handling of Unicode data."""
        result = await call_tool(
            pg_client,
            "execute_query",
            {"query": "SELECT '日本語' as japanese, 'émojis: 🎉' as emoji"},
        )
        assert result["rows"][0]["japanese"] == "日本語"
        assert "🎉" in result["rows"][0]["emoji"]

    @pytest.mark.asyncio
    async def test_very_long_column_values(self, pg_client: ClientSession):
        """Test handling of very long string values."""
        long_text = "x" * 10000
        result = await call_tool(
            pg_client,
            "execute_query",
            {"query": f"SELECT '{long_text}' as long_text"},
        )
        # Should either truncate or handle gracefully
        assert result["row_count"] == 1
        assert len(result["rows"][0]["long_text"]) > 0

    @pytest.mark.asyncio
    async def test_invalid_sql_syntax_error(self, pg_client: ClientSession):
        """Test that SQL syntax errors are properly reported."""
        response = await pg_client.call_tool(
            "execute_query",
            arguments={"query": "SELEKT * FORM users"},  # intentional typo
        )
        assert response.isError

    @pytest.mark.asyncio
    async def test_nonexistent_table_error(self, pg_client: ClientSession):
        """Test error when querying nonexistent table."""
        response = await pg_client.call_tool(
            "execute_query",
            arguments={"query": "SELECT * FROM table_that_does_not_exist_xyz"},
        )
        assert response.isError

    @pytest.mark.asyncio
    async def test_sample_nonexistent_table_error(self, pg_client: ClientSession):
        """Test error when sampling nonexistent table."""
        response = await pg_client.call_tool(
            "sample_data",
            arguments={"table": "nonexistent_table_xyz", "schema": "public"},
        )
        assert response.isError


@pytest.mark.postgresql
@pytest.mark.integration
@pytest.mark.xdist_group(name="mcp_real_world")
class TestDataTypeHandling:
    """Tests for various PostgreSQL data types."""

    @pytest.mark.asyncio
    async def test_numeric_types(self, pg_client: ClientSession):
        """Test handling of various numeric types."""
        result = await call_tool(
            pg_client,
            "execute_query",
            {
                "query": """
                SELECT
                    1::smallint as small,
                    1000000::integer as medium,
                    9223372036854775807::bigint as big,
                    3.14159::real as single_precision,
                    3.14159265358979::double precision as double_precision,
                    123.456::numeric(10,3) as exact_numeric
                """
            },
        )
        row = result["rows"][0]
        assert isinstance(row["small"], int)
        assert isinstance(row["big"], int)
        assert isinstance(row["single_precision"], (float, int))

    @pytest.mark.asyncio
    async def test_date_time_types(self, pg_client: ClientSession):
        """Test handling of date/time types."""
        result = await call_tool(
            pg_client,
            "execute_query",
            {
                "query": """
                SELECT
                    CURRENT_DATE as today,
                    CURRENT_TIME as now_time,
                    CURRENT_TIMESTAMP as now_ts,
                    INTERVAL '1 hour' as one_hour
                """
            },
        )
        row = result["rows"][0]
        # All should be serialized as strings
        assert isinstance(row["today"], str)
        assert isinstance(row["now_ts"], str)

    @pytest.mark.asyncio
    async def test_json_types(self, pg_client: ClientSession):
        """Test handling of JSON types."""
        result = await call_tool(
            pg_client,
            "execute_query",
            {
                "query": """
                SELECT
                    '{"key": "value"}'::json as json_col,
                    '{"key": "value"}'::jsonb as jsonb_col,
                    '["a", "b", "c"]'::jsonb as json_array
                """
            },
        )
        row = result["rows"][0]
        # JSON should be parsed as dict/list or string
        assert row["json_col"] is not None
        assert row["jsonb_col"] is not None

    @pytest.mark.asyncio
    async def test_array_types(self, pg_client: ClientSession):
        """Test handling of array types."""
        result = await call_tool(
            pg_client,
            "execute_query",
            {
                "query": """
                SELECT
                    ARRAY[1, 2, 3] as int_array,
                    ARRAY['a', 'b', 'c'] as text_array,
                    ARRAY[[1,2], [3,4]] as nested_array
                """
            },
        )
        row = result["rows"][0]
        assert isinstance(row["int_array"], (list, str))
        assert isinstance(row["text_array"], (list, str))


@pytest.mark.postgresql
@pytest.mark.integration
@pytest.mark.xdist_group(name="mcp_real_world")
class TestPerformanceQueries:
    """Tests for query performance analysis."""

    @pytest.mark.asyncio
    async def test_explain_vs_explain_analyze(self, pg_client: ClientSession):
        """Test difference between EXPLAIN and EXPLAIN ANALYZE."""
        query = "SELECT * FROM products WHERE price > 50"

        # Regular EXPLAIN (no execution)
        explain_only = await call_tool(
            pg_client, "explain_query", {"query": query, "analyze": False}
        )
        assert "plan" in explain_only

        # EXPLAIN ANALYZE (with execution)
        explain_analyze = await call_tool(
            pg_client, "explain_query", {"query": query, "analyze": True}
        )
        assert "plan" in explain_analyze

        # ANALYZE should have execution time info
        plan_text = explain_analyze["plan"].lower()
        assert "actual" in plan_text or "time" in plan_text

    @pytest.mark.asyncio
    async def test_explain_complex_join(self, pg_client: ClientSession):
        """Test explain plan for complex join query."""
        query = """
        SELECT u.email, COUNT(o.order_id) as order_count, SUM(o.total_amount) as total_spent
        FROM users u
        LEFT JOIN orders o ON u.user_id = o.user_id
        GROUP BY u.user_id, u.email
        HAVING COUNT(o.order_id) > 0
        ORDER BY total_spent DESC
        LIMIT 10
        """
        result = await call_tool(pg_client, "explain_query", {"query": query})
        plan = result["plan"].lower()

        # Should mention various plan operations
        assert any(
            op in plan
            for op in ["sort", "aggregate", "hash", "seq scan", "index", "limit"]
        )
