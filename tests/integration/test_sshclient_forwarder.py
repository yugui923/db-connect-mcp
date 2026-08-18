"""Reliability tests for database traffic through the native SSH forwarder."""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text

from db_connect_mcp.core.connection import DatabaseConnection
from db_connect_mcp.models.config import DatabaseConfig, SSHTunnelConfig

pytestmark = [pytest.mark.ssh_tunnel, pytest.mark.integration]


def _case(database_env: str, remote_host: str, remote_port: int) -> DatabaseConfig:
    database_url = os.getenv(database_env)
    ssh_host = os.getenv("SSH_HOST")
    ssh_username = os.getenv("SSH_USERNAME")
    if not database_url or not ssh_host or not ssh_username:
        pytest.skip(f"SSH reliability environment is incomplete for {database_env}")
    return DatabaseConfig(
        url=database_url,
        ssh_tunnel=SSHTunnelConfig(
            ssh_host=ssh_host,
            ssh_port=int(os.getenv("SSH_PORT", "22")),
            ssh_username=ssh_username,
            ssh_password=os.getenv("SSH_PASSWORD"),
            ssh_private_key=os.getenv("SSH_PRIVATE_KEY"),
            remote_host=remote_host,
            remote_port=remote_port,
        ),
    )


@pytest.fixture(
    params=[
        ("PG_TUNNEL_DATABASE_URL", "postgres-tunneled", 5432),
        ("MYSQL_TUNNEL_DATABASE_URL", "mysql-tunneled", 3306),
    ],
    ids=["postgresql", "mysql"],
)
def tunnel_database_config(request: pytest.FixtureRequest) -> DatabaseConfig:
    """Build a tunnel configuration for each supported asynchronous database."""
    database_env, remote_host, remote_port = request.param
    return _case(database_env, remote_host, remote_port)


@pytest.mark.asyncio
async def test_twenty_queries_share_one_tunnel(
    tunnel_database_config: DatabaseConfig,
) -> None:
    """A persistent tunnel should carry repeated database operations reliably."""
    connection = DatabaseConnection(tunnel_database_config)
    try:
        await connection.initialize()
        for _ in range(20):
            async with connection.get_connection() as database_connection:
                result = await database_connection.execute(text("SELECT 1"))
                assert result.scalar() == 1
    finally:
        await connection.dispose()


@pytest.mark.asyncio
async def test_ten_fresh_tunnel_lifecycles(
    tunnel_database_config: DatabaseConfig,
) -> None:
    """Repeated startup and bounded teardown should not leak listeners or threads."""
    ports: list[int] = []
    for _ in range(10):
        connection = DatabaseConnection(tunnel_database_config)
        forwarder = None
        listener_thread = None
        try:
            await connection.initialize()
            manager = connection._tunnel_manager
            assert manager is not None
            assert manager.local_bind_port is not None
            ports.append(manager.local_bind_port)
            forwarder = manager._tunnel
            assert forwarder is not None
            listener_thread = forwarder._server_thread
            assert listener_thread is not None
            assert listener_thread.is_alive()
            async with connection.get_connection() as database_connection:
                result = await database_connection.execute(text("SELECT 1"))
                assert result.scalar() == 1
        finally:
            await connection.dispose()
        assert connection._tunnel_manager is None
        assert forwarder is not None
        assert listener_thread is not None
        assert not listener_thread.is_alive()
        assert not forwarder._sessions
        assert forwarder._current_generation is None
    assert len(ports) == 10


@pytest.mark.asyncio
async def test_five_concurrent_queries_share_one_tunnel(
    tunnel_database_config: DatabaseConfig,
) -> None:
    """Concurrent database connections should receive independent SSH channels."""
    connection = DatabaseConnection(tunnel_database_config)

    async def query_once() -> int:
        async with connection.get_connection() as database_connection:
            result = await database_connection.execute(text("SELECT 1"))
            return int(result.scalar())

    try:
        await connection.initialize()
        assert await asyncio.gather(*(query_once() for _ in range(5))) == [1] * 5
    finally:
        await connection.dispose()


@pytest.mark.asyncio
async def test_transport_recovery_preserves_database_engine_endpoint(
    tunnel_database_config: DatabaseConfig,
) -> None:
    """Replacing a failed SSH transport must not change the listener port."""
    connection = DatabaseConnection(tunnel_database_config)
    try:
        await connection.initialize()
        manager = connection._tunnel_manager
        assert manager is not None
        original_port = manager.local_bind_port
        assert original_port is not None
        forwarder = manager._tunnel
        assert forwarder is not None
        generation = forwarder._current_generation
        assert generation is not None
        generation.transport.close()

        assert await asyncio.to_thread(manager.ensure_active)
        assert manager.local_bind_port == original_port

        # Discard pooled channels tied to the closed generation. The engine keeps
        # its original URL and opens its next connection through the stable port.
        assert connection.engine is not None
        await connection.engine.dispose()
        async with connection.get_connection() as database_connection:
            result = await database_connection.execute(text("SELECT 1"))
            assert result.scalar() == 1
    finally:
        await connection.dispose()
