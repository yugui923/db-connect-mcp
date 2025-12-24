"""Pytest configuration and shared fixtures for database tests.

This conftest.py is at the root of the tests/ directory and provides
fixtures for all test subdirectories (integration/, module/, unit/).
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
    StatisticsAnalyzer,
)
from db_connect_mcp.models.config import DatabaseConfig

# Load environment variables
load_dotenv()

# Fix for Windows: asyncpg requires SelectorEventLoop on Windows
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]


# ==================== Configuration Fixtures ====================


@pytest.fixture(scope="session")
def pg_database_url() -> str:
    """PostgreSQL test database URL.

    Priority:
    1. PG_TEST_DATABASE_URL (explicit test database override)
    2. Local Docker database (default: localhost:5432)
    """
    return os.getenv(
        "PG_TEST_DATABASE_URL",
        "postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb",
    )


@pytest.fixture(scope="session")
def ch_database_url() -> Optional[str]:
    """ClickHouse test database URL from environment."""
    return os.getenv("CH_TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def mysql_database_url() -> Optional[str]:
    """MySQL test database URL from environment."""
    return os.getenv("MYSQL_TEST_DATABASE_URL")


# ==================== PostgreSQL Fixtures ====================


@pytest.fixture
async def pg_config(pg_database_url: str) -> DatabaseConfig:
    """PostgreSQL database configuration."""
    return DatabaseConfig(url=pg_database_url)


@pytest.fixture
async def pg_adapter(pg_config: DatabaseConfig) -> BaseAdapter:
    """PostgreSQL adapter instance."""
    return create_adapter(pg_config)


@pytest.fixture
async def pg_connection(
    pg_config: DatabaseConfig,
) -> AsyncGenerator[DatabaseConnection, None]:
    """PostgreSQL database connection with proper cleanup."""
    connection = DatabaseConnection(pg_config)
    try:
        await connection.initialize()
        # Test actual connectivity (engine creation is lazy)
        async with connection.get_connection() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        # Skip test if database connection fails
        await connection.dispose()
        pytest.skip(f"PostgreSQL database connection failed: {e}")
    try:
        yield connection
    finally:
        await connection.dispose()


@pytest.fixture
async def pg_inspector(
    pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
) -> MetadataInspector:
    """PostgreSQL metadata inspector."""
    return MetadataInspector(pg_connection, pg_adapter)


@pytest.fixture
async def pg_analyzer(
    pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
) -> StatisticsAnalyzer:
    """PostgreSQL statistics analyzer."""
    return StatisticsAnalyzer(pg_connection, pg_adapter)


@pytest.fixture
async def pg_executor(pg_connection: DatabaseConnection, pg_adapter: BaseAdapter):
    """PostgreSQL query executor."""
    from db_connect_mcp.core import QueryExecutor

    return QueryExecutor(pg_connection, pg_adapter)


@pytest.fixture
def known_tables():
    """Known tables from local test database with their guaranteed columns.

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
    """PostgreSQL MCP server for protocol-level testing."""
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
        # Test actual connectivity
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
        # Test actual connectivity (handle both sync and async engines)
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
    """Assert that an object can be JSON serialized.

    Args:
        obj: The object to test for JSON serializability
        message: Custom error message if serialization fails

    Raises:
        AssertionError: If the object cannot be serialized to JSON

    Example:
        >>> result = await executor.execute_query("SELECT * FROM products LIMIT 10")
        >>> assert_json_serializable(result.model_dump())
    """
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
