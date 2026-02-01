"""Pytest configuration and shared fixtures for database tests.

This conftest.py is at the root of the tests/ directory and provides
fixtures for all test subdirectories (integration/, module/, unit/).

Fixture naming convention:
  pg_*          = PostgreSQL direct (localhost:5432)
  mysql_*       = MySQL direct (localhost:3306)
  pg_tunnel_*   = PostgreSQL via SSH tunnel (bastion -> postgres-tunneled)
  mysql_tunnel_* = MySQL via SSH tunnel (bastion -> mysql-tunneled)
"""

import os
import sys
from typing import AsyncGenerator, Optional

import pytest
from dotenv import load_dotenv
from sqlalchemy import text

from db_connect_mcp.adapters import create_adapter
from db_connect_mcp.adapters.base import BaseAdapter
from db_connect_mcp.core import (
    DatabaseConnection,
    MetadataInspector,
    QueryExecutor,
    StatisticsAnalyzer,
)
from db_connect_mcp.models.config import DatabaseConfig, SSHTunnelConfig

# Load environment variables
load_dotenv()

# Fix for Windows: asyncpg requires SelectorEventLoop on Windows
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]


# ==================== SSH Tunnel Helper ====================


def _build_ssh_tunnel_config(
    remote_host: str, remote_port: int
) -> Optional[SSHTunnelConfig]:
    """Build SSH tunnel config from env vars for a specific remote target."""
    ssh_host = os.getenv("SSH_HOST")
    ssh_username = os.getenv("SSH_USERNAME")
    if not ssh_host or not ssh_username:
        return None
    return SSHTunnelConfig(
        ssh_host=ssh_host,
        ssh_port=int(os.getenv("SSH_PORT", "22")),
        ssh_username=ssh_username,
        ssh_password=os.getenv("SSH_PASSWORD"),
        ssh_private_key=os.getenv("SSH_PRIVATE_KEY"),
        remote_host=remote_host,
        remote_port=remote_port,
    )


# ==================== URL Fixtures ====================


@pytest.fixture(scope="session")
def pg_database_url() -> str:
    """PostgreSQL direct-access test database URL."""
    return os.getenv(
        "PG_TEST_DATABASE_URL",
        "postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb",
    )


@pytest.fixture(scope="session")
def mysql_database_url() -> Optional[str]:
    """MySQL direct-access test database URL."""
    return os.getenv("MYSQL_TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def pg_tunnel_database_url() -> Optional[str]:
    """PostgreSQL tunnel database URL (target as seen from bastion)."""
    return os.getenv("PG_TUNNEL_DATABASE_URL")


@pytest.fixture(scope="session")
def mysql_tunnel_database_url() -> Optional[str]:
    """MySQL tunnel database URL (target as seen from bastion)."""
    return os.getenv("MYSQL_TUNNEL_DATABASE_URL")


@pytest.fixture(scope="session")
def ch_database_url() -> Optional[str]:
    """ClickHouse test database URL from environment."""
    return os.getenv("CH_TEST_DATABASE_URL")


# ==================== Tunnel Config Fixtures ====================


@pytest.fixture(scope="session")
def pg_tunnel_ssh_config() -> Optional[SSHTunnelConfig]:
    """SSH tunnel config targeting the tunneled PostgreSQL container."""
    return _build_ssh_tunnel_config("postgres-tunneled", 5432)


@pytest.fixture(scope="session")
def mysql_tunnel_ssh_config() -> Optional[SSHTunnelConfig]:
    """SSH tunnel config targeting the tunneled MySQL container."""
    return _build_ssh_tunnel_config("mysql-tunneled", 3306)


# ==================== PostgreSQL Direct Fixtures ====================


@pytest.fixture
async def pg_config(pg_database_url: str) -> DatabaseConfig:
    """PostgreSQL direct database configuration."""
    return DatabaseConfig(url=pg_database_url)


@pytest.fixture
async def pg_adapter(pg_config: DatabaseConfig) -> BaseAdapter:
    """PostgreSQL direct adapter instance."""
    return create_adapter(pg_config)


@pytest.fixture
async def pg_connection(
    pg_config: DatabaseConfig,
) -> AsyncGenerator[DatabaseConnection, None]:
    """PostgreSQL direct database connection with proper cleanup."""
    connection = DatabaseConnection(pg_config)
    try:
        await connection.initialize()
        async with connection.get_connection() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        await connection.dispose()
        pytest.skip(f"PostgreSQL direct connection failed: {e}")
    try:
        yield connection
    finally:
        await connection.dispose()


@pytest.fixture
async def pg_inspector(
    pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
) -> MetadataInspector:
    """PostgreSQL direct metadata inspector."""
    return MetadataInspector(pg_connection, pg_adapter)


@pytest.fixture
async def pg_analyzer(
    pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
) -> StatisticsAnalyzer:
    """PostgreSQL direct statistics analyzer."""
    return StatisticsAnalyzer(pg_connection, pg_adapter)


@pytest.fixture
async def pg_executor(
    pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
) -> QueryExecutor:
    """PostgreSQL direct query executor."""
    return QueryExecutor(pg_connection, pg_adapter)


@pytest.fixture
def known_tables():
    """Known tables from local PG test database with their guaranteed columns.

    Use this instead of searching for tables - these are guaranteed to exist
    in the local Docker test database.
    """
    return {
        "categories": {
            "columns": {
                "numeric": ["category_id", "parent_category_id"],
                "text": ["name", "description", "slug"],
                "json": ["metadata"],
            },
            "has_fk": True,  # Self-referencing FK to parent_category_id
            "has_index": True,
            "row_count_min": 50,
        },
        "products": {
            "columns": {
                "numeric": [
                    "product_id",
                    "category_id",
                    "price",
                    "cost",
                    "stock_quantity",
                    "weight_kg",
                ],
                "text": ["name", "description", "sku"],
                "uuid": ["product_uuid"],
                "json": ["specifications"],
                "array": ["tags"],
                "inet": ["last_ip_address"],
            },
            "has_fk": True,  # FK to categories
            "has_index": True,
            "row_count_min": 2000,
        },
        "users": {
            "columns": {
                "numeric": ["user_id"],
                "text": [
                    "username",
                    "email",
                    "first_name",
                    "last_name",
                    "city",
                    "country",
                ],
                "inet": ["ip_address"],
                "timestamp": ["created_at", "last_login_at"],
                "json": ["preferences"],
            },
            "has_fk": False,
            "has_index": True,
            "row_count_min": 5000,
        },
        "orders": {
            "columns": {
                "numeric": [
                    "order_id",
                    "user_id",
                    "subtotal",
                    "tax",
                    "shipping_cost",
                    "total",
                ],
                "text": ["status", "shipping_address", "billing_address"],
                "timestamp": ["order_date"],
            },
            "has_fk": True,  # FK to users
            "has_index": True,
            "row_count_min": 10000,
        },
        "data_type_examples": {
            "columns": {
                "all_types": True,  # Has all PostgreSQL data types
                "numeric": [
                    "smallint_col",
                    "integer_col",
                    "bigint_col",
                    "decimal_col",
                    "numeric_col",
                ],
                "text": ["varchar_col", "text_col", "char_col"],
                "timestamp": [
                    "timestamp_col",
                    "timestamptz_col",
                    "date_col",
                    "time_col",
                ],
                "boolean": ["boolean_col"],
                "uuid": ["uuid_col"],
                "json": ["json_col", "jsonb_col"],
                "inet": ["inet_col", "cidr_col", "macaddr_col"],
                "array": ["integer_array", "text_array"],
                "bytea": ["bytea_col"],
            },
            "has_fk": False,
            "has_index": False,
            "row_count_min": 100,
        },
    }


@pytest.fixture
async def pg_mcp_server(
    pg_config: DatabaseConfig,
) -> AsyncGenerator:
    """PostgreSQL direct MCP server for protocol-level testing."""
    from db_connect_mcp.server import DatabaseMCPServer

    server = DatabaseMCPServer(pg_config)
    try:
        await server.initialize()
    except Exception as e:
        pytest.skip(f"MCP server initialization failed: {e}")

    try:
        yield server
    finally:
        await server.cleanup()


# ==================== MySQL Direct Fixtures ====================


@pytest.fixture
async def mysql_config(mysql_database_url: Optional[str]) -> DatabaseConfig:
    """MySQL direct database configuration (no tunnel)."""
    if not mysql_database_url:
        pytest.skip("MYSQL_TEST_DATABASE_URL not set in environment")
    return DatabaseConfig(url=mysql_database_url)


@pytest.fixture
async def mysql_adapter(mysql_config: DatabaseConfig) -> BaseAdapter:
    """MySQL direct adapter instance."""
    return create_adapter(mysql_config)


@pytest.fixture
async def mysql_connection(
    mysql_config: DatabaseConfig,
) -> AsyncGenerator[DatabaseConnection, None]:
    """MySQL direct database connection with proper cleanup."""
    connection = DatabaseConnection(mysql_config)
    try:
        await connection.initialize()
        async with connection.get_connection() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        await connection.dispose()
        pytest.skip(f"MySQL direct connection failed: {e}")
    try:
        yield connection
    finally:
        await connection.dispose()


@pytest.fixture
async def mysql_inspector(
    mysql_connection: DatabaseConnection, mysql_adapter: BaseAdapter
) -> MetadataInspector:
    """MySQL direct metadata inspector."""
    return MetadataInspector(mysql_connection, mysql_adapter)


@pytest.fixture
async def mysql_executor(
    mysql_connection: DatabaseConnection, mysql_adapter: BaseAdapter
) -> QueryExecutor:
    """MySQL direct query executor."""
    return QueryExecutor(mysql_connection, mysql_adapter)


@pytest.fixture
async def mysql_analyzer(
    mysql_connection: DatabaseConnection, mysql_adapter: BaseAdapter
) -> StatisticsAnalyzer:
    """MySQL direct statistics analyzer."""
    return StatisticsAnalyzer(mysql_connection, mysql_adapter)


@pytest.fixture
async def mysql_mcp_server(
    mysql_config: DatabaseConfig,
) -> AsyncGenerator:
    """MySQL direct MCP server for protocol-level testing."""
    from db_connect_mcp.server import DatabaseMCPServer

    server = DatabaseMCPServer(mysql_config)
    try:
        await server.initialize()
    except Exception as e:
        pytest.skip(f"MySQL direct MCP server initialization failed: {e}")

    try:
        yield server
    finally:
        await server.cleanup()


# ==================== PostgreSQL Tunneled Fixtures ====================


@pytest.fixture
async def pg_tunnel_config(
    pg_tunnel_database_url: Optional[str],
    pg_tunnel_ssh_config: Optional[SSHTunnelConfig],
) -> DatabaseConfig:
    """PostgreSQL tunneled database configuration."""
    if not pg_tunnel_database_url:
        pytest.skip("PG_TUNNEL_DATABASE_URL not set in environment")
    if not pg_tunnel_ssh_config:
        pytest.skip("SSH tunnel env vars not set (SSH_HOST, SSH_USERNAME)")
    return DatabaseConfig(url=pg_tunnel_database_url, ssh_tunnel=pg_tunnel_ssh_config)


@pytest.fixture
async def pg_tunnel_adapter(pg_tunnel_config: DatabaseConfig) -> BaseAdapter:
    """PostgreSQL tunneled adapter instance."""
    return create_adapter(pg_tunnel_config)


@pytest.fixture
async def pg_tunnel_connection(
    pg_tunnel_config: DatabaseConfig,
) -> AsyncGenerator[DatabaseConnection, None]:
    """PostgreSQL tunneled database connection with proper cleanup."""
    connection = DatabaseConnection(pg_tunnel_config)
    try:
        await connection.initialize()
        async with connection.get_connection() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        await connection.dispose()
        pytest.skip(f"PostgreSQL tunneled connection failed: {e}")
    try:
        yield connection
    finally:
        await connection.dispose()


@pytest.fixture
async def pg_tunnel_inspector(
    pg_tunnel_connection: DatabaseConnection, pg_tunnel_adapter: BaseAdapter
) -> MetadataInspector:
    """PostgreSQL tunneled metadata inspector."""
    return MetadataInspector(pg_tunnel_connection, pg_tunnel_adapter)


@pytest.fixture
async def pg_tunnel_executor(
    pg_tunnel_connection: DatabaseConnection, pg_tunnel_adapter: BaseAdapter
) -> QueryExecutor:
    """PostgreSQL tunneled query executor."""
    return QueryExecutor(pg_tunnel_connection, pg_tunnel_adapter)


@pytest.fixture
async def pg_tunnel_analyzer(
    pg_tunnel_connection: DatabaseConnection, pg_tunnel_adapter: BaseAdapter
) -> StatisticsAnalyzer:
    """PostgreSQL tunneled statistics analyzer."""
    return StatisticsAnalyzer(pg_tunnel_connection, pg_tunnel_adapter)


@pytest.fixture
async def pg_tunnel_mcp_server(
    pg_tunnel_config: DatabaseConfig,
) -> AsyncGenerator:
    """PostgreSQL tunneled MCP server for protocol-level testing."""
    from db_connect_mcp.server import DatabaseMCPServer

    server = DatabaseMCPServer(pg_tunnel_config)
    try:
        await server.initialize()
    except Exception as e:
        pytest.skip(f"PostgreSQL tunneled MCP server initialization failed: {e}")

    try:
        yield server
    finally:
        await server.cleanup()


# ==================== MySQL Tunneled Fixtures ====================


@pytest.fixture
async def mysql_tunnel_config(
    mysql_tunnel_database_url: Optional[str],
    mysql_tunnel_ssh_config: Optional[SSHTunnelConfig],
) -> DatabaseConfig:
    """MySQL tunneled database configuration."""
    if not mysql_tunnel_database_url:
        pytest.skip("MYSQL_TUNNEL_DATABASE_URL not set in environment")
    if not mysql_tunnel_ssh_config:
        pytest.skip("SSH tunnel env vars not set (SSH_HOST, SSH_USERNAME)")
    return DatabaseConfig(
        url=mysql_tunnel_database_url, ssh_tunnel=mysql_tunnel_ssh_config
    )


@pytest.fixture
async def mysql_tunnel_adapter(mysql_tunnel_config: DatabaseConfig) -> BaseAdapter:
    """MySQL tunneled adapter instance."""
    return create_adapter(mysql_tunnel_config)


@pytest.fixture
async def mysql_tunnel_connection(
    mysql_tunnel_config: DatabaseConfig,
) -> AsyncGenerator[DatabaseConnection, None]:
    """MySQL tunneled database connection with proper cleanup."""
    connection = DatabaseConnection(mysql_tunnel_config)
    try:
        await connection.initialize()
        async with connection.get_connection() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        await connection.dispose()
        pytest.skip(f"MySQL tunneled connection failed: {e}")
    try:
        yield connection
    finally:
        await connection.dispose()


@pytest.fixture
async def mysql_tunnel_inspector(
    mysql_tunnel_connection: DatabaseConnection, mysql_tunnel_adapter: BaseAdapter
) -> MetadataInspector:
    """MySQL tunneled metadata inspector."""
    return MetadataInspector(mysql_tunnel_connection, mysql_tunnel_adapter)


@pytest.fixture
async def mysql_tunnel_executor(
    mysql_tunnel_connection: DatabaseConnection, mysql_tunnel_adapter: BaseAdapter
) -> QueryExecutor:
    """MySQL tunneled query executor."""
    return QueryExecutor(mysql_tunnel_connection, mysql_tunnel_adapter)


@pytest.fixture
async def mysql_tunnel_analyzer(
    mysql_tunnel_connection: DatabaseConnection, mysql_tunnel_adapter: BaseAdapter
) -> StatisticsAnalyzer:
    """MySQL tunneled statistics analyzer."""
    return StatisticsAnalyzer(mysql_tunnel_connection, mysql_tunnel_adapter)


@pytest.fixture
async def mysql_tunnel_mcp_server(
    mysql_tunnel_config: DatabaseConfig,
) -> AsyncGenerator:
    """MySQL tunneled MCP server for protocol-level testing."""
    from db_connect_mcp.server import DatabaseMCPServer

    server = DatabaseMCPServer(mysql_tunnel_config)
    try:
        await server.initialize()
    except Exception as e:
        pytest.skip(f"MySQL tunneled MCP server initialization failed: {e}")

    try:
        yield server
    finally:
        await server.cleanup()


# ==================== ClickHouse Fixtures ====================


@pytest.fixture
async def ch_config(ch_database_url: Optional[str]) -> DatabaseConfig:
    """ClickHouse database configuration."""
    if not ch_database_url:
        pytest.skip("CH_TEST_DATABASE_URL not set in environment")
    return DatabaseConfig(url=ch_database_url)


@pytest.fixture
async def ch_adapter(ch_config: DatabaseConfig) -> BaseAdapter:
    """ClickHouse adapter instance."""
    return create_adapter(ch_config)


@pytest.fixture
async def ch_connection(
    ch_config: DatabaseConfig,
) -> AsyncGenerator[DatabaseConnection, None]:
    """ClickHouse database connection with proper cleanup."""
    connection = DatabaseConnection(ch_config)
    try:
        await connection.initialize()
        if connection.sync_engine:
            with connection.sync_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        else:
            async with connection.get_connection() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception as e:
        await connection.dispose()
        pytest.skip(f"ClickHouse database connection failed: {e}")
    try:
        yield connection
    finally:
        await connection.dispose()


@pytest.fixture
async def ch_inspector(
    ch_connection: DatabaseConnection, ch_adapter: BaseAdapter
) -> MetadataInspector:
    """ClickHouse metadata inspector."""
    return MetadataInspector(ch_connection, ch_adapter)


@pytest.fixture
async def ch_analyzer(
    ch_connection: DatabaseConnection, ch_adapter: BaseAdapter
) -> StatisticsAnalyzer:
    """ClickHouse statistics analyzer."""
    return StatisticsAnalyzer(ch_connection, ch_adapter)


# ==================== Generic/Parametrized Fixtures ====================


@pytest.fixture(
    params=[
        pytest.param("postgresql", marks=pytest.mark.postgresql),
        pytest.param("clickhouse", marks=pytest.mark.clickhouse),
        pytest.param("mysql", marks=pytest.mark.mysql),
    ]
)
async def db_config(
    request, pg_database_url: Optional[str], ch_database_url: Optional[str]
) -> DatabaseConfig:
    """Parametrized database configuration for all supported databases."""
    db_type = request.param

    if db_type == "postgresql":
        if not pg_database_url:
            pytest.skip("PG_TEST_DATABASE_URL not set")
        return DatabaseConfig(url=pg_database_url)
    elif db_type == "clickhouse":
        if not ch_database_url:
            pytest.skip("CH_TEST_DATABASE_URL not set")
        return DatabaseConfig(url=ch_database_url)
    elif db_type == "mysql":
        mysql_url = os.getenv("MYSQL_TEST_DATABASE_URL")
        if not mysql_url:
            pytest.skip("MYSQL_TEST_DATABASE_URL not set")
        return DatabaseConfig(url=mysql_url)
    else:
        pytest.skip(f"Unknown database type: {db_type}")


@pytest.fixture
async def db_adapter(db_config: DatabaseConfig) -> BaseAdapter:
    """Parametrized adapter for all supported databases."""
    return create_adapter(db_config)


@pytest.fixture
async def db_connection(
    db_config: DatabaseConfig,
) -> AsyncGenerator[DatabaseConnection, None]:
    """Parametrized database connection for all supported databases."""
    connection = DatabaseConnection(db_config)
    try:
        await connection.initialize()
        if connection.sync_engine:
            with connection.sync_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        else:
            async with connection.get_connection() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception as e:
        await connection.dispose()
        pytest.skip(f"Database connection failed: {e}")
    try:
        yield connection
    finally:
        await connection.dispose()


# ==================== Test Helpers ====================


def assert_json_serializable(obj, message: str = "Object should be JSON serializable"):
    """Assert that an object can be JSON serialized."""
    import json

    try:
        json_str = json.dumps(obj)
        assert len(json_str) > 0, "JSON serialization produced empty string"
    except (TypeError, ValueError) as e:
        pytest.fail(f"{message}: {e}")


# ==================== Pytest Configuration ====================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "postgresql: PostgreSQL-specific tests")
    config.addinivalue_line("markers", "clickhouse: ClickHouse-specific tests")
    config.addinivalue_line("markers", "mysql: MySQL-specific tests")
    config.addinivalue_line(
        "markers", "integration: Integration tests requiring database"
    )
    config.addinivalue_line("markers", "slow: Slow-running tests")
    config.addinivalue_line("markers", "ssh_tunnel: SSH tunnel integration tests")
