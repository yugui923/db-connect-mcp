"""Module Tests for MySQL QueryExecutor

Tests both direct and tunneled MySQL access for the QueryExecutor component.
"""

import pytest

from db_connect_mcp.core import QueryExecutor
from tests.conftest import assert_json_serializable


# ==================== MySQL Direct ====================


class TestMySQLDirectExecutorBasic:
    """Test basic query execution on MySQL direct."""

    pytestmark = [pytest.mark.mysql]

    @pytest.mark.asyncio
    async def test_execute_simple_query(self, mysql_executor: QueryExecutor):
        result = await mysql_executor.execute_query("SELECT 1 as test_col", limit=10)
        assert result.row_count == 1
        assert result.columns[0] == "test_col"
        assert result.rows[0]["test_col"] == 1

    @pytest.mark.asyncio
    async def test_execute_query_with_limit(self, mysql_executor: QueryExecutor):
        result = await mysql_executor.execute_query("SELECT * FROM products", limit=2)
        assert result.row_count <= 2

    @pytest.mark.asyncio
    async def test_query_result_serializable(self, mysql_executor: QueryExecutor):
        result = await mysql_executor.execute_query(
            "SELECT * FROM products LIMIT 5", limit=5
        )
        assert_json_serializable(result.model_dump())

    @pytest.mark.asyncio
    async def test_execute_query_with_join(self, mysql_executor: QueryExecutor):
        result = await mysql_executor.execute_query(
            """
            SELECT p.name, c.name as category_name, p.price
            FROM products p
            JOIN categories c ON p.category_id = c.category_id
            """,
            limit=10,
        )
        assert result.row_count > 0
        assert "category_name" in result.columns


class TestMySQLDirectExecutorSampling:
    """Test data sampling on MySQL direct."""

    pytestmark = [pytest.mark.mysql]

    @pytest.mark.asyncio
    async def test_sample_data(self, mysql_executor: QueryExecutor):
        result = await mysql_executor.sample_data("products", "devdb", limit=3)
        assert result.row_count > 0
        assert result.row_count <= 3

    @pytest.mark.asyncio
    async def test_sample_data_users(self, mysql_executor: QueryExecutor):
        result = await mysql_executor.sample_data("users", "devdb", limit=5)
        assert result.row_count > 0
        assert "email" in result.columns


class TestMySQLDirectExecutorReadOnly:
    """Test read-only enforcement on MySQL direct."""

    pytestmark = [pytest.mark.mysql]

    @pytest.mark.asyncio
    async def test_reject_drop(self, mysql_executor: QueryExecutor):
        with pytest.raises(ValueError):
            await mysql_executor.execute_query("DROP TABLE products", limit=10)

    @pytest.mark.asyncio
    async def test_reject_delete(self, mysql_executor: QueryExecutor):
        with pytest.raises(ValueError):
            await mysql_executor.execute_query(
                "DELETE FROM products WHERE product_id = 1", limit=10
            )

    @pytest.mark.asyncio
    async def test_reject_update(self, mysql_executor: QueryExecutor):
        with pytest.raises(ValueError):
            await mysql_executor.execute_query(
                "UPDATE products SET price = 0", limit=10
            )

    @pytest.mark.asyncio
    async def test_reject_insert(self, mysql_executor: QueryExecutor):
        with pytest.raises(ValueError):
            await mysql_executor.execute_query(
                "INSERT INTO products (name, price) VALUES ('test', 1.00)", limit=10
            )


# ==================== MySQL Tunneled ====================


class TestMySQLTunneledExecutorBasic:
    """Test basic query execution on MySQL via SSH tunnel."""

    pytestmark = [pytest.mark.mysql, pytest.mark.ssh_tunnel]

    @pytest.mark.asyncio
    async def test_execute_simple_query(self, mysql_tunnel_executor: QueryExecutor):
        result = await mysql_tunnel_executor.execute_query(
            "SELECT 1 as test_col", limit=10
        )
        assert result.row_count == 1
        assert result.rows[0]["test_col"] == 1

    @pytest.mark.asyncio
    async def test_execute_query_with_limit(self, mysql_tunnel_executor: QueryExecutor):
        result = await mysql_tunnel_executor.execute_query(
            "SELECT * FROM products", limit=2
        )
        assert result.row_count <= 2

    @pytest.mark.asyncio
    async def test_query_result_serializable(
        self, mysql_tunnel_executor: QueryExecutor
    ):
        result = await mysql_tunnel_executor.execute_query(
            "SELECT * FROM products LIMIT 5", limit=5
        )
        assert_json_serializable(result.model_dump())

    @pytest.mark.asyncio
    async def test_execute_query_with_join(self, mysql_tunnel_executor: QueryExecutor):
        result = await mysql_tunnel_executor.execute_query(
            """
            SELECT p.name, c.name as category_name, p.price
            FROM products p
            JOIN categories c ON p.category_id = c.category_id
            """,
            limit=10,
        )
        assert result.row_count > 0


class TestMySQLTunneledExecutorReadOnly:
    """Test read-only enforcement on MySQL via SSH tunnel."""

    pytestmark = [pytest.mark.mysql, pytest.mark.ssh_tunnel]

    @pytest.mark.asyncio
    async def test_reject_drop(self, mysql_tunnel_executor: QueryExecutor):
        with pytest.raises(ValueError):
            await mysql_tunnel_executor.execute_query("DROP TABLE products", limit=10)

    @pytest.mark.asyncio
    async def test_reject_insert(self, mysql_tunnel_executor: QueryExecutor):
        with pytest.raises(ValueError):
            await mysql_tunnel_executor.execute_query(
                "INSERT INTO products (name, price) VALUES ('test', 1.00)", limit=10
            )
