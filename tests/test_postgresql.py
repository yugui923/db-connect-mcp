"""PostgreSQL adapter and integration tests"""

import pytest
from sqlalchemy import text

from db_connect_mcp.adapters.base import BaseAdapter
from db_connect_mcp.core import (
    DatabaseConnection,
    MetadataInspector,
    StatisticsAnalyzer,
)
from db_connect_mcp.models.config import DatabaseConfig

# Mark all tests in this module as PostgreSQL and integration tests
pytestmark = [pytest.mark.postgresql, pytest.mark.integration]


# ==================== Configuration Tests ====================


class TestPostgreSQLConfiguration:
    """Test PostgreSQL configuration and setup"""

    async def test_config_creation(self, pg_config: DatabaseConfig):
        """Test that PostgreSQL configuration is created correctly"""
        assert pg_config is not None
        assert pg_config.dialect == "postgresql"
        assert pg_config.driver == "asyncpg"

    async def test_adapter_creation(
        self, pg_adapter: BaseAdapter, pg_config: DatabaseConfig
    ):
        """Test that PostgreSQL adapter is created with correct capabilities"""
        assert pg_adapter is not None

        capabilities = pg_adapter.capabilities
        assert capabilities is not None

        # PostgreSQL should support these features
        assert capabilities.foreign_keys is True
        assert capabilities.indexes is True

        # Check supported features list
        features = capabilities.get_supported_features()
        assert len(features) > 0
        assert "foreign_keys" in features

    async def test_read_only_mode(self, pg_config: DatabaseConfig):
        """Test that read-only mode is properly configured"""
        assert pg_config.read_only is True


# ==================== Connection Tests ====================


class TestPostgreSQLConnection:
    """Test PostgreSQL connection and basic queries"""

    async def test_connection_initialization(self, pg_connection: DatabaseConnection):
        """Test that database connection initializes successfully"""
        assert pg_connection is not None
        # Engine may be lazy-initialized, so we just verify connection object exists

    async def test_database_connectivity(self, pg_connection: DatabaseConnection):
        """Test that we can connect and query the database"""
        async with pg_connection.get_connection() as conn:
            result = await conn.execute(text("SELECT version()"))
            row = result.fetchone()

            assert row is not None
            version = str(row[0])
            assert "PostgreSQL" in version
            assert len(version) > 0

    async def test_connection_context_manager(self, pg_connection: DatabaseConnection):
        """Test that connection context manager works properly"""
        async with pg_connection.get_connection() as conn:
            result = await conn.execute(text("SELECT 1 AS test"))
            row = result.fetchone()
            assert row is not None
            assert row[0] == 1


# ==================== Metadata Inspector Tests ====================


class TestPostgreSQLMetadata:
    """Test PostgreSQL metadata inspection"""

    async def test_inspector_creation(self, pg_inspector: MetadataInspector):
        """Test that metadata inspector is created successfully"""
        assert pg_inspector is not None

    async def test_get_schemas(self, pg_inspector: MetadataInspector):
        """Test listing database schemas"""
        schemas = await pg_inspector.get_schemas()

        assert schemas is not None
        assert len(schemas) > 0

        # Should have at least 'public' schema
        schema_names = [s.name for s in schemas]
        assert "public" in schema_names

        # Verify schema properties
        for schema in schemas:
            assert schema.name is not None
            assert isinstance(schema.name, str)
            assert schema.table_count is not None
            assert isinstance(schema.table_count, int)
            assert schema.table_count >= 0

    async def test_get_tables(self, pg_inspector: MetadataInspector):
        """Test listing tables in a schema"""
        tables = await pg_inspector.get_tables("public")

        assert tables is not None
        assert isinstance(tables, list)

        # If tables exist, verify their properties
        if tables:
            first_table = tables[0]
            assert first_table.name is not None
            assert isinstance(first_table.name, str)
            assert first_table.schema == "public"
            assert first_table.table_type is not None

    @pytest.mark.slow
    async def test_describe_table(self, pg_inspector: MetadataInspector):
        """Test getting detailed table information"""
        # Get tables first
        tables = await pg_inspector.get_tables("public")

        if not tables:
            pytest.skip("No tables in public schema")

        table_name = tables[0].name
        detailed_table = await pg_inspector.describe_table(table_name, "public")

        assert detailed_table is not None
        assert detailed_table.name == table_name
        assert detailed_table.schema == "public"
        assert detailed_table.columns is not None
        assert len(detailed_table.columns) > 0

        # Verify column properties
        first_column = detailed_table.columns[0]
        assert first_column.name is not None
        assert first_column.data_type is not None
        assert isinstance(first_column.nullable, bool)

        # Verify indexes and constraints exist (may be empty)
        assert detailed_table.indexes is not None
        assert detailed_table.constraints is not None

    async def test_get_relationships(
        self, pg_inspector: MetadataInspector, pg_adapter: BaseAdapter
    ):
        """Test getting table relationships (foreign keys)"""
        if not pg_adapter.capabilities.foreign_keys:
            pytest.skip("Database doesn't support foreign keys")

        tables = await pg_inspector.get_tables("public")

        if not tables:
            pytest.skip("No tables in public schema")

        # Check first few tables for relationships
        for table in tables[:5]:
            relationships = await pg_inspector.get_relationships(table.name, "public")
            assert relationships is not None
            assert isinstance(relationships, list)

            if relationships:
                rel = relationships[0]
                assert rel.from_table is not None
                assert rel.to_table is not None
                assert rel.from_columns is not None
                assert rel.to_columns is not None
                assert len(rel.from_columns) > 0
                assert len(rel.to_columns) > 0
                break

        # Note: Not all databases have foreign keys, so we don't assert relationship_found


# ==================== Statistics Analyzer Tests ====================


class TestPostgreSQLStatistics:
    """Test PostgreSQL statistics and analysis"""

    async def test_analyzer_creation(self, pg_analyzer: StatisticsAnalyzer):
        """Test that statistics analyzer is created successfully"""
        assert pg_analyzer is not None

    @pytest.mark.slow
    async def test_analyze_column(
        self, pg_inspector: MetadataInspector, pg_analyzer: StatisticsAnalyzer
    ):
        """Test column statistics analysis"""
        # Get a table with columns
        tables = await pg_inspector.get_tables("public")

        if not tables or not tables[0].columns:
            pytest.skip("No tables with columns in public schema")

        table_name = tables[0].name
        column_name = tables[0].columns[0].name

        stats = await pg_analyzer.analyze_column(table_name, column_name, "public")

        assert stats is not None
        assert stats.data_type is not None
        assert stats.total_rows is not None
        assert stats.total_rows >= 0
        assert stats.null_count is not None
        assert stats.null_count >= 0
        assert stats.null_count <= stats.total_rows

        # If there are rows, should have distinct count
        if stats.total_rows > 0:
            assert stats.distinct_count is not None
            assert stats.distinct_count > 0
            assert stats.distinct_count <= stats.total_rows

    @pytest.mark.slow
    async def test_sample_data_via_query(
        self, pg_connection: DatabaseConnection, pg_inspector: MetadataInspector
    ):
        """Test sampling data from tables using direct query"""
        tables = await pg_inspector.get_tables("public")

        if not tables:
            pytest.skip("No tables in public schema")

        table_name = tables[0].name

        # Sample data using a direct query
        async with pg_connection.get_connection() as conn:
            from sqlalchemy import text

            result = await conn.execute(
                text(f'SELECT * FROM "public"."{table_name}" LIMIT 5')
            )
            rows = result.fetchall()

        assert rows is not None
        assert isinstance(rows, list)
        assert len(rows) <= 5


# ==================== Integration Tests ====================


class TestPostgreSQLIntegration:
    """End-to-end integration tests"""

    async def test_full_workflow(
        self,
        pg_connection: DatabaseConnection,
        pg_inspector: MetadataInspector,
        pg_analyzer: StatisticsAnalyzer,
    ):
        """Test complete workflow: connect → inspect → analyze"""
        # 1. Verify connection works
        async with pg_connection.get_connection() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.fetchone() is not None

        # 2. Get schemas
        schemas = await pg_inspector.get_schemas()
        assert len(schemas) > 0

        # 3. Get tables
        tables = await pg_inspector.get_tables("public")
        assert tables is not None

        # 4. If tables exist, analyze them
        if tables and tables[0].columns:
            table_name = tables[0].name
            column_name = tables[0].columns[0].name

            # Describe table
            detailed = await pg_inspector.describe_table(table_name, "public")
            assert detailed is not None
            assert len(detailed.columns) > 0

            # Analyze column
            stats = await pg_analyzer.analyze_column(table_name, column_name, "public")
            assert stats is not None
            assert stats.total_rows >= 0
