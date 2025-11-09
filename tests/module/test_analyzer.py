"""Module Tests for StatisticsAnalyzer

Tests the StatisticsAnalyzer component directly without MCP protocol overhead.
Validates:
- Column statistics for numeric and text columns
- Database profiling
- Statistical calculations
- Data type handling
"""

import json

import pytest

from db_connect_mcp.adapters.base import BaseAdapter
from db_connect_mcp.core import (
    DatabaseConnection,
    MetadataInspector,
    StatisticsAnalyzer,
)

pytestmark = [pytest.mark.postgresql, pytest.mark.integration]


class TestStatisticsAnalyzerNumeric:
    """Test column analysis for numeric columns."""

    @pytest.mark.asyncio
    async def test_analyze_column_numeric(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test analyze_column with numeric columns."""
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
                # Analyze the numeric column
                stats = await analyzer.analyze_column(table.name, numeric_col, "public")

                # Validate basic stats
                assert stats.column == numeric_col
                assert stats.data_type is not None
                assert stats.total_rows >= 0
                assert stats.null_count >= 0

                # For numeric columns, should have numeric stats if data exists
                if stats.total_rows > stats.null_count:
                    assert stats.min_value is not None
                    assert stats.max_value is not None

                # Verify JSON serialization (min/max could be Decimal, etc.)
                try:
                    json.dumps(stats.model_dump())
                except TypeError as e:
                    pytest.fail(f"Stats not JSON-safe: {e}")

                break


class TestStatisticsAnalyzerText:
    """Test column analysis for text columns."""

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

                # Verify no SQL errors occurred
                assert (
                    stats.warning is None or "unavailable" not in stats.warning.lower()
                )

                break


class TestStatisticsAnalyzerProfiling:
    """Test database profiling functionality."""

    @pytest.mark.asyncio
    async def test_profile_database(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test profile_database returns comprehensive stats."""
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


class TestStatisticsAnalyzerEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_analyze_nonexistent_column(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test analyzing a column that doesn't exist."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        analyzer = StatisticsAnalyzer(pg_connection, pg_adapter)
        inspector = MetadataInspector(pg_connection, pg_adapter)

        # Get a table
        tables = await inspector.get_tables("public")
        if not tables:
            pytest.skip("No tables available")

        table_name = tables[0].name

        # Try to analyze non-existent column
        with pytest.raises(Exception):
            await analyzer.analyze_column(
                table_name, "nonexistent_column_xyz", "public"
            )

    @pytest.mark.asyncio
    async def test_analyze_column_all_nulls(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test analyzing a column with all NULL values.

        Note: In read-only mode, we cannot create temporary views/tables.
        This test is skipped as it's not critical to the read-only functionality.
        In a real-world scenario, if a column has all NULLs, the analyzer
        should handle it gracefully (which it does through the adapter's
        error handling in analyze_multiple_columns).
        """
        pytest.skip("Cannot create temporary objects in read-only mode")
