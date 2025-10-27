"""Database adapters for specific database implementations."""

from sqlalchemy.engine.url import make_url

from .base import BaseAdapter
from .clickhouse import ClickHouseAdapter
from .mysql import MySQLAdapter
from .postgresql import PostgresAdapter
from ..models.config import DatabaseConfig

__all__ = [
    "BaseAdapter",
    "PostgresAdapter",
    "MySQLAdapter",
    "ClickHouseAdapter",
    "create_adapter",
    "detect_dialect",
]


def detect_dialect(url: str) -> str:
    """
    Detect database dialect from connection URL.

    Args:
        url: Database connection URL

    Returns:
        Dialect name (postgresql, mysql, clickhouse)

    Raises:
        ValueError: If dialect cannot be detected
    """
    try:
        parsed_url = make_url(url)
        # Extract base dialect (e.g., "postgresql" from "postgresql+asyncpg")
        dialect = parsed_url.drivername.split("+")[0]
        return dialect
    except Exception as e:
        raise ValueError(f"Failed to detect dialect from URL: {e}")


def create_adapter(config: DatabaseConfig) -> BaseAdapter:
    """
    Factory function to create appropriate database adapter.

    Args:
        config: Database configuration

    Returns:
        Database adapter instance

    Raises:
        ValueError: If database type is not supported
    """
    dialect = config.dialect

    adapters = {
        "postgresql": PostgresAdapter,
        "mysql": MySQLAdapter,
        "clickhouse": ClickHouseAdapter,
    }

    adapter_class = adapters.get(dialect)

    if adapter_class is None:
        raise ValueError(
            f"Unsupported database dialect: {dialect}. "
            f"Supported dialects: {', '.join(adapters.keys())}"
        )

    return adapter_class()
