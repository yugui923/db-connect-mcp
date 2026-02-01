"""Integration Tests for SSH Tunnel connectivity

Tests the SSH tunnel infrastructure end-to-end:
- Bastion host connectivity
- SSH tunnel establishment and teardown
- MySQL access through tunnel
- Tunnel URL rewriting
- Connection lifecycle with tunnel
- MCP server with tunneled MySQL
"""

import os

import pytest
from sqlalchemy import text

from db_connect_mcp.adapters import create_adapter
from db_connect_mcp.core import DatabaseConnection, MetadataInspector
from db_connect_mcp.core.tunnel import SSHTunnelManager, rewrite_database_url
from db_connect_mcp.models.config import DatabaseConfig, SSHTunnelConfig

pytestmark = [pytest.mark.ssh_tunnel, pytest.mark.integration]


def _get_tunnel_config() -> SSHTunnelConfig:
    """Build tunnel config from env vars, skip if not available."""
    ssh_host = os.getenv("SSH_HOST")
    ssh_username = os.getenv("SSH_USERNAME")
    if not ssh_host or not ssh_username:
        pytest.skip("SSH tunnel env vars not set (SSH_HOST, SSH_USERNAME)")
    return SSHTunnelConfig(
        ssh_host=ssh_host,
        ssh_port=int(os.getenv("SSH_PORT", "22")),
        ssh_username=ssh_username,
        ssh_password=os.getenv("SSH_PASSWORD"),
        remote_host=os.getenv("SSH_REMOTE_HOST", "127.0.0.1"),
        remote_port=int(os.getenv("SSH_REMOTE_PORT", "3306")),
    )


class TestSSHTunnelConnectivity:
    """Test raw SSH tunnel establishment."""

    def test_tunnel_start_and_stop(self):
        """Test that SSH tunnel can be established and torn down."""
        config = _get_tunnel_config()
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
        config = _get_tunnel_config()

        with SSHTunnelManager(config) as manager:
            assert manager.is_active
            assert manager.local_bind_port is not None
            assert manager.local_bind_port > 0

        # After exiting context, tunnel should be stopped
        assert not manager.is_active

    def test_tunnel_ensure_active(self):
        """Test ensure_active on a running tunnel."""
        config = _get_tunnel_config()

        with SSHTunnelManager(config) as manager:
            assert manager.ensure_active() is True

    def test_tunnel_url_rewriting(self):
        """Test that URL rewriting works with a real tunnel port."""
        config = _get_tunnel_config()

        with SSHTunnelManager(config) as manager:
            port = manager.local_bind_port
            rewritten = rewrite_database_url(
                "mysql+aiomysql://testuser:testpass@mysql:3306/testdb",
                "127.0.0.1",
                port,
            )
            assert f"127.0.0.1:{port}" in rewritten
            assert "testuser:testpass" in rewritten
            assert "/testdb" in rewritten


class TestSSHTunnelDatabaseAccess:
    """Test MySQL access through SSH tunnel."""

    @pytest.mark.asyncio
    async def test_connect_mysql_through_tunnel(self):
        """Test full connection to MySQL through SSH tunnel."""
        mysql_url = os.getenv("MYSQL_TEST_DATABASE_URL")
        if not mysql_url:
            pytest.skip("MYSQL_TEST_DATABASE_URL not set")

        config = DatabaseConfig(
            url=mysql_url,
            ssh_tunnel=_get_tunnel_config(),
        )

        connection = DatabaseConnection(config)
        try:
            await connection.initialize()
            assert connection.is_tunneled

            async with connection.get_connection() as conn:
                result = await conn.execute(text("SELECT 1"))
                row = result.scalar()
                assert row == 1
        finally:
            await connection.dispose()

    @pytest.mark.asyncio
    async def test_query_mysql_data_through_tunnel(self):
        """Test querying actual data through tunnel."""
        mysql_url = os.getenv("MYSQL_TEST_DATABASE_URL")
        if not mysql_url:
            pytest.skip("MYSQL_TEST_DATABASE_URL not set")

        config = DatabaseConfig(
            url=mysql_url,
            ssh_tunnel=_get_tunnel_config(),
        )

        connection = DatabaseConnection(config)
        try:
            await connection.initialize()

            async with connection.get_connection() as conn:
                result = await conn.execute(text("SELECT COUNT(*) FROM products"))
                count = result.scalar()
                assert count == 5  # 5 products in seed data

                result = await conn.execute(text("SELECT COUNT(*) FROM categories"))
                count = result.scalar()
                assert count == 3  # 3 categories in seed data

                result = await conn.execute(text("SELECT COUNT(*) FROM users"))
                count = result.scalar()
                assert count == 3  # 3 users in seed data
        finally:
            await connection.dispose()

    @pytest.mark.asyncio
    async def test_tunnel_connection_cleanup(self):
        """Test that tunnel is properly cleaned up on dispose."""
        mysql_url = os.getenv("MYSQL_TEST_DATABASE_URL")
        if not mysql_url:
            pytest.skip("MYSQL_TEST_DATABASE_URL not set")

        config = DatabaseConfig(
            url=mysql_url,
            ssh_tunnel=_get_tunnel_config(),
        )

        connection = DatabaseConnection(config)
        await connection.initialize()
        assert connection.is_tunneled

        await connection.dispose()
        # After dispose, tunnel manager should be cleaned up
        assert connection._tunnel_manager is None


class TestSSHTunnelMCPIntegration:
    """Test MCP server with tunneled MySQL connection."""

    @pytest.mark.asyncio
    async def test_mcp_server_with_tunnel(self, mysql_mcp_server):
        """Test MCP server initializes with tunneled MySQL."""
        server = mysql_mcp_server
        result = await server.handle_get_database_info({})
        assert len(result) > 0
        assert "mysql" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_mcp_list_schemas_with_tunnel(self, mysql_mcp_server):
        """Test listing schemas through tunneled MCP server."""
        server = mysql_mcp_server
        result = await server.handle_list_schemas({})
        assert len(result) > 0
        assert "testdb" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_list_tables_with_tunnel(self, mysql_mcp_server):
        """Test listing tables through tunneled MCP server."""
        server = mysql_mcp_server
        result = await server.handle_list_tables({"schema": "testdb"})
        assert len(result) > 0
        text = result[0].text
        assert "products" in text
        assert "categories" in text
        assert "users" in text

    @pytest.mark.asyncio
    async def test_mcp_execute_query_with_tunnel(self, mysql_mcp_server):
        """Test executing a query through tunneled MCP server."""
        server = mysql_mcp_server
        result = await server.handle_execute_query({
            "query": "SELECT name, price FROM products ORDER BY price DESC LIMIT 3",
        })
        assert len(result) > 0
        text = result[0].text
        assert "name" in text
        assert "price" in text

    @pytest.mark.asyncio
    async def test_mcp_sample_data_with_tunnel(self, mysql_mcp_server):
        """Test sampling data through tunneled MCP server."""
        server = mysql_mcp_server
        result = await server.handle_sample_data({
            "table": "products",
            "schema": "testdb",
            "limit": 3,
        })
        assert len(result) > 0
        assert "product_id" in result[0].text
