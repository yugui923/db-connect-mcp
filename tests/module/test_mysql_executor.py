"""Module Tests for MySQL QueryExecutor (via SSH Tunnel)

Tests the QueryExecutor component with MySQL accessed through SSH tunnel.
Validates:
- Query execution with proper validation
- Data sampling from tables
- Read-only enforcement
- Query result serialization
"""

import pytest

from db_connect_mcp.core import QueryExecutor
from tests.conftest import assert_json_serializable

pytestmark = [pytest.mark.mysql, pytest.mark.ssh_tunnel]


class TestMySQLExecutorBasic:
    """Test basic query execution on MySQL."""

    @pytest.mark.asyncio
    async def test_execute_simple_query(self, mysql_executor: QueryExecutor):
        """Test execute_query runs SELECT queries correctly."""
        result = await mysql_executor.execute_query("SELECT 1 as test_col", limit=10)

        assert result.query is not None
        assert result.row_count == 1
        assert len(result.columns) == 1
        assert result.columns[0] == "test_col"
        assert result.rows[0]["test_col"] == 1

    @pytest.mark.asyncio
    async def test_execute_query_with_limit(self, mysql_executor: QueryExecutor):
        """Test that query limit is enforced."""
        result = await mysql_executor.execute_query(
            "SELECT * FROM products", limit=2
        )

        assert result.row_count <= 2
        assert len(result.rows) <= 2

    @pytest.mark.asyncio
    async def test_query_result_serializable(self, mysql_executor: QueryExecutor):
        """Test that query results are JSON serializable."""
        result = await mysql_executor.execute_query(
            "SELECT * FROM products LIMIT 5", limit=5
        )

        assert_json_serializable(result.model_dump())

    @pytest.mark.asyncio
    async def test_execute_query_with_join(self, mysql_executor: QueryExecutor):
        """Test executing a JOIN query."""
        result = await mysql_executor.execute_query(
            """
            SELECT p.name, c.name as category_name, p.price
            FROM products p
            JOIN categories c ON p.category_id = c.category_id
            """,
            limit=10,
        )

        assert result.row_count > 0
        assert "name" in result.columns
        assert "category_name" in result.columns
        assert "price" in result.columns


class TestMySQLExecutorSampling:
    """Test data sampling on MySQL."""

    @pytest.mark.asyncio
    async def test_sample_data(self, mysql_executor: QueryExecutor):
        """Test sample_data from products table."""
        result = await mysql_executor.sample_data("products", "testdb", limit=3)

        assert result.row_count >= 0
        assert result.row_count <= 3
        assert len(result.columns) > 0

    @pytest.mark.asyncio
    async def test_sample_data_users(self, mysql_executor: QueryExecutor):
        """Test sample_data from users table."""
        result = await mysql_executor.sample_data("users", "testdb", limit=5)

        assert result.row_count > 0
        assert "email" in result.columns
        assert "username" in result.columns


class TestMySQLExecutorReadOnly:
    """Test read-only enforcement on MySQL."""

    @pytest.mark.asyncio
    async def test_reject_drop_table(self, mysql_executor: QueryExecutor):
        """Test that DROP TABLE is rejected."""
        with pytest.raises(Exception):
            await mysql_executor.execute_query("DROP TABLE products", limit=10)

    @pytest.mark.asyncio
    async def test_reject_delete(self, mysql_executor: QueryExecutor):
        """Test that DELETE is rejected."""
        with pytest.raises(Exception):
            await mysql_executor.execute_query(
                "DELETE FROM products WHERE product_id = 1", limit=10
            )

    @pytest.mark.asyncio
    async def test_reject_update(self, mysql_executor: QueryExecutor):
        """Test that UPDATE is rejected."""
        with pytest.raises(Exception):
            await mysql_executor.execute_query(
                "UPDATE products SET price = 0", limit=10
            )

    @pytest.mark.asyncio
    async def test_reject_insert(self, mysql_executor: QueryExecutor):
        """Test that INSERT is rejected."""
        with pytest.raises(Exception):
            await mysql_executor.execute_query(
                "INSERT INTO products (name, price) VALUES ('test', 1.00)", limit=10
            )
