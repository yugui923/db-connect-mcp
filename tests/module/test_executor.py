"""Module Tests for QueryExecutor

Tests the QueryExecutor component directly without MCP protocol overhead.
Validates:
- Query execution with proper validation
- Data sampling from tables
- Read-only enforcement
- Query result serialization
- Data type handling
"""

import pytest

from db_connect_mcp.core import QueryExecutor
from tests.conftest import assert_json_serializable

pytestmark = [pytest.mark.postgresql, pytest.mark.integration]


class TestQueryExecutorBasic:
    """Test basic query execution functionality."""

    @pytest.mark.asyncio
    async def test_execute_query(self, pg_executor: QueryExecutor):
        """Test execute_query runs SELECT queries correctly."""
        result = await pg_executor.execute_query("SELECT 1 as test_col", limit=10)

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
    async def test_execute_query_with_limit(self, pg_executor: QueryExecutor):
        """Test that query limit is enforced."""
        result = await pg_executor.execute_query(
            "SELECT generate_series(1, 100) as num", limit=5
        )

        # Should be limited to 5 rows
        assert result.row_count <= 5
        assert len(result.rows) <= 5

    @pytest.mark.asyncio
    async def test_execute_query_with_cte(self, pg_executor: QueryExecutor):
        """Test executing queries with CTEs."""
        query = """
        WITH sample AS (
            SELECT 1 as id, 'test' as name
            UNION ALL
            SELECT 2, 'test2'
        )
        SELECT * FROM sample
        """

        result = await pg_executor.execute_query(query, limit=10)

        assert result.row_count == 2
        assert "id" in result.columns
        assert "name" in result.columns


class TestQueryExecutorSampling:
    """Test data sampling functionality."""

    @pytest.mark.asyncio
    async def test_sample_data_from_known_table(self, pg_executor: QueryExecutor):
        """Test sample_data with products table (guaranteed to exist)."""
        result = await pg_executor.sample_data("products", "public", limit=5)

        # Validate result
        assert result.row_count >= 0
        assert result.row_count <= 5
        assert len(result.columns) > 0

        # products table has known columns
        expected_columns = ["product_id", "name", "price", "sku"]
        for col in expected_columns:
            assert col in result.columns, f"products table should have {col} column"

    @pytest.mark.asyncio
    async def test_sample_data_json_serialization(self, pg_executor: QueryExecutor):
        """Test sample_data with JSON serialization."""
        # Use products table which has various data types (UUID, INET, arrays, JSONB)
        result = await pg_executor.sample_data("products", "public", limit=5)

        # Critical: Verify JSON serialization works
        assert_json_serializable(result.model_dump())

        # Verify rows are JSON-safe
        for row in result.rows:
            assert_json_serializable(row)

    @pytest.mark.asyncio
    async def test_sample_data_with_all_types(self, pg_executor: QueryExecutor):
        """Test sampling from data_type_examples table (all PostgreSQL types)."""
        result = await pg_executor.sample_data("data_type_examples", "public", limit=5)

        assert result.row_count >= 0
        assert len(result.columns) > 0

        # Verify JSON serialization works with all PostgreSQL types
        assert_json_serializable(result.model_dump())


class TestQueryExecutorReadOnly:
    """Test read-only enforcement."""

    @pytest.mark.asyncio
    async def test_write_query_rejected(self, pg_executor: QueryExecutor):
        """Test that write queries are rejected."""
        # Try various write operations - all should be rejected
        write_queries = [
            "DROP TABLE products",
            "DELETE FROM products WHERE product_id = 1",
            "UPDATE products SET name = 'test'",
            "INSERT INTO products (name, price, category_id, sku) VALUES ('test', 10.00, 1, 'TEST123')",
            "CREATE TABLE test_table (id INT)",
            "ALTER TABLE products ADD COLUMN test_col INT",
            "TRUNCATE TABLE products",
        ]

        for query in write_queries:
            with pytest.raises(Exception) as exc_info:
                await pg_executor.execute_query(query, limit=10)

            # Verify it's a validation error
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
            ), f"Expected read-only error for query: {query}"


class TestQueryExecutorDataTypes:
    """Test handling of various data types using parametrization."""

    @pytest.mark.parametrize(
        "query,expected_columns,value_checks",
        [
            # Timestamp types
            (
                "SELECT NOW() as ts, CURRENT_DATE as dt, CURRENT_TIME as tm",
                ["ts", "dt", "tm"],
                {"ts": str, "dt": str, "tm": str},
            ),
            # Network types
            (
                "SELECT '192.168.1.1'::inet as ip4, '::1'::inet as ip6",
                ["ip4", "ip6"],
                {"ip4": str, "ip6": str},
            ),
            # UUID type
            (
                "SELECT gen_random_uuid() as id",
                ["id"],
                {"id": str},
            ),
            # Numeric types
            (
                "SELECT 1::INTEGER as int_col, 3.14::NUMERIC as num_col, 2.718::REAL as real_col",
                ["int_col", "num_col", "real_col"],
                {
                    "int_col": (int, float, str),
                    "num_col": (int, float, str),
                    "real_col": (int, float, str),
                },
            ),
            # Boolean type
            (
                "SELECT TRUE as bool_col, FALSE as bool_col2",
                ["bool_col", "bool_col2"],
                {"bool_col": bool, "bool_col2": bool},
            ),
            # Array types
            (
                "SELECT ARRAY[1,2,3] as int_array, ARRAY['a','b','c'] as text_array",
                ["int_array", "text_array"],
                {"int_array": list, "text_array": list},
            ),
            # JSON types
            (
                'SELECT \'{"key": "value"}\'::json as json_col, \'{"key": "value"}\'::jsonb as jsonb_col',
                ["json_col", "jsonb_col"],
                {"json_col": (dict, str), "jsonb_col": (dict, str)},
            ),
        ],
        ids=[
            "timestamp_types",
            "network_types",
            "uuid_type",
            "numeric_types",
            "boolean_type",
            "array_types",
            "json_types",
        ],
    )
    @pytest.mark.asyncio
    async def test_data_type_serialization(
        self, pg_executor: QueryExecutor, query, expected_columns, value_checks
    ):
        """Test various PostgreSQL data types serialize correctly to JSON."""
        result = await pg_executor.execute_query(query, limit=1)

        assert len(result.rows) == 1
        row = result.rows[0]

        # Verify expected columns exist
        for col in expected_columns:
            assert col in row, f"Expected column {col} in result"

        # Verify value types
        for col, expected_type in value_checks.items():
            assert isinstance(row[col], expected_type), (
                f"Column {col} should be {expected_type}, got {type(row[col])}"
            )

        # Verify full JSON serialization works
        assert_json_serializable(result.model_dump())

    @pytest.mark.asyncio
    async def test_real_table_data_types(self, pg_executor: QueryExecutor):
        """Test data types from actual table (products) with real data."""
        result = await pg_executor.execute_query(
            """
            SELECT
                product_id,
                name,
                price,
                product_uuid,
                tags,
                supplier_ip,
                created_at
            FROM products
            LIMIT 5
            """,
            limit=5,
        )

        assert len(result.rows) > 0

        # Verify all rows are JSON serializable
        for row in result.rows:
            assert_json_serializable(row)

        # Verify full result is JSON serializable
        assert_json_serializable(result.model_dump())


class TestQueryExecutorExplain:
    """Test query explanation functionality."""

    @pytest.mark.asyncio
    async def test_explain_query_format(self, pg_executor: QueryExecutor, pg_adapter):
        """Test explain_query returns properly formatted plan."""
        if not pg_adapter.capabilities.explain_plans:
            pytest.skip("Database doesn't support EXPLAIN")

        plan = await pg_executor.explain_query("SELECT 1", analyze=False)

        # Validate plan structure
        assert plan.query == "SELECT 1"
        assert plan.plan is not None
        assert len(plan.plan) > 0

        # plan_json should be parsed dict, not escaped string
        if plan.plan_json is not None:
            assert isinstance(plan.plan_json, (dict, list)), (
                f"plan_json should be dict/list, not string: {type(plan.plan_json)}"
            )
            assert_json_serializable(plan.plan_json)

    @pytest.mark.asyncio
    async def test_explain_query_with_analyze(
        self, pg_executor: QueryExecutor, pg_adapter
    ):
        """Test EXPLAIN ANALYZE (actual query execution)."""
        if not pg_adapter.capabilities.explain_plans:
            pytest.skip("Database doesn't support EXPLAIN")

        plan = await pg_executor.explain_query("SELECT 1", analyze=True)

        # Should have actual timing information
        assert plan.plan is not None
        # Analyze mode should include actual execution info
        assert "actual" in plan.plan.lower() or plan.actual_rows is not None

    @pytest.mark.asyncio
    async def test_explain_real_query(self, pg_executor: QueryExecutor, pg_adapter):
        """Test EXPLAIN on real query with known table."""
        if not pg_adapter.capabilities.explain_plans:
            pytest.skip("Database doesn't support EXPLAIN")

        plan = await pg_executor.explain_query(
            "SELECT * FROM products WHERE price > 100", analyze=False
        )

        assert plan.plan is not None
        assert "products" in plan.plan.lower()


class TestQueryExecutorEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_result_set(self, pg_executor: QueryExecutor):
        """Test query that returns no rows."""
        result = await pg_executor.execute_query("SELECT 1 WHERE FALSE", limit=10)

        assert result.row_count == 0
        assert len(result.rows) == 0
        assert len(result.columns) > 0  # Still has column metadata

    @pytest.mark.asyncio
    async def test_query_with_null_values(self, pg_executor: QueryExecutor):
        """Test query with NULL values."""
        result = await pg_executor.execute_query(
            "SELECT NULL as null_col, 1 as int_col", limit=1
        )

        row = result.rows[0]
        assert row["null_col"] is None
        assert row["int_col"] == 1

        # Should be JSON-serializable
        assert_json_serializable(result.model_dump())

    @pytest.mark.asyncio
    async def test_query_with_many_nulls(self, pg_executor: QueryExecutor):
        """Test query with data_type_examples table that has NULL values."""
        result = await pg_executor.execute_query(
            "SELECT * FROM data_type_examples WHERE id BETWEEN 101 AND 110", limit=10
        )

        # Verify NULL handling works
        assert_json_serializable(result.model_dump())

    @pytest.mark.asyncio
    async def test_invalid_sql_syntax(self, pg_executor: QueryExecutor):
        """Test that invalid SQL raises appropriate error."""
        with pytest.raises(Exception):
            await pg_executor.execute_query("SELECT * FROM INVALID SYNTAX", limit=10)

    @pytest.mark.asyncio
    async def test_nonexistent_table(self, pg_executor: QueryExecutor):
        """Test querying non-existent table raises error."""
        with pytest.raises(Exception):
            await pg_executor.execute_query(
                "SELECT * FROM nonexistent_table_xyz", limit=10
            )

    @pytest.mark.asyncio
    async def test_complex_join_query(self, pg_executor: QueryExecutor):
        """Test complex query with JOINs using known tables."""
        query = """
        SELECT
            p.name as product_name,
            c.name as category_name,
            p.price
        FROM products p
        JOIN categories c ON p.category_id = c.category_id
        LIMIT 10
        """

        result = await pg_executor.execute_query(query, limit=10)

        assert len(result.rows) > 0
        assert "product_name" in result.columns
        assert "category_name" in result.columns
        assert "price" in result.columns

        # Verify JSON serialization
        assert_json_serializable(result.model_dump())
