"""Pytest configuration and shared fixtures for database tests"""

import os
import sys
from typing import AsyncGenerator, Optional

import pytest
from dotenv import load_dotenv

from src.adapters import create_adapter
from src.adapters.base import BaseAdapter
from src.core import DatabaseConnection, MetadataInspector, StatisticsAnalyzer
from src.models.config import DatabaseConfig

# Load environment variables
load_dotenv()

# Fix for Windows: asyncpg requires SelectorEventLoop on Windows
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]


# ==================== Configuration Fixtures ====================


@pytest.fixture(scope="session")
def pg_database_url() -> Optional[str]:
    """PostgreSQL test database URL from environment"""
    return os.getenv("PG_TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def ch_database_url() -> Optional[str]:
    """ClickHouse test database URL from environment"""
    return os.getenv("CH_TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def mysql_database_url() -> Optional[str]:
    """MySQL test database URL from environment"""
    return os.getenv("MYSQL_TEST_DATABASE_URL")


# ==================== PostgreSQL Fixtures ====================


@pytest.fixture
async def pg_config(pg_database_url: Optional[str]) -> DatabaseConfig:
    """PostgreSQL database configuration"""
    if not pg_database_url:
        pytest.skip("PG_TEST_DATABASE_URL not set in environment")
    return DatabaseConfig(url=pg_database_url)


@pytest.fixture
async def pg_adapter(pg_config: DatabaseConfig) -> BaseAdapter:
    """PostgreSQL adapter instance"""
    return create_adapter(pg_config)


@pytest.fixture
async def pg_connection(
    pg_config: DatabaseConfig,
) -> AsyncGenerator[DatabaseConnection, None]:
    """PostgreSQL database connection with proper cleanup"""
    connection = DatabaseConnection(pg_config)
    await connection.initialize()
    try:
        yield connection
    finally:
        await connection.dispose()


@pytest.fixture
async def pg_inspector(
    pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
) -> MetadataInspector:
    """PostgreSQL metadata inspector"""
    return MetadataInspector(pg_connection, pg_adapter)


@pytest.fixture
async def pg_analyzer(
    pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
) -> StatisticsAnalyzer:
    """PostgreSQL statistics analyzer"""
    return StatisticsAnalyzer(pg_connection, pg_adapter)


# ==================== ClickHouse Fixtures ====================


@pytest.fixture
async def ch_config(ch_database_url: Optional[str]) -> DatabaseConfig:
    """ClickHouse database configuration"""
    if not ch_database_url:
        pytest.skip("CH_TEST_DATABASE_URL not set in environment")
    return DatabaseConfig(url=ch_database_url)


@pytest.fixture
async def ch_adapter(ch_config: DatabaseConfig) -> BaseAdapter:
    """ClickHouse adapter instance"""
    return create_adapter(ch_config)


@pytest.fixture
async def ch_connection(
    ch_config: DatabaseConfig,
) -> AsyncGenerator[DatabaseConnection, None]:
    """ClickHouse database connection with proper cleanup"""
    connection = DatabaseConnection(ch_config)
    await connection.initialize()
    try:
        yield connection
    finally:
        await connection.dispose()


@pytest.fixture
async def ch_inspector(
    ch_connection: DatabaseConnection, ch_adapter: BaseAdapter
) -> MetadataInspector:
    """ClickHouse metadata inspector"""
    return MetadataInspector(ch_connection, ch_adapter)


@pytest.fixture
async def ch_analyzer(
    ch_connection: DatabaseConnection, ch_adapter: BaseAdapter
) -> StatisticsAnalyzer:
    """ClickHouse statistics analyzer"""
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
    """Parametrized database configuration for all supported databases"""
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
    """Parametrized adapter for all supported databases"""
    return create_adapter(db_config)


@pytest.fixture
async def db_connection(
    db_config: DatabaseConfig,
) -> AsyncGenerator[DatabaseConnection, None]:
    """Parametrized database connection for all supported databases"""
    connection = DatabaseConnection(db_config)
    await connection.initialize()
    try:
        yield connection
    finally:
        await connection.dispose()


# ==================== Pytest Configuration ====================


def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line("markers", "postgresql: PostgreSQL-specific tests")
    config.addinivalue_line("markers", "clickhouse: ClickHouse-specific tests")
    config.addinivalue_line("markers", "mysql: MySQL-specific tests")
    config.addinivalue_line(
        "markers", "integration: Integration tests requiring database"
    )
    config.addinivalue_line("markers", "slow: Slow-running tests")
