"""Module Tests for MySQL StatisticsAnalyzer

Tests both direct and tunneled MySQL access for the StatisticsAnalyzer component.
"""

import pytest

from db_connect_mcp.core import StatisticsAnalyzer
from tests.conftest import assert_json_serializable


# ==================== MySQL Direct ====================


class TestMySQLDirectAnalyzerNumeric:
    """Test numeric column analysis on MySQL direct."""

    pytestmark = [pytest.mark.mysql]

    @pytest.mark.asyncio
    async def test_analyze_numeric_column(self, mysql_analyzer: StatisticsAnalyzer):
        stats = await mysql_analyzer.analyze_column("products", "price", "testdb")
        assert stats is not None
        assert stats.column == "price"
        assert stats.total_rows > 0
        assert stats.distinct_count is not None
        assert stats.distinct_count > 0

    @pytest.mark.asyncio
    async def test_analyze_numeric_serializable(self, mysql_analyzer: StatisticsAnalyzer):
        stats = await mysql_analyzer.analyze_column("products", "price", "testdb")
        assert_json_serializable(stats.model_dump())


class TestMySQLDirectAnalyzerText:
    """Test text column analysis on MySQL direct."""

    pytestmark = [pytest.mark.mysql]

    @pytest.mark.asyncio
    async def test_analyze_text_column(self, mysql_analyzer: StatisticsAnalyzer):
        stats = await mysql_analyzer.analyze_column("products", "name", "testdb")
        assert stats is not None
        assert stats.column == "name"
        assert stats.total_rows > 0

    @pytest.mark.asyncio
    async def test_analyze_email_column(self, mysql_analyzer: StatisticsAnalyzer):
        stats = await mysql_analyzer.analyze_column("users", "email", "testdb")
        assert stats is not None
        assert stats.total_rows > 0


class TestMySQLDirectAnalyzerEdgeCases:
    """Test edge cases for MySQL direct analysis."""

    pytestmark = [pytest.mark.mysql]

    @pytest.mark.asyncio
    async def test_analyze_nonexistent_column(self, mysql_analyzer: StatisticsAnalyzer):
        stats = await mysql_analyzer.analyze_column("products", "nonexistent_col", "testdb")
        assert stats.total_rows == 0 or stats.warning is not None


# ==================== MySQL Tunneled ====================


class TestMySQLTunneledAnalyzerNumeric:
    """Test numeric column analysis on MySQL via SSH tunnel."""

    pytestmark = [pytest.mark.mysql, pytest.mark.ssh_tunnel]

    @pytest.mark.asyncio
    async def test_analyze_numeric_column(self, mysql_tunnel_analyzer: StatisticsAnalyzer):
        stats = await mysql_tunnel_analyzer.analyze_column("products", "price", "testdb")
        assert stats is not None
        assert stats.column == "price"
        assert stats.total_rows > 0

    @pytest.mark.asyncio
    async def test_analyze_numeric_serializable(self, mysql_tunnel_analyzer: StatisticsAnalyzer):
        stats = await mysql_tunnel_analyzer.analyze_column("products", "price", "testdb")
        assert_json_serializable(stats.model_dump())


class TestMySQLTunneledAnalyzerText:
    """Test text column analysis on MySQL via SSH tunnel."""

    pytestmark = [pytest.mark.mysql, pytest.mark.ssh_tunnel]

    @pytest.mark.asyncio
    async def test_analyze_text_column(self, mysql_tunnel_analyzer: StatisticsAnalyzer):
        stats = await mysql_tunnel_analyzer.analyze_column("products", "name", "testdb")
        assert stats is not None
        assert stats.column == "name"
        assert stats.total_rows > 0
