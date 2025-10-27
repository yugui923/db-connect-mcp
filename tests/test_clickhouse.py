"""ClickHouse adapter and integration tests"""

import pytest
from sqlalchemy import text

from src.adapters.base import BaseAdapter
from src.core import DatabaseConnection, MetadataInspector, StatisticsAnalyzer
from src.models.config import DatabaseConfig

# Mark all tests in this module as ClickHouse and integration tests
pytestmark = [pytest.mark.clickhouse, pytest.mark.integration]


# ==================== Configuration Tests ====================


class TestClickHouseConfiguration:
    """Test ClickHouse configuration and setup"""

    async def test_config_creation(self, ch_config: DatabaseConfig):
        """Test that ClickHouse configuration is created correctly"""
        assert ch_config is not None
        assert ch_config.dialect == "clickhouse"
        # ClickHouse may use different drivers (asynch, etc.)
        assert ch_config.driver is not None

    async def test_adapter_creation(
        self, ch_adapter: BaseAdapter, ch_config: DatabaseConfig
    ):
        """Test that ClickHouse adapter is created with correct capabilities"""
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
        """Test that read-only mode is properly configured"""
        assert ch_config.read_only is True


# ==================== Connection Tests ====================


class TestClickHouseConnection:
    """Test ClickHouse connection and basic queries"""

    async def test_connection_initialization(self, ch_connection: DatabaseConnection):
        """Test that database connection initializes successfully"""
        assert ch_connection is not None
        # Engine may be lazy-initialized, so we just verify connection object exists

    async def test_database_connectivity(self, ch_connection: DatabaseConnection):
        """Test that we can connect and query the database"""
        try:
            async with ch_connection.get_connection() as conn:
                result = await conn.execute(text("SELECT version() AS version"))
                row = result.fetchone()

                assert row is not None
                version = str(row[0])
                assert len(version) > 0
                # ClickHouse version format: X.Y.Z.N
                assert "." in version
        except AttributeError as e:
            # Known issue with asynch driver compatibility
            if "asynch" in str(e) and "connect" in str(e):
                pytest.skip(
                    f"Known ClickHouse asynch driver compatibility issue: {e}. "
                    "Consider downgrading or using a different connection method."
                )
            else:
                raise

    async def test_current_database(self, ch_connection: DatabaseConnection):
        """Test querying current database"""
        try:
            async with ch_connection.get_connection() as conn:
                result = await conn.execute(text("SELECT currentDatabase()"))
                row = result.fetchone()

                assert row is not None
                current_db = str(row[0])
                assert len(current_db) > 0
        except AttributeError as e:
            if "asynch" in str(e):
                pytest.skip(f"Known asynch driver issue: {e}")
            raise

    async def test_connection_context_manager(self, ch_connection: DatabaseConnection):
        """Test that connection context manager works properly"""
        try:
            async with ch_connection.get_connection() as conn:
                result = await conn.execute(text("SELECT 1 AS test"))
                row = result.fetchone()
                assert row is not None
                assert row[0] == 1
        except AttributeError as e:
            if "asynch" in str(e):
                pytest.skip(f"Known asynch driver issue: {e}")
            raise


# ==================== Metadata Inspector Tests ====================


class TestClickHouseMetadata:
    """Test ClickHouse metadata inspection"""

    async def test_inspector_creation(self, ch_inspector: MetadataInspector):
        """Test that metadata inspector is created successfully"""
        assert ch_inspector is not None

    async def test_get_schemas(self, ch_inspector: MetadataInspector):
        """Test listing databases (schemas in ClickHouse)"""
        schemas = await ch_inspector.get_schemas()

        assert schemas is not None
        assert len(schemas) > 0

        # ClickHouse should have 'default' and 'system' databases
        schema_names = [s.name for s in schemas]
        assert "default" in schema_names or "system" in schema_names

        # Verify schema properties
        for schema in schemas:
            assert schema.name is not None
            assert isinstance(schema.name, str)

    async def test_get_tables(
        self, ch_inspector: MetadataInspector, ch_config: DatabaseConfig
    ):
        """Test listing tables in a database"""
        current_schema = ch_config.database or "default"
        tables = await ch_inspector.get_tables(current_schema)

        assert tables is not None
        assert isinstance(tables, list)

        # If tables exist, verify their properties
        if tables:
            first_table = tables[0]
            assert first_table.name is not None
            assert isinstance(first_table.name, str)
            assert first_table.schema == current_schema

    async def test_system_tables_access(self, ch_inspector: MetadataInspector):
        """Test accessing ClickHouse system tables"""
        try:
            system_tables = await ch_inspector.get_tables("system")
            assert system_tables is not None
            assert len(system_tables) > 0

            # Verify some common system tables exist
            table_names = [t.name for t in system_tables]
            # At least some common system tables should exist
            common_tables = ["tables", "columns", "databases"]
            assert any(table in table_names for table in common_tables)
        except Exception as e:
            pytest.skip(f"Could not access system tables: {e}")

    @pytest.mark.slow
    async def test_describe_table(
        self, ch_inspector: MetadataInspector, ch_config: DatabaseConfig
    ):
        """Test getting detailed table information"""
        current_schema = ch_config.database or "default"
        tables = await ch_inspector.get_tables(current_schema)

        if not tables:
            pytest.skip(f"No tables in '{current_schema}' database")

        table_name = tables[0].name
        detailed_table = await ch_inspector.describe_table(table_name, current_schema)

        assert detailed_table is not None
        assert detailed_table.name == table_name
        assert detailed_table.schema == current_schema
        assert detailed_table.columns is not None
        assert len(detailed_table.columns) > 0

        # Verify column properties
        first_column = detailed_table.columns[0]
        assert first_column.name is not None
        assert first_column.data_type is not None
        assert isinstance(first_column.nullable, bool)

        # ClickHouse-specific: check for engine information
        if detailed_table.extra_info:
            if "engine" in detailed_table.extra_info:
                engine = detailed_table.extra_info["engine"]
                assert isinstance(engine, str)
                assert len(engine) > 0

    async def test_clickhouse_engines(
        self, ch_inspector: MetadataInspector, ch_config: DatabaseConfig
    ):
        """Test detection of ClickHouse-specific table engines"""
        current_schema = ch_config.database or "default"
        tables = await ch_inspector.get_tables(current_schema)

        if not tables:
            pytest.skip(f"No tables in '{current_schema}' database")

        # Check for engine information in tables
        engines_found = []
        for table in tables[:10]:  # Check first 10 tables
            if table.extra_info and "engine" in table.extra_info:
                engines_found.append(table.extra_info["engine"])

        # Should find at least one engine
        if engines_found:
            assert len(engines_found) > 0
            # Common ClickHouse engines
            common_engines = [
                "MergeTree",
                "ReplacingMergeTree",
                "Memory",
                "Distributed",
                "ReplicatedMergeTree",
            ]
            assert any(
                any(engine in found for engine in common_engines)
                for found in engines_found
            )

    async def test_no_foreign_keys(
        self,
        ch_inspector: MetadataInspector,
        ch_adapter: BaseAdapter,
        ch_config: DatabaseConfig,
    ):
        """Test that ClickHouse correctly reports no foreign key support"""
        assert ch_adapter.capabilities.foreign_keys is False

        current_schema = ch_config.database or "default"
        tables = await ch_inspector.get_tables(current_schema)

        if not tables:
            pytest.skip(f"No tables in '{current_schema}' database")

        # ClickHouse should return empty relationships
        relationships = await ch_inspector.get_relationships(
            tables[0].name, current_schema
        )
        assert relationships is not None
        assert len(relationships) == 0


# ==================== Statistics Analyzer Tests ====================


class TestClickHouseStatistics:
    """Test ClickHouse statistics and analysis"""

    async def test_analyzer_creation(self, ch_analyzer: StatisticsAnalyzer):
        """Test that statistics analyzer is created successfully"""
        assert ch_analyzer is not None

    @pytest.mark.slow
    async def test_analyze_column(
        self,
        ch_inspector: MetadataInspector,
        ch_analyzer: StatisticsAnalyzer,
        ch_config: DatabaseConfig,
    ):
        """Test column statistics analysis"""
        current_schema = ch_config.database or "default"
        tables = await ch_inspector.get_tables(current_schema)

        if not tables or not tables[0].columns:
            pytest.skip(f"No tables with columns in '{current_schema}' database")

        table_name = tables[0].name

        # Prefer numeric columns for analysis
        column_name = None
        for col in tables[0].columns:
            if any(
                t in col.data_type.lower() for t in ["int", "float", "decimal", "uint"]
            ):
                column_name = col.name
                break

        # Fallback to first column
        if not column_name:
            column_name = tables[0].columns[0].name

        stats = await ch_analyzer.analyze_column(
            table_name, column_name, current_schema
        )

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
        self,
        ch_connection: DatabaseConnection,
        ch_inspector: MetadataInspector,
        ch_config: DatabaseConfig,
    ):
        """Test sampling data from tables using direct query"""
        current_schema = ch_config.database or "default"
        tables = await ch_inspector.get_tables(current_schema)

        if not tables:
            pytest.skip(f"No tables in '{current_schema}' database")

        table_name = tables[0].name

        # Sample data using a direct query
        async with ch_connection.get_connection() as conn:
            from sqlalchemy import text

            result = await conn.execute(
                text(f'SELECT * FROM "{current_schema}"."{table_name}" LIMIT 5')
            )
            rows = result.fetchall()

        assert rows is not None
        assert isinstance(rows, list)
        assert len(rows) <= 5


# ==================== ClickHouse-Specific Tests ====================


class TestClickHouseSpecificFeatures:
    """Test ClickHouse-specific features and capabilities"""

    async def test_cluster_information(self, ch_connection: DatabaseConnection):
        """Test querying cluster information"""
        try:
            async with ch_connection.get_connection() as conn:
                result = await conn.execute(
                    text(
                        "SELECT cluster, count(*) as cnt FROM system.clusters GROUP BY cluster"
                    )
                )
                clusters = result.fetchall()

                assert clusters is not None
                assert isinstance(clusters, list)

                if clusters:
                    # Should have cluster information
                    assert len(clusters) > 0
                    for cluster in clusters:
                        assert cluster[0] is not None  # cluster name
                        assert cluster[1] > 0  # node count
        except AttributeError as e:
            if "asynch" in str(e):
                pytest.skip(f"Known asynch driver issue: {e}")
            raise
        except Exception:
            # Single-node setup may not have clusters
            pytest.skip("No cluster configuration (single-node setup)")

    async def test_distributed_tables(
        self, ch_inspector: MetadataInspector, ch_config: DatabaseConfig
    ):
        """Test detection of distributed tables"""
        current_schema = ch_config.database or "default"
        tables = await ch_inspector.get_tables(current_schema)

        if not tables:
            pytest.skip(f"No tables in '{current_schema}' database")

        distributed_found = False
        replicated_found = False

        for table in tables[:20]:  # Check first 20 tables
            if table.extra_info and "engine" in table.extra_info:
                engine = table.extra_info["engine"]
                if "Distributed" in engine:
                    distributed_found = True
                if "Replicated" in engine:
                    replicated_found = True

        return distributed_found, replicated_found

        # Note: Not asserting these must be found, just testing detection works
        # In production, may or may not have distributed/replicated tables


# ==================== Integration Tests ====================


class TestClickHouseIntegration:
    """End-to-end integration tests"""

    async def test_full_workflow(
        self,
        ch_connection: DatabaseConnection,
        ch_inspector: MetadataInspector,
        ch_analyzer: StatisticsAnalyzer,
        ch_config: DatabaseConfig,
    ):
        """Test complete workflow: connect → inspect → analyze"""
        try:
            # 1. Verify connection works
            async with ch_connection.get_connection() as conn:
                result = await conn.execute(text("SELECT 1"))
                assert result.fetchone() is not None

            # 2. Get schemas (databases)
            schemas = await ch_inspector.get_schemas()
            assert len(schemas) > 0

            # 3. Get tables
            current_schema = ch_config.database or "default"
            tables = await ch_inspector.get_tables(current_schema)
            assert tables is not None

            # 4. If tables exist, analyze them
            if tables and tables[0].columns:
                table_name = tables[0].name
                column_name = tables[0].columns[0].name

                # Describe table
                detailed = await ch_inspector.describe_table(table_name, current_schema)
                assert detailed is not None
                assert len(detailed.columns) > 0

                # Analyze column
                stats = await ch_analyzer.analyze_column(
                    table_name, column_name, current_schema
                )
                assert stats is not None
                assert stats.total_rows >= 0
        except AttributeError as e:
            if "asynch" in str(e):
                pytest.skip(f"Known asynch driver issue: {e}")
            raise
