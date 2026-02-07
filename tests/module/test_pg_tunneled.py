"""Module Tests for PostgreSQL via SSH Tunnel

Tests the core components (inspector, executor, analyzer) with PostgreSQL
accessed through SSH tunnel to validate tunnel works with PG protocol.
"""

import pytest

from db_connect_mcp.core import MetadataInspector, QueryExecutor, StatisticsAnalyzer
from tests.conftest import assert_json_serializable

pytestmark = [pytest.mark.postgresql, pytest.mark.ssh_tunnel]


# ==================== Inspector ====================


class TestPGTunneledInspectorSchemas:
    """Test schema listing for PostgreSQL via SSH tunnel."""

    @pytest.mark.asyncio
    async def test_list_schemas(self, pg_tunnel_inspector: MetadataInspector):
        schemas = await pg_tunnel_inspector.get_schemas()
        assert len(schemas) > 0
        public = next((s for s in schemas if s.name == "public"), None)
        assert public is not None, "public schema should exist"
        assert public.table_count is not None
        assert public.table_count >= 5


class TestPGTunneledInspectorTables:
    """Test table listing and description for PostgreSQL via SSH tunnel."""

    @pytest.mark.asyncio
    async def test_list_tables(self, pg_tunnel_inspector: MetadataInspector):
        tables = await pg_tunnel_inspector.get_tables("public")
        table_names = {t.name for t in tables}
        assert "categories" in table_names
        assert "products" in table_names
        assert "users" in table_names
        assert "orders" in table_names

    @pytest.mark.asyncio
    async def test_describe_table_products(
        self, pg_tunnel_inspector: MetadataInspector
    ):
        table = await pg_tunnel_inspector.describe_table("products", "public")
        assert table is not None
        assert table.name == "products"
        col_names = [c.name for c in table.columns]
        assert "product_id" in col_names
        assert "price" in col_names
        assert "category_id" in col_names

    @pytest.mark.asyncio
    async def test_describe_table_has_indexes(
        self, pg_tunnel_inspector: MetadataInspector
    ):
        table = await pg_tunnel_inspector.describe_table("products", "public")
        assert table is not None
        assert table.indexes is not None
        assert len(table.indexes) > 0


class TestPGTunneledInspectorRelationships:
    """Test FK detection for PostgreSQL via SSH tunnel."""

    @pytest.mark.asyncio
    async def test_get_relationships(self, pg_tunnel_inspector: MetadataInspector):
        relationships = await pg_tunnel_inspector.get_relationships(
            "products", "public"
        )
        assert len(relationships) > 0
        assert relationships[0].from_table == "products"
        assert "category_id" in relationships[0].from_columns


# ==================== Executor ====================


class TestPGTunneledExecutorBasic:
    """Test basic query execution on PostgreSQL via SSH tunnel."""

    @pytest.mark.asyncio
    async def test_execute_simple_query(self, pg_tunnel_executor: QueryExecutor):
        result = await pg_tunnel_executor.execute_query(
            "SELECT 1 as test_col", limit=10
        )
        assert result.row_count == 1
        assert result.rows[0]["test_col"] == 1

    @pytest.mark.asyncio
    async def test_execute_query_with_limit(self, pg_tunnel_executor: QueryExecutor):
        result = await pg_tunnel_executor.execute_query(
            "SELECT * FROM products", limit=3
        )
        assert result.row_count <= 3

    @pytest.mark.asyncio
    async def test_query_result_serializable(self, pg_tunnel_executor: QueryExecutor):
        result = await pg_tunnel_executor.execute_query(
            "SELECT * FROM products LIMIT 5", limit=5
        )
        assert_json_serializable(result.model_dump())

    @pytest.mark.asyncio
    async def test_execute_query_with_cte(self, pg_tunnel_executor: QueryExecutor):
        result = await pg_tunnel_executor.execute_query(
            """
            WITH sample AS (
                SELECT 1 as id, 'test' as name
                UNION ALL
                SELECT 2, 'test2'
            )
            SELECT * FROM sample
            """,
            limit=10,
        )
        assert result.row_count == 2

    @pytest.mark.asyncio
    async def test_execute_query_with_join(self, pg_tunnel_executor: QueryExecutor):
        result = await pg_tunnel_executor.execute_query(
            """
            SELECT p.name, c.name as category_name, p.price
            FROM products p
            JOIN categories c ON p.category_id = c.category_id
            LIMIT 5
            """,
            limit=10,
        )
        assert result.row_count > 0
        assert "category_name" in result.columns


class TestPGTunneledExecutorSampling:
    """Test data sampling on PostgreSQL via SSH tunnel."""

    @pytest.mark.asyncio
    async def test_sample_data(self, pg_tunnel_executor: QueryExecutor):
        result = await pg_tunnel_executor.sample_data("products", "public", limit=5)
        assert result.row_count > 0
        assert result.row_count <= 5


class TestPGTunneledExecutorReadOnly:
    """Test read-only enforcement on PostgreSQL via SSH tunnel."""

    @pytest.mark.asyncio
    async def test_reject_drop(self, pg_tunnel_executor: QueryExecutor):
        with pytest.raises(ValueError):
            await pg_tunnel_executor.execute_query("DROP TABLE products", limit=10)

    @pytest.mark.asyncio
    async def test_reject_delete(self, pg_tunnel_executor: QueryExecutor):
        with pytest.raises(ValueError):
            await pg_tunnel_executor.execute_query(
                "DELETE FROM products WHERE product_id = 1", limit=10
            )

    @pytest.mark.asyncio
    async def test_reject_insert(self, pg_tunnel_executor: QueryExecutor):
        with pytest.raises(ValueError):
            await pg_tunnel_executor.execute_query(
                "INSERT INTO products (name, price) VALUES ('test', 1.00)", limit=10
            )


# ==================== Analyzer ====================


class TestPGTunneledAnalyzer:
    """Test column analysis on PostgreSQL via SSH tunnel."""

    @pytest.mark.asyncio
    async def test_analyze_numeric_column(self, pg_tunnel_analyzer: StatisticsAnalyzer):
        stats = await pg_tunnel_analyzer.analyze_column("products", "price", "public")
        assert stats is not None
        assert stats.column == "price"
        assert stats.total_rows > 0

    @pytest.mark.asyncio
    async def test_analyze_numeric_serializable(
        self, pg_tunnel_analyzer: StatisticsAnalyzer
    ):
        stats = await pg_tunnel_analyzer.analyze_column("products", "price", "public")
        assert_json_serializable(stats.model_dump())

    @pytest.mark.asyncio
    async def test_analyze_text_column(self, pg_tunnel_analyzer: StatisticsAnalyzer):
        stats = await pg_tunnel_analyzer.analyze_column("products", "name", "public")
        assert stats is not None
        assert stats.column == "name"
        assert stats.total_rows > 0
