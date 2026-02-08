"""Unit tests for adapters module initialization and factory functions."""

import pytest

from db_connect_mcp.adapters import (
    BaseAdapter,
    ClickHouseAdapter,
    MySQLAdapter,
    PostgresAdapter,
    create_adapter,
    detect_dialect,
)
from db_connect_mcp.models.config import DatabaseConfig


class TestDetectDialect:
    """Tests for detect_dialect function."""

    def test_detect_postgresql_dialect(self):
        """Test detecting PostgreSQL dialect."""
        assert detect_dialect("postgresql://user:pass@host:5432/db") == "postgresql"

    def test_detect_postgresql_with_driver(self):
        """Test detecting PostgreSQL with asyncpg driver."""
        assert (
            detect_dialect("postgresql+asyncpg://user:pass@host:5432/db")
            == "postgresql"
        )

    def test_detect_mysql_dialect(self):
        """Test detecting MySQL dialect."""
        assert detect_dialect("mysql://user:pass@host:3306/db") == "mysql"

    def test_detect_mysql_with_driver(self):
        """Test detecting MySQL with aiomysql driver."""
        assert detect_dialect("mysql+aiomysql://user:pass@host:3306/db") == "mysql"

    def test_detect_clickhouse_dialect(self):
        """Test detecting ClickHouse dialect."""
        assert detect_dialect("clickhouse://user:pass@host:8123/db") == "clickhouse"

    def test_detect_clickhousedb_dialect(self):
        """Test detecting clickhousedb dialect."""
        assert detect_dialect("clickhousedb://user:pass@host:8123/db") == "clickhousedb"

    def test_detect_postgres_alias(self):
        """Test detecting 'postgres' alias."""
        assert detect_dialect("postgres://user:pass@host:5432/db") == "postgres"

    def test_detect_mariadb_alias(self):
        """Test detecting 'mariadb' alias."""
        assert detect_dialect("mariadb://user:pass@host:3306/db") == "mariadb"

    def test_invalid_url_raises_value_error(self):
        """Test that invalid URL raises ValueError."""
        with pytest.raises(ValueError, match="Failed to detect dialect"):
            detect_dialect("not-a-valid-url")

    def test_empty_url_raises_value_error(self):
        """Test that empty URL raises ValueError."""
        with pytest.raises(ValueError, match="Failed to detect dialect"):
            detect_dialect("")

    def test_url_without_scheme_raises_value_error(self):
        """Test that URL without scheme raises ValueError."""
        with pytest.raises(ValueError, match="Failed to detect dialect"):
            detect_dialect("user:pass@host:5432/db")


class TestCreateAdapter:
    """Tests for create_adapter factory function."""

    def test_create_postgresql_adapter(self):
        """Test creating PostgreSQL adapter."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")
        adapter = create_adapter(config)
        assert isinstance(adapter, PostgresAdapter)
        assert isinstance(adapter, BaseAdapter)

    def test_create_mysql_adapter(self):
        """Test creating MySQL adapter."""
        config = DatabaseConfig(url="mysql://user:pass@host:3306/db")
        adapter = create_adapter(config)
        assert isinstance(adapter, MySQLAdapter)
        assert isinstance(adapter, BaseAdapter)

    def test_create_clickhouse_adapter(self):
        """Test creating ClickHouse adapter."""
        config = DatabaseConfig(url="clickhouse://user:pass@host:8123/db")
        adapter = create_adapter(config)
        assert isinstance(adapter, ClickHouseAdapter)
        assert isinstance(adapter, BaseAdapter)

    def test_unsupported_dialect_raises_value_error(self):
        """Test that unsupported dialect raises ValueError."""
        from unittest.mock import patch

        # Create a config with a mocked dialect property
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")

        # Patch the dialect property to return an unsupported value
        with patch.object(
            type(config), "dialect", property(lambda self: "unsupported")
        ):
            with pytest.raises(ValueError, match="Unsupported database dialect"):
                create_adapter(config)


class TestAdapterCapabilities:
    """Tests for adapter capabilities."""

    def test_postgresql_adapter_capabilities(self):
        """Test PostgreSQL adapter has expected capabilities."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")
        adapter = create_adapter(config)

        caps = adapter.capabilities
        assert caps.foreign_keys is True
        assert caps.indexes is True
        assert caps.advanced_stats is True
        assert caps.explain_plans is True
        assert caps.profiling is True

    def test_mysql_adapter_capabilities(self):
        """Test MySQL adapter has expected capabilities."""
        config = DatabaseConfig(url="mysql://user:pass@host:3306/db")
        adapter = create_adapter(config)

        caps = adapter.capabilities
        assert caps.foreign_keys is True
        assert caps.indexes is True
        assert caps.advanced_stats is False  # MySQL doesn't have advanced stats
        assert caps.explain_plans is True

    def test_clickhouse_adapter_capabilities(self):
        """Test ClickHouse adapter has expected capabilities."""
        config = DatabaseConfig(url="clickhouse://user:pass@host:8123/db")
        adapter = create_adapter(config)

        caps = adapter.capabilities
        assert caps.foreign_keys is False  # ClickHouse doesn't have FKs
        assert caps.indexes is True  # ClickHouse has specialized indexes
        assert caps.advanced_stats is True  # ClickHouse has columnar statistics
        assert caps.explain_plans is True
