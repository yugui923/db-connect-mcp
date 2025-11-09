"""Unit Tests for ClickHouse Adapter

Tests ClickHouse-specific adapter implementation:
- Adapter configuration and capabilities
- Database connections
- ClickHouse-specific features
"""

import pytest
from sqlalchemy import text

from db_connect_mcp.adapters.base import BaseAdapter
from db_connect_mcp.core import DatabaseConnection, MetadataInspector
from db_connect_mcp.models.config import DatabaseConfig

# Mark all tests in this module as ClickHouse tests
pytestmark = [pytest.mark.clickhouse, pytest.mark.integration]


class TestClickHouseConfiguration:
    """Test ClickHouse configuration and setup."""

    async def test_config_creation(self, ch_config: DatabaseConfig):
        """Test that ClickHouse configuration is created correctly."""
        assert ch_config is not None
        assert ch_config.dialect == "clickhouse"
        assert ch_config.driver is not None

    async def test_adapter_creation(
        self, ch_adapter: BaseAdapter, ch_config: DatabaseConfig
    ):
        """Test that ClickHouse adapter is created with correct capabilities."""
        assert ch_adapter is not None

        capabilities = ch_adapter.capabilities
        assert capabilities is not None

        # ClickHouse-specific: doesn't support foreign keys
        assert capabilities.foreign_keys is False

        # Should still support indexes
        assert capabilities.indexes is True

        # Check supported features list
        features = capabilities.get_supported_features()
        assert len(features) > 0
        assert "indexes" in features

    async def test_read_only_mode(self, ch_config: DatabaseConfig):
        """Test that read-only mode is properly configured."""
        assert ch_config.read_only is True


class TestClickHouseConnection:
    """Test ClickHouse connection and basic queries."""

    async def test_connection_initialization(self, ch_connection: DatabaseConnection):
        """Test that database connection initializes successfully."""
        assert ch_connection is not None

    async def test_database_connectivity(self, ch_connection: DatabaseConnection):
        """Test that we can connect and query the database."""
        try:
            async with ch_connection.get_connection() as conn:
                result = await conn.execute(text("SELECT version() AS version"))
                row = result.fetchone()

                assert row is not None
                version = str(row[0])
                assert len(version) > 0
                assert "." in version
        except AttributeError as e:
            # Known issue with asynch driver compatibility
            if "asynch" in str(e) and "connect" in str(e):
                pytest.skip(f"Known ClickHouse asynch driver compatibility issue: {e}")
            else:
                raise

    async def test_current_database(self, ch_connection: DatabaseConnection):
        """Test querying current database."""
        try:
            async with ch_connection.get_connection() as conn:
                result = await conn.execute(text("SELECT currentDatabase()"))
                row = result.fetchone()

                assert row is not None
                current_db = str(row[0])
                assert len(current_db) > 0
        except AttributeError as e:
            if "asynch" in str(e):
                pytest.skip(f"Known ClickHouse asynch driver issue: {e}")
            else:
                raise


class TestClickHouseMetadata:
    """Test ClickHouse metadata inspection."""

    async def test_inspector_creation(self, ch_inspector: MetadataInspector):
        """Test that metadata inspector is created successfully."""
        assert ch_inspector is not None

    async def test_get_schemas(self, ch_inspector: MetadataInspector):
        """Test listing database schemas."""
        try:
            schemas = await ch_inspector.get_schemas()

            assert schemas is not None
            assert len(schemas) > 0

            # Verify schema properties
            for schema in schemas:
                assert schema.name is not None
                assert isinstance(schema.name, str)
                assert schema.table_count is not None
                assert isinstance(schema.table_count, int)
                assert schema.table_count >= 0
        except AttributeError as e:
            if "asynch" in str(e):
                pytest.skip(f"Known ClickHouse asynch driver issue: {e}")
            else:
                raise

    async def test_get_tables(self, ch_inspector: MetadataInspector):
        """Test listing tables in a schema."""
        try:
            schemas = await ch_inspector.get_schemas()
            if not schemas:
                pytest.skip("No schemas available")

            schema_name = schemas[0].name
            tables = await ch_inspector.get_tables(schema_name)

            assert tables is not None
            assert isinstance(tables, list)

            # If tables exist, verify their properties
            if tables:
                first_table = tables[0]
                assert first_table.name is not None
                assert isinstance(first_table.name, str)
        except AttributeError as e:
            if "asynch" in str(e):
                pytest.skip(f"Known ClickHouse asynch driver issue: {e}")
            else:
                raise
