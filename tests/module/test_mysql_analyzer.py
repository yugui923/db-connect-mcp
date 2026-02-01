"""Module Tests for MySQL StatisticsAnalyzer (via SSH Tunnel)

Tests the StatisticsAnalyzer component with MySQL accessed through SSH tunnel.
Validates:
- Column profiling and statistics
- Value distribution analysis
"""

import pytest

from db_connect_mcp.core import StatisticsAnalyzer
from tests.conftest import assert_json_serializable

pytestmark = [pytest.mark.mysql, pytest.mark.ssh_tunnel]


class TestMySQLAnalyzerNumeric:
    """Test numeric column analysis on MySQL."""

    @pytest.mark.asyncio
    async def test_analyze_numeric_column(self, mysql_analyzer: StatisticsAnalyzer):
        """Test analyzing a numeric column (price)."""
        stats = await mysql_analyzer.analyze_column("products", "price", "testdb")

        assert stats is not None
        assert stats.column == "price"
        assert stats.total_rows > 0
        assert stats.distinct_count is not None
        assert stats.distinct_count > 0

    @pytest.mark.asyncio
    async def test_analyze_numeric_serializable(self, mysql_analyzer: StatisticsAnalyzer):
        """Test that numeric analysis results are JSON serializable."""
        stats = await mysql_analyzer.analyze_column("products", "price", "testdb")
        assert_json_serializable(stats.model_dump())


class TestMySQLAnalyzerText:
    """Test text column analysis on MySQL."""

    @pytest.mark.asyncio
    async def test_analyze_text_column(self, mysql_analyzer: StatisticsAnalyzer):
        """Test analyzing a text column (name)."""
        stats = await mysql_analyzer.analyze_column("products", "name", "testdb")

        assert stats is not None
        assert stats.column == "name"
        assert stats.total_rows > 0

    @pytest.mark.asyncio
    async def test_analyze_email_column(self, mysql_analyzer: StatisticsAnalyzer):
        """Test analyzing email column from users table."""
        stats = await mysql_analyzer.analyze_column("users", "email", "testdb")

        assert stats is not None
        assert stats.total_rows > 0
        assert stats.null_count is not None


class TestMySQLAnalyzerEdgeCases:
    """Test edge cases for MySQL analysis."""

    @pytest.mark.asyncio
    async def test_analyze_nonexistent_column(self, mysql_analyzer: StatisticsAnalyzer):
        """Test analyzing a column that doesn't exist returns warning or error."""
        # MySQL adapter may return stats with a warning rather than raising
        stats = await mysql_analyzer.analyze_column("products", "nonexistent_col", "testdb")
        # If it doesn't raise, check for warning or zero results
        assert stats.total_rows == 0 or stats.warning is not None
