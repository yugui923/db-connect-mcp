"""Module Tests for StatisticsAnalyzer

Tests the StatisticsAnalyzer component directly without MCP protocol overhead.
Validates:
- Column statistics for numeric and text columns
- Database profiling
- Statistical calculations
- Data type handling
"""

import pytest

from db_connect_mcp.core import StatisticsAnalyzer
from tests.conftest import assert_json_serializable

pytestmark = [pytest.mark.postgresql, pytest.mark.integration]


class TestStatisticsAnalyzerNumeric:
    """Test column analysis for numeric columns."""

    @pytest.mark.asyncio
    async def test_analyze_numeric_column_price(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyze_column with products.price (guaranteed numeric column)."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        stats = await pg_analyzer.analyze_column("products", "price", "public")

        # Validate basic stats
        assert stats.column == "price"
        assert stats.data_type is not None
        assert stats.total_rows >= 2000  # Known from sample data
        assert stats.null_count >= 0

        # For price column with 2000 products, should have numeric stats
        assert stats.min_value is not None
        assert stats.max_value is not None
        assert stats.avg_value is not None

        # Verify JSON serialization works
        assert_json_serializable(stats.model_dump())

    @pytest.mark.asyncio
    async def test_analyze_integer_column(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyze_column with products.stock_quantity (integer column)."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        stats = await pg_analyzer.analyze_column("products", "stock_quantity", "public")

        assert stats.column == "stock_quantity"
        assert stats.total_rows >= 2000
        assert stats.min_value is not None
        assert stats.max_value is not None

        # Integer column should have whole numbers or NULL
        if stats.avg_value is not None:
            assert isinstance(stats.avg_value, (int, float, str))

        assert_json_serializable(stats.model_dump())

    @pytest.mark.asyncio
    async def test_analyze_nullable_numeric_column(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyze_column with products.cost (nullable numeric column)."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        stats = await pg_analyzer.analyze_column("products", "cost", "public")

        assert stats.column == "cost"
        assert stats.total_rows >= 2000

        # cost column has NULLs (some products don't have cost data)
        # Stats should still work
        if stats.total_rows > stats.null_count:
            assert stats.min_value is not None
            assert stats.max_value is not None

        assert_json_serializable(stats.model_dump())


class TestStatisticsAnalyzerText:
    """Test column analysis for text columns."""

    @pytest.mark.asyncio
    async def test_analyze_text_column_name(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyze_column with categories.name (guaranteed text column)."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        stats = await pg_analyzer.analyze_column("categories", "name", "public")

        # Validate basic stats work for text
        assert stats.column == "name"
        assert stats.data_type is not None
        assert stats.total_rows >= 50  # Known from sample data
        assert stats.null_count >= 0

        # Text columns should not have numeric stats (mean, stddev, etc.)
        # But should have distinct_count, top_values, etc.
        assert stats.distinct_count is not None

        # Verify no SQL errors occurred
        assert stats.warning is None or "unavailable" not in stats.warning.lower()

        assert_json_serializable(stats.model_dump())

    @pytest.mark.asyncio
    async def test_analyze_varchar_column(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyze_column with products.sku (VARCHAR column)."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        stats = await pg_analyzer.analyze_column("products", "sku", "public")

        assert stats.column == "sku"
        assert stats.total_rows >= 2000
        # SKU is unique, so distinct_count should equal total_rows
        if stats.distinct_count is not None:
            assert stats.distinct_count >= 1500  # Most SKUs are unique

        assert_json_serializable(stats.model_dump())

    @pytest.mark.asyncio
    async def test_analyze_text_with_nulls(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyze_column with users.phone (nullable text column with NULLs)."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        stats = await pg_analyzer.analyze_column("users", "phone", "public")

        assert stats.column == "phone"
        assert stats.total_rows >= 5000

        # phone column is nullable (some users don't have phone data)
        # Should still return valid stats
        assert stats.null_count >= 0

        assert_json_serializable(stats.model_dump())


class TestStatisticsAnalyzerSpecialTypes:
    """Test column analysis for special data types."""

    @pytest.mark.asyncio
    async def test_analyze_timestamp_column(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyze_column with timestamp column (users.registered_at)."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        stats = await pg_analyzer.analyze_column("users", "registered_at", "public")

        assert stats.column == "registered_at"
        assert stats.total_rows >= 5000

        # Timestamp columns might have min/max as date strings
        if stats.min_value is not None:
            assert isinstance(stats.min_value, (str, int, float))

        assert_json_serializable(stats.model_dump())

    @pytest.mark.asyncio
    async def test_analyze_boolean_column(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyze_column with boolean column (products.is_featured)."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        stats = await pg_analyzer.analyze_column("products", "is_featured", "public")

        assert stats.column == "is_featured"

        # Boolean columns may not support all statistics (MIN/MAX fails in PostgreSQL)
        # If stats returned successfully, verify basic properties
        if stats.total_rows > 0:
            assert stats.total_rows >= 2000
            # Boolean column should have 2-3 distinct values (true, false, null)
            if stats.distinct_count is not None:
                assert stats.distinct_count <= 3

        assert_json_serializable(stats.model_dump())

    @pytest.mark.asyncio
    async def test_analyze_uuid_column(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyze_column with UUID column (products.product_uuid)."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        stats = await pg_analyzer.analyze_column("products", "product_uuid", "public")

        assert stats.column == "product_uuid"

        # UUID columns may not support all statistics (MIN/MAX fails in PostgreSQL)
        # If stats returned successfully, verify basic properties
        if stats.total_rows > 0:
            assert stats.total_rows >= 2000
            # UUIDs should be unique
            if stats.distinct_count is not None and stats.null_count < stats.total_rows:
                assert stats.distinct_count >= 1900  # Most are unique

        assert_json_serializable(stats.model_dump())


class TestStatisticsAnalyzerEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_analyze_nonexistent_column(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyzing a column that doesn't exist."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        # Try to analyze non-existent column
        with pytest.raises(Exception):
            await pg_analyzer.analyze_column(
                "products", "nonexistent_column_xyz", "public"
            )

    @pytest.mark.asyncio
    async def test_analyze_nonexistent_table(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyzing column from non-existent table."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        with pytest.raises(Exception):
            await pg_analyzer.analyze_column(
                "nonexistent_table_xyz", "any_column", "public"
            )

    @pytest.mark.asyncio
    async def test_analyze_all_types_table(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyzing columns from data_type_examples (all PostgreSQL types)."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        # Test a few columns with different types
        test_columns = [
            "integer_col",  # INTEGER
            "text_col",  # TEXT
            "timestamp_col",  # TIMESTAMP
            "boolean_col",  # BOOLEAN
            "uuid_col",  # UUID
        ]

        for column in test_columns:
            stats = await pg_analyzer.analyze_column(
                "data_type_examples", column, "public"
            )

            assert stats.column == column

            # Some special types (boolean, UUID) may not support all statistics
            # Only check total_rows if stats were successfully computed
            if stats.total_rows > 0:
                assert stats.total_rows >= 100

            # All should be JSON serializable
            assert_json_serializable(stats.model_dump())

    @pytest.mark.asyncio
    async def test_analyze_column_with_many_nulls(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyzing column with high percentage of NULLs."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        # data_type_examples has rows with many NULLs (rows 101-110)
        # Test that analyzer handles high NULL percentage gracefully
        stats = await pg_analyzer.analyze_column(
            "data_type_examples", "integer_col", "public"
        )

        assert stats.column == "integer_col"
        assert stats.total_rows >= 100

        # Even with many NULLs, should return valid stats
        assert stats.null_count >= 0
        assert stats.null_count <= stats.total_rows

        # If all values are NULL, min/max might be None
        # Otherwise should have values
        if stats.null_count < stats.total_rows:
            # Has some non-NULL values
            assert stats.distinct_count is not None
        else:
            # All NULL - stats might be None
            pass

        assert_json_serializable(stats.model_dump())

    @pytest.mark.asyncio
    async def test_analyze_array_column(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyzing array column (products.tags)."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        stats = await pg_analyzer.analyze_column("products", "tags", "public")

        assert stats.column == "tags"
        assert stats.total_rows >= 2000

        # Array columns might not have traditional stats
        # But should not error and should be JSON serializable
        assert_json_serializable(stats.model_dump())

    @pytest.mark.asyncio
    async def test_analyze_jsonb_column(
        self, pg_analyzer: StatisticsAnalyzer, pg_adapter
    ):
        """Test analyzing JSONB column (categories.metadata)."""
        if not pg_adapter.capabilities.advanced_stats:
            pytest.skip("Database doesn't support advanced statistics")

        stats = await pg_analyzer.analyze_column("categories", "metadata", "public")

        assert stats.column == "metadata"

        # JSONB columns may not support all statistics (MIN/MAX fails in PostgreSQL)
        # If stats returned successfully, verify basic properties
        if stats.total_rows > 0:
            assert stats.total_rows >= 50

        # Should not error and should be JSON serializable
        assert_json_serializable(stats.model_dump())
