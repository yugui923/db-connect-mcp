"""Integration Tests for SSH Tunnel connectivity

Tests the SSH tunnel infrastructure end-to-end:
- Bastion host connectivity
- SSH tunnel establishment and teardown
- MySQL access through tunnel
- PostgreSQL access through tunnel
- Tunnel URL rewriting
- Connection lifecycle with tunnel
- MCP server with tunneled databases
"""

import os

import pytest
from sqlalchemy import text

from db_connect_mcp.core import DatabaseConnection
from db_connect_mcp.core.tunnel import SSHTunnelManager, rewrite_database_url
from db_connect_mcp.models.config import DatabaseConfig, SSHTunnelConfig

pytestmark = [pytest.mark.ssh_tunnel, pytest.mark.integration]


def _get_base_tunnel_config(remote_host: str, remote_port: int) -> SSHTunnelConfig:
    """Build tunnel config from env vars for a specific remote target."""
    ssh_host = os.getenv("SSH_HOST")
    ssh_username = os.getenv("SSH_USERNAME")
    if not ssh_host or not ssh_username:
        pytest.skip("SSH tunnel env vars not set (SSH_HOST, SSH_USERNAME)")
    return SSHTunnelConfig(
        ssh_host=ssh_host,
        ssh_port=int(os.getenv("SSH_PORT", "22")),
        ssh_username=ssh_username,
        ssh_password=os.getenv("SSH_PASSWORD"),
        remote_host=remote_host,
        remote_port=remote_port,
    )


# ==================== Raw Tunnel Tests ====================


class TestSSHTunnelConnectivity:
    """Test raw SSH tunnel establishment (database-agnostic)."""

    def test_tunnel_start_and_stop(self):
        """Test that SSH tunnel can be established and torn down."""
        config = _get_base_tunnel_config("mysql-tunneled", 3306)
        manager = SSHTunnelManager(config)

        port = manager.start()
        assert port > 0
        assert manager.is_active
        assert manager.local_bind_port == port

        manager.stop()
        assert not manager.is_active
        assert manager.local_bind_port is None

    def test_tunnel_context_manager(self):
        """Test SSH tunnel as context manager."""
        config = _get_base_tunnel_config("mysql-tunneled", 3306)

        with SSHTunnelManager(config) as manager:
            assert manager.is_active
            assert manager.local_bind_port is not None
            assert manager.local_bind_port > 0

        assert not manager.is_active

    def test_tunnel_ensure_active(self):
        """Test ensure_active on a running tunnel."""
        config = _get_base_tunnel_config("postgres-tunneled", 5432)

        with SSHTunnelManager(config) as manager:
            assert manager.ensure_active() is True

    def test_tunnel_url_rewriting_mysql(self):
        """Test URL rewriting with a real tunnel port for MySQL."""
        config = _get_base_tunnel_config("mysql-tunneled", 3306)

        with SSHTunnelManager(config) as manager:
            port = manager.local_bind_port
            rewritten = rewrite_database_url(
                "mysql+aiomysql://devuser:devpassword@mysql-tunneled:3306/devdb",
                "127.0.0.1",
                port,
            )
            assert f"127.0.0.1:{port}" in rewritten
            assert "devuser:devpassword" in rewritten
            assert "/devdb" in rewritten

    def test_tunnel_url_rewriting_pg(self):
        """Test URL rewriting with a real tunnel port for PostgreSQL."""
        config = _get_base_tunnel_config("postgres-tunneled", 5432)

        with SSHTunnelManager(config) as manager:
            port = manager.local_bind_port
            rewritten = rewrite_database_url(
                "postgresql+asyncpg://devuser:devpassword@postgres-tunneled:5432/devdb",
                "127.0.0.1",
                port,
            )
            assert f"127.0.0.1:{port}" in rewritten
            assert "devuser:devpassword" in rewritten
            assert "/devdb" in rewritten


# ==================== MySQL Through Tunnel ====================


class TestSSHTunnelMySQLAccess:
    """Test MySQL access through SSH tunnel."""

    @pytest.mark.asyncio
    async def test_connect_mysql_through_tunnel(self):
        """Test full connection to MySQL through SSH tunnel."""
        mysql_url = os.getenv("MYSQL_TUNNEL_DATABASE_URL")
        if not mysql_url:
            pytest.skip("MYSQL_TUNNEL_DATABASE_URL not set")

        config = DatabaseConfig(
            url=mysql_url,
            ssh_tunnel=_get_base_tunnel_config("mysql-tunneled", 3306),
        )

        connection = DatabaseConnection(config)
        try:
            await connection.initialize()
            assert connection.is_tunneled

            async with connection.get_connection() as conn:
                result = await conn.execute(text("SELECT 1"))
                assert result.scalar() == 1
        finally:
            await connection.dispose()

    @pytest.mark.asyncio
    async def test_query_mysql_data_through_tunnel(self):
        """Test querying actual data from MySQL through tunnel."""
        mysql_url = os.getenv("MYSQL_TUNNEL_DATABASE_URL")
        if not mysql_url:
            pytest.skip("MYSQL_TUNNEL_DATABASE_URL not set")

        config = DatabaseConfig(
            url=mysql_url,
            ssh_tunnel=_get_base_tunnel_config("mysql-tunneled", 3306),
        )

        connection = DatabaseConnection(config)
        try:
            await connection.initialize()
            async with connection.get_connection() as conn:
                result = await conn.execute(text("SELECT COUNT(*) FROM products"))
                assert result.scalar() == 5

                result = await conn.execute(text("SELECT COUNT(*) FROM categories"))
                assert result.scalar() == 3

                result = await conn.execute(text("SELECT COUNT(*) FROM users"))
                assert result.scalar() == 3
        finally:
            await connection.dispose()

    @pytest.mark.asyncio
    async def test_mysql_tunnel_cleanup(self):
        """Test that MySQL tunnel is properly cleaned up on dispose."""
        mysql_url = os.getenv("MYSQL_TUNNEL_DATABASE_URL")
        if not mysql_url:
            pytest.skip("MYSQL_TUNNEL_DATABASE_URL not set")

        config = DatabaseConfig(
            url=mysql_url,
            ssh_tunnel=_get_base_tunnel_config("mysql-tunneled", 3306),
        )

        connection = DatabaseConnection(config)
        await connection.initialize()
        assert connection.is_tunneled
        await connection.dispose()
        assert connection._tunnel_manager is None


# ==================== PostgreSQL Through Tunnel ====================


class TestSSHTunnelPostgresAccess:
    """Test PostgreSQL access through SSH tunnel."""

    @pytest.mark.asyncio
    async def test_connect_pg_through_tunnel(self):
        """Test full connection to PostgreSQL through SSH tunnel."""
        pg_url = os.getenv("PG_TUNNEL_DATABASE_URL")
        if not pg_url:
            pytest.skip("PG_TUNNEL_DATABASE_URL not set")

        config = DatabaseConfig(
            url=pg_url,
            ssh_tunnel=_get_base_tunnel_config("postgres-tunneled", 5432),
        )

        connection = DatabaseConnection(config)
        try:
            await connection.initialize()
            assert connection.is_tunneled

            async with connection.get_connection() as conn:
                result = await conn.execute(text("SELECT 1"))
                assert result.scalar() == 1
        finally:
            await connection.dispose()

    @pytest.mark.asyncio
    async def test_query_pg_data_through_tunnel(self):
        """Test querying actual data from PostgreSQL through tunnel."""
        pg_url = os.getenv("PG_TUNNEL_DATABASE_URL")
        if not pg_url:
            pytest.skip("PG_TUNNEL_DATABASE_URL not set")

        config = DatabaseConfig(
            url=pg_url,
            ssh_tunnel=_get_base_tunnel_config("postgres-tunneled", 5432),
        )

        connection = DatabaseConnection(config)
        try:
            await connection.initialize()
            async with connection.get_connection() as conn:
                result = await conn.execute(text("SELECT COUNT(*) FROM products"))
                count = result.scalar()
                assert count > 0  # PG has 2000+ products

                result = await conn.execute(text("SELECT COUNT(*) FROM users"))
                count = result.scalar()
                assert count > 0
        finally:
            await connection.dispose()

    @pytest.mark.asyncio
    async def test_pg_tunnel_cleanup(self):
        """Test that PG tunnel is properly cleaned up on dispose."""
        pg_url = os.getenv("PG_TUNNEL_DATABASE_URL")
        if not pg_url:
            pytest.skip("PG_TUNNEL_DATABASE_URL not set")

        config = DatabaseConfig(
            url=pg_url,
            ssh_tunnel=_get_base_tunnel_config("postgres-tunneled", 5432),
        )

        connection = DatabaseConnection(config)
        await connection.initialize()
        assert connection.is_tunneled
        await connection.dispose()
        assert connection._tunnel_manager is None


# ==================== MCP Server with Tunneled MySQL ====================


class TestSSHTunnelMySQLMCP:
    """Test MCP server with tunneled MySQL connection."""

    @pytest.mark.asyncio
    async def test_mcp_get_database_info(self, mysql_tunnel_mcp_server):
        result = await mysql_tunnel_mcp_server.handle_get_database_info({})
        assert len(result) > 0
        assert "mysql" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_mcp_list_schemas(self, mysql_tunnel_mcp_server):
        result = await mysql_tunnel_mcp_server.handle_list_schemas({})
        assert len(result) > 0
        assert "devdb" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_list_tables(self, mysql_tunnel_mcp_server):
        result = await mysql_tunnel_mcp_server.handle_list_tables({"schema": "devdb"})
        assert len(result) > 0
        text = result[0].text
        assert "products" in text
        assert "categories" in text

    @pytest.mark.asyncio
    async def test_mcp_execute_query(self, mysql_tunnel_mcp_server):
        result = await mysql_tunnel_mcp_server.handle_execute_query(
            {
                "query": "SELECT name, price FROM products ORDER BY price DESC LIMIT 3",
            }
        )
        assert len(result) > 0
        assert "name" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_sample_data(self, mysql_tunnel_mcp_server):
        result = await mysql_tunnel_mcp_server.handle_sample_data(
            {
                "table": "products",
                "schema": "devdb",
                "limit": 3,
            }
        )
        assert len(result) > 0
        assert "product_id" in result[0].text


# ==================== MCP Server with Tunneled PostgreSQL ====================


class TestSSHTunnelPostgresMCP:
    """Test MCP server with tunneled PostgreSQL connection."""

    @pytest.mark.asyncio
    async def test_mcp_get_database_info(self, pg_tunnel_mcp_server):
        result = await pg_tunnel_mcp_server.handle_get_database_info({})
        assert len(result) > 0
        assert "postgresql" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_mcp_list_schemas(self, pg_tunnel_mcp_server):
        result = await pg_tunnel_mcp_server.handle_list_schemas({})
        assert len(result) > 0
        assert "public" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_list_tables(self, pg_tunnel_mcp_server):
        result = await pg_tunnel_mcp_server.handle_list_tables({"schema": "public"})
        assert len(result) > 0
        text = result[0].text
        assert "products" in text
        assert "users" in text

    @pytest.mark.asyncio
    async def test_mcp_execute_query(self, pg_tunnel_mcp_server):
        result = await pg_tunnel_mcp_server.handle_execute_query(
            {
                "query": "SELECT name, price FROM products ORDER BY price DESC LIMIT 3",
            }
        )
        assert len(result) > 0
        assert "name" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_sample_data(self, pg_tunnel_mcp_server):
        result = await pg_tunnel_mcp_server.handle_sample_data(
            {
                "table": "products",
                "schema": "public",
                "limit": 3,
            }
        )
        assert len(result) > 0
        assert "product_id" in result[0].text
