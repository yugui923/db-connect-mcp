"""Unit tests for StatisticsAnalyzer with mocked connections."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from db_connect_mcp.core.analyzer import StatisticsAnalyzer
from db_connect_mcp.models.statistics import ColumnStats, Distribution


class TestStatisticsAnalyzerInit:
    """Tests for StatisticsAnalyzer initialization."""

    def test_initialization(self):
        """Test analyzer initialization stores connection and adapter."""
        mock_connection = MagicMock()
        mock_adapter = MagicMock()

        analyzer = StatisticsAnalyzer(mock_connection, mock_adapter)

        assert analyzer.connection is mock_connection
        assert analyzer.adapter is mock_adapter


class TestAnalyzeColumn:
    """Tests for analyze_column method."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock connection with async context manager."""
        mock_conn = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_cm.__aexit__.return_value = None

        connection = MagicMock()
        connection.get_connection.return_value = mock_cm
        return connection, mock_conn

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock adapter."""
        adapter = MagicMock()
        adapter.get_column_statistics = AsyncMock()
        adapter.get_value_distribution = AsyncMock()
        return adapter

    @pytest.mark.asyncio
    async def test_analyze_column_delegates_to_adapter(
        self, mock_connection, mock_adapter
    ):
        """Test that analyze_column delegates to adapter."""
        connection, mock_conn = mock_connection
        expected_stats = ColumnStats(
            column="test_col",
            data_type="integer",
            total_rows=100,
            null_count=5,
            sample_size=100,
        )
        mock_adapter.get_column_statistics.return_value = expected_stats

        analyzer = StatisticsAnalyzer(connection, mock_adapter)
        result = await analyzer.analyze_column("test_table", "test_col", "public")

        assert result == expected_stats
        mock_adapter.get_column_statistics.assert_called_once_with(
            mock_conn, "test_table", "test_col", "public"
        )

    @pytest.mark.asyncio
    async def test_analyze_column_without_schema(self, mock_connection, mock_adapter):
        """Test analyze_column with schema=None."""
        connection, mock_conn = mock_connection
        expected_stats = ColumnStats(
            column="name",
            data_type="varchar",
            total_rows=50,
            null_count=0,
            sample_size=50,
        )
        mock_adapter.get_column_statistics.return_value = expected_stats

        analyzer = StatisticsAnalyzer(connection, mock_adapter)
        result = await analyzer.analyze_column("users", "name")

        assert result == expected_stats
        mock_adapter.get_column_statistics.assert_called_once_with(
            mock_conn, "users", "name", None
        )


class TestGetValueDistribution:
    """Tests for get_value_distribution method."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock connection with async context manager."""
        mock_conn = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_cm.__aexit__.return_value = None

        connection = MagicMock()
        connection.get_connection.return_value = mock_cm
        return connection, mock_conn

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock adapter."""
        adapter = MagicMock()
        adapter.get_value_distribution = AsyncMock()
        return adapter

    @pytest.mark.asyncio
    async def test_get_value_distribution_delegates_to_adapter(
        self, mock_connection, mock_adapter
    ):
        """Test that get_value_distribution delegates to adapter."""
        connection, mock_conn = mock_connection
        expected_dist = Distribution(
            column="status",
            total_rows=100,
            unique_values=3,
            null_count=0,
            top_values=[
                {"value": "active", "count": 50},
                {"value": "inactive", "count": 30},
                {"value": "pending", "count": 20},
            ],
            sample_size=100,
        )
        mock_adapter.get_value_distribution.return_value = expected_dist

        analyzer = StatisticsAnalyzer(connection, mock_adapter)
        result = await analyzer.get_value_distribution(
            "users", "status", "public", limit=10
        )

        assert result == expected_dist
        mock_adapter.get_value_distribution.assert_called_once_with(
            mock_conn, "users", "status", "public", 10
        )

    @pytest.mark.asyncio
    async def test_get_value_distribution_default_limit(
        self, mock_connection, mock_adapter
    ):
        """Test get_value_distribution uses default limit of 20."""
        connection, mock_conn = mock_connection
        expected_dist = Distribution(
            column="category",
            total_rows=1000,
            unique_values=50,
            null_count=0,
            top_values=[],
            sample_size=1000,
        )
        mock_adapter.get_value_distribution.return_value = expected_dist

        analyzer = StatisticsAnalyzer(connection, mock_adapter)
        await analyzer.get_value_distribution("products", "category")

        mock_adapter.get_value_distribution.assert_called_once_with(
            mock_conn, "products", "category", None, 20
        )


class TestAnalyzeMultipleColumns:
    """Tests for analyze_multiple_columns method."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock connection with async context manager."""
        mock_conn = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_cm.__aexit__.return_value = None

        connection = MagicMock()
        connection.get_connection.return_value = mock_cm
        return connection, mock_conn

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock adapter."""
        adapter = MagicMock()
        adapter.get_column_statistics = AsyncMock()
        return adapter

    @pytest.mark.asyncio
    async def test_analyze_multiple_columns_success(
        self, mock_connection, mock_adapter
    ):
        """Test analyzing multiple columns successfully."""
        connection, mock_conn = mock_connection
        stats1 = ColumnStats(
            column="id",
            data_type="integer",
            total_rows=100,
            null_count=0,
            sample_size=100,
        )
        stats2 = ColumnStats(
            column="name",
            data_type="varchar",
            total_rows=100,
            null_count=5,
            sample_size=100,
        )
        mock_adapter.get_column_statistics.side_effect = [stats1, stats2]

        analyzer = StatisticsAnalyzer(connection, mock_adapter)
        results = await analyzer.analyze_multiple_columns(
            "users", ["id", "name"], "public"
        )

        assert len(results) == 2
        assert results[0] == stats1
        assert results[1] == stats2

    @pytest.mark.asyncio
    async def test_analyze_multiple_columns_with_error(
        self, mock_connection, mock_adapter
    ):
        """Test that errors are handled gracefully for individual columns."""
        connection, mock_conn = mock_connection
        stats1 = ColumnStats(
            column="id",
            data_type="integer",
            total_rows=100,
            null_count=0,
            sample_size=100,
        )
        # Second column fails
        mock_adapter.get_column_statistics.side_effect = [
            stats1,
            Exception("Column not found"),
        ]

        analyzer = StatisticsAnalyzer(connection, mock_adapter)
        results = await analyzer.analyze_multiple_columns(
            "users", ["id", "nonexistent"], "public"
        )

        assert len(results) == 2
        assert results[0] == stats1
        # Second result should have error info
        assert results[1].column == "nonexistent"
        assert results[1].data_type == "unknown"
        assert results[1].total_rows == 0
        assert results[1].warning is not None
        assert "Failed to analyze" in results[1].warning
        assert "Column not found" in results[1].warning

    @pytest.mark.asyncio
    async def test_analyze_multiple_columns_all_errors(
        self, mock_connection, mock_adapter
    ):
        """Test when all columns fail to analyze."""
        connection, mock_conn = mock_connection
        mock_adapter.get_column_statistics.side_effect = [
            Exception("Error 1"),
            Exception("Error 2"),
        ]

        analyzer = StatisticsAnalyzer(connection, mock_adapter)
        results = await analyzer.analyze_multiple_columns(
            "users", ["col1", "col2"], "public"
        )

        assert len(results) == 2
        for i, result in enumerate(results):
            assert result.data_type == "unknown"
            assert result.warning is not None
            assert f"Error {i + 1}" in result.warning

    @pytest.mark.asyncio
    async def test_analyze_multiple_columns_empty_list(
        self, mock_connection, mock_adapter
    ):
        """Test analyzing empty column list."""
        connection, _ = mock_connection

        analyzer = StatisticsAnalyzer(connection, mock_adapter)
        results = await analyzer.analyze_multiple_columns("users", [], "public")

        assert results == []
        mock_adapter.get_column_statistics.assert_not_called()
