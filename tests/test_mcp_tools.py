"""Comprehensive MCP Server Tools Testing

Tests all 10 MCP tool functions against real databases with systematic validation.
Run with: pytest tests/test_mcp_tools.py -v
"""

import json

import pytest

from db_connect_mcp.adapters.base import BaseAdapter
from db_connect_mcp.core import (
    DatabaseConnection,
    MetadataInspector,
    QueryExecutor,
    StatisticsAnalyzer,
)


class TestMCPTools:
    """Comprehensive test suite for all MCP server tools."""

    # ============= Tool 1: get_database_info =============

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_get_database_info(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test get_database_info returns complete metadata."""
        # Get database version
        version = await pg_connection.get_version()

        # Validate version is returned
        assert version is not None
        assert len(version) > 0
        assert "PostgreSQL" in version or "postgres" in version.lower()

        # Validate capabilities
        capabilities = pg_adapter.capabilities
        assert capabilities.foreign_keys is True
        assert capabilities.indexes is True
        assert capabilities.explain_plans is True

        # Validate supported features list
        features = capabilities.get_supported_features()
        assert len(features) > 0
        assert "foreign_keys" in features
        assert "indexes" in features

    # ============= Tool 2: list_schemas =============

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_schemas(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test list_schemas returns schema information with metadata."""
        inspector = MetadataInspector(pg_connection, pg_adapter)

        schemas = await inspector.get_schemas()

        # Validate schemas returned
        assert len(schemas) > 0

        for schema in schemas:
            # Validate schema structure
            assert schema.name is not None
            assert len(schema.name) > 0

            # Validate table count is populated
            assert schema.table_count is not None
            assert schema.table_count >= 0

            # For schemas with tables, size might be available
            # Note: size_bytes can be None for views, foreign tables, or permission issues
            # We just validate the field exists and is the right type
            if schema.size_bytes is not None:
                assert isinstance(schema.size_bytes, int)
                assert schema.size_bytes >= 0

    # ============= Tool 3: list_tables =============

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_tables_with_metadata(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test list_tables returns tables with complete metadata (row counts, sizes)."""
        inspector = MetadataInspector(pg_connection, pg_adapter)

        # Get tables from public schema
        tables = await inspector.get_tables("public", include_views=True)

        # Should have at least some tables
        assert len(tables) > 0

        # Find a base table to validate
        base_table = None
        for table in tables:
            if table.table_type == "BASE TABLE":
                base_table = table
                break

        if base_table:
            # Validate metadata fields exist and are properly typed
            # Note: row_count and size_bytes can be None for certain table types
            # (e.g., foreign tables, partitioned tables) or due to permissions
            # PostgreSQL returns row_count=-1 for tables that haven't been ANALYZEd yet
            if base_table.row_count is not None:
                assert isinstance(base_table.row_count, int)
                # -1 is valid for PostgreSQL (means stats not gathered yet)
                assert base_table.row_count >= -1

            if base_table.size_bytes is not None:
                assert isinstance(base_table.size_bytes, int)
                assert base_table.size_bytes >= 0

    # ============= Tool 4: describe_table =============

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_describe_table_complete(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test describe_table returns comprehensive table information."""
        inspector = MetadataInspector(pg_connection, pg_adapter)

        # Get first table
        tables = await inspector.get_tables("public")
        assert len(tables) > 0

        table_name = tables[0].name
        table_info = await inspector.describe_table(table_name, "public")

        # Validate basic info
        assert table_info.name == table_name
        assert table_info.schema == "public"

        # Validate columns
        assert len(table_info.columns) > 0
        for col in table_info.columns:
            assert col.name is not None
            assert col.data_type is not None
            assert col.nullable is not None

        # Validate statistics fields exist and are properly typed
        # Note: row_count and size_bytes can be None for certain table types
        # (e.g., foreign tables, partitioned tables) or due to permissions
        # PostgreSQL returns row_count=-1 for tables that haven't been ANALYZEd yet
        if table_info.table_type == "BASE TABLE":
            # Validate that if statistics are present, they have sensible values
            if table_info.row_count is not None:
                assert isinstance(table_info.row_count, int)
                # -1 is valid for PostgreSQL (means stats not gathered yet)
                assert table_info.row_count >= -1

            if table_info.size_bytes is not None:
                assert isinstance(table_info.size_bytes, int)
                assert table_info.size_bytes >= 0

    # ============= Tool 5: execute_query =============

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_execute_query(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test execute_query runs SELECT queries correctly."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        # Simple query
        result = await executor.execute_query("SELECT 1 as test_col", limit=10)

        # Validate result structure
        assert result.query is not None
        assert result.row_count == 1
        assert len(result.columns) == 1
        assert result.columns[0] == "test_col"
        assert len(result.rows) == 1
        assert result.rows[0]["test_col"] == 1
        assert result.execution_time_ms is not None
        assert result.execution_time_ms > 0

    # ============= Tool 6: sample_data =============

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_sample_data_json_serialization(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test sample_data with various data types - this was BROKEN due to JSON serialization."""
        executor = QueryExecutor(pg_connection, pg_adapter)
        inspector = MetadataInspector(pg_connection, pg_adapter)

        # Get a table
        tables = await inspector.get_tables("public")
        if not tables:
            pytest.skip("No tables available for testing")

        table_name = tables[0].name

        # Sample data - this used to fail with JSON serialization errors
        result = await executor.sample_data(table_name, "public", limit=5)

        # Validate result
        assert result.row_count >= 0
        assert len(result.columns) > 0

        # Critical: Verify JSON serialization works
        # This was failing before the fix
        try:
            json_str = json.dumps(result.model_dump())
            assert len(json_str) > 0
        except TypeError as e:
            pytest.fail(f"JSON serialization failed: {e}")

        # Verify rows are JSON-safe
        for row in result.rows:
            try:
                json.dumps(row)
            except TypeError as e:
                pytest.fail(f"Row data not JSON-safe: {e}")

    # ============= Tool 7: get_table_relationships =============

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_get_table_relationships(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test get_table_relationships finds foreign keys."""
        if not pg_adapter.capabilities.foreign_keys:
            pytest.skip("Database doesn't support foreign keys")

        inspector = MetadataInspector(pg_connection, pg_adapter)
        tables = await inspector.get_tables("public")

        # Try to find a table with relationships
        for table in tables[:10]:  # Check first 10 tables
            relationships = await inspector.get_relationships(table.name, "public")

            if relationships:
                rel = relationships[0]

                # Validate relationship structure
                assert rel.from_table is not None
                assert rel.to_table is not None
                assert len(rel.from_columns) > 0
                assert len(rel.to_columns) > 0
                assert rel.constraint_name is not None
                break

        # Note: Not all databases will have relationships, so we just check structure

    # ============= Tool 8: analyze_column =============

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_analyze_column_numeric(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test analyze_column with numeric columns - this was BROKEN."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        analyzer = StatisticsAnalyzer(pg_connection, pg_adapter)
        inspector = MetadataInspector(pg_connection, pg_adapter)

        # Find a table with numeric columns
        tables = await inspector.get_tables("public")
        if not tables:
            pytest.skip("No tables available")

        for table in tables[:5]:
            table_info = await inspector.describe_table(table.name, "public")

            # Find numeric column
            numeric_col = None
            for col in table_info.columns:
                if any(
                    t in col.data_type.lower()
                    for t in ["int", "numeric", "decimal", "float", "real", "double"]
                ):
                    numeric_col = col.name
                    break

            if numeric_col:
                # This used to fail with SQL syntax errors
                stats = await analyzer.analyze_column(table.name, numeric_col, "public")

                # Validate basic stats
                assert stats.column == numeric_col
                assert stats.data_type is not None
                assert stats.total_rows >= 0
                assert stats.null_count >= 0

                # For numeric columns, should have numeric stats
                # Note: might be NULL if column is all NULL
                if stats.total_rows > stats.null_count:
                    assert stats.min_value is not None
                    assert stats.max_value is not None

                # Verify JSON serialization (min/max could be Decimal, etc.)
                try:
                    json.dumps(stats.model_dump())
                except TypeError as e:
                    pytest.fail(f"Stats not JSON-safe: {e}")

                break

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_analyze_column_text(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test analyze_column with text columns - this was BROKEN."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        analyzer = StatisticsAnalyzer(pg_connection, pg_adapter)
        inspector = MetadataInspector(pg_connection, pg_adapter)

        # Find a table with text columns
        tables = await inspector.get_tables("public")
        if not tables:
            pytest.skip("No tables available")

        for table in tables[:5]:
            table_info = await inspector.describe_table(table.name, "public")

            # Find text column
            text_col = None
            for col in table_info.columns:
                if any(t in col.data_type.lower() for t in ["text", "varchar", "char"]):
                    text_col = col.name
                    break

            if text_col:
                # This used to fail trying to compute AVG/STDDEV on text
                stats = await analyzer.analyze_column(table.name, text_col, "public")

                # Validate basic stats work for text
                assert stats.column == text_col
                assert stats.data_type is not None
                assert stats.total_rows >= 0
                assert stats.null_count >= 0

                # Text columns should NOT have numeric stats
                # (or should have them as NULL)
                # Min/Max should work as text sorting

                # Verify no SQL errors occurred
                assert (
                    stats.warning is None or "unavailable" not in stats.warning.lower()
                )

                break

    # ============= Tool 9: explain_query =============

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_explain_query_format(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test explain_query returns properly formatted plan - this was BROKEN."""
        if not pg_adapter.capabilities.explain_plans:
            pytest.skip("Database doesn't support EXPLAIN")

        executor = QueryExecutor(pg_connection, pg_adapter)

        # Simple query to explain
        plan = await executor.explain_query("SELECT 1", analyze=False)

        # Validate plan structure
        assert plan.query == "SELECT 1"
        assert plan.plan is not None
        assert len(plan.plan) > 0

        # Critical: plan_json should be parsed dict, not escaped string
        # This was the bug - it was returning "[{'Plan': ...}]" as string
        if plan.plan_json is not None:
            assert isinstance(plan.plan_json, (dict, list)), (
                f"plan_json should be dict/list, not string: {type(plan.plan_json)}"
            )

            # Verify it's proper JSON structure
            try:
                json.dumps(plan.plan_json)
            except TypeError as e:
                pytest.fail(f"plan_json not JSON-safe: {e}")

        # Validate cost estimates if present
        # Note: Simple queries might not have detailed cost estimates
        # We validate that if present, they have sensible values
        if plan.estimated_cost is not None:
            assert isinstance(plan.estimated_cost, (int, float))
            assert plan.estimated_cost >= 0

        if plan.estimated_rows is not None:
            assert isinstance(plan.estimated_rows, (int, float))
            assert plan.estimated_rows >= 0

        # At minimum, we should have the plan text
        assert plan.plan is not None
        assert len(plan.plan) > 0

    # ============= Tool 10: profile_database =============

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_profile_database(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test profile_database returns comprehensive stats - this was NOT IMPLEMENTED."""
        if not pg_adapter.capabilities.profiling:
            pytest.skip("Database doesn't support profiling")

        # Extract database name
        database_name = "test_db"

        async with pg_connection.get_connection() as conn:
            profile = await pg_adapter.profile_database(conn, database_name)

        # Validate profile structure
        assert profile.database_name == database_name
        assert profile.version is not None
        assert len(profile.version) > 0

        # Should have schema count
        assert profile.total_schemas >= 0
        assert profile.total_tables >= 0

        # Should have schema breakdown
        assert len(profile.schemas) >= 0

        # Should have largest tables
        assert isinstance(profile.largest_tables, list)

        # If we have data, validate structure
        if profile.largest_tables:
            table = profile.largest_tables[0]
            assert table.name is not None
            assert table.size_bytes is not None

        # Verify JSON serialization
        try:
            json.dumps(profile.model_dump())
        except TypeError as e:
            pytest.fail(f"Profile not JSON-safe: {e}")


# ============= Data Type Coverage Tests =============


class TestDataTypeCoverage:
    """Test all PostgreSQL data types for JSON serialization."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_timestamp_columns(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test TIMESTAMP columns serialize correctly - was BROKEN."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        # Query with timestamp
        result = await executor.execute_query(
            "SELECT NOW() as ts, CURRENT_DATE as dt, CURRENT_TIME as tm", limit=1
        )

        assert len(result.rows) == 1
        row = result.rows[0]

        # Verify timestamp values are JSON-safe (ISO strings)
        assert isinstance(row["ts"], str)
        assert isinstance(row["dt"], str)
        assert isinstance(row["tm"], str)

        # Verify full JSON serialization works
        json.dumps(result.model_dump())

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_inet_columns(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test INET columns serialize correctly - was BROKEN."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        # Query with INET type
        result = await executor.execute_query(
            "SELECT '192.168.1.1'::inet as ip4, '::1'::inet as ip6", limit=1
        )

        assert len(result.rows) == 1
        row = result.rows[0]

        # Verify IP addresses are strings
        assert isinstance(row["ip4"], str)
        assert isinstance(row["ip6"], str)
        assert "192.168.1.1" in row["ip4"]

        # Verify full JSON serialization works
        json.dumps(result.model_dump())

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_uuid_columns(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test UUID columns serialize correctly."""
        executor = QueryExecutor(pg_connection, pg_adapter)

        # Query with UUID
        result = await executor.execute_query("SELECT gen_random_uuid() as id", limit=1)

        assert len(result.rows) == 1
        row = result.rows[0]

        # Verify UUID is string
        assert isinstance(row["id"], str)
        assert len(row["id"]) == 36  # UUID string length

        # Verify full JSON serialization works
        json.dumps(result.model_dump())
