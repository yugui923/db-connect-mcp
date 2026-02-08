"""Tests for column statistics and distribution models."""

import pytest

from db_connect_mcp.models.statistics import ColumnStats, Distribution


class TestDistribution:
    """Tests for Distribution model."""

    def test_basic_creation(self):
        """Test creating a distribution with required fields."""
        dist = Distribution(
            column="status",
            total_rows=1000,
            unique_values=5,
            null_count=10,
            top_values=[{"value": "active", "count": 500}],
            sample_size=1000,
        )
        assert dist.column == "status"
        assert dist.total_rows == 1000
        assert dist.unique_values == 5
        assert dist.null_count == 10
        assert len(dist.top_values) == 1
        assert dist.sample_size == 1000

    def test_null_percentage_with_nulls(self):
        """Test null_percentage calculation with null values."""
        dist = Distribution(
            column="status",
            total_rows=100,
            unique_values=5,
            null_count=25,
            top_values=[],
            sample_size=100,
        )
        assert dist.null_percentage == 25.0

    def test_null_percentage_no_nulls(self):
        """Test null_percentage when there are no null values."""
        dist = Distribution(
            column="status",
            total_rows=100,
            unique_values=5,
            null_count=0,
            top_values=[],
            sample_size=100,
        )
        assert dist.null_percentage == 0.0

    def test_null_percentage_all_nulls(self):
        """Test null_percentage when all values are null."""
        dist = Distribution(
            column="status",
            total_rows=100,
            unique_values=0,
            null_count=100,
            top_values=[],
            sample_size=100,
        )
        assert dist.null_percentage == 100.0

    def test_null_percentage_zero_rows(self):
        """Test null_percentage with zero total rows."""
        dist = Distribution(
            column="status",
            total_rows=0,
            unique_values=0,
            null_count=0,
            top_values=[],
            sample_size=0,
        )
        assert dist.null_percentage == 0.0

    def test_cardinality_normal(self):
        """Test cardinality calculation with normal data."""
        dist = Distribution(
            column="id",
            total_rows=100,
            unique_values=50,
            null_count=0,
            top_values=[],
            sample_size=100,
        )
        assert dist.cardinality == 0.5

    def test_cardinality_all_unique(self):
        """Test cardinality when all values are unique."""
        dist = Distribution(
            column="id",
            total_rows=100,
            unique_values=100,
            null_count=0,
            top_values=[],
            sample_size=100,
        )
        assert dist.cardinality == 1.0

    def test_cardinality_zero_rows(self):
        """Test cardinality with zero total rows."""
        dist = Distribution(
            column="status",
            total_rows=0,
            unique_values=0,
            null_count=0,
            top_values=[],
            sample_size=0,
        )
        assert dist.cardinality == 0.0

    def test_is_high_cardinality_true(self):
        """Test is_high_cardinality returns True when cardinality > 0.9."""
        dist = Distribution(
            column="id",
            total_rows=100,
            unique_values=95,
            null_count=0,
            top_values=[],
            sample_size=100,
        )
        assert dist.cardinality == 0.95
        assert dist.is_high_cardinality is True

    def test_is_high_cardinality_false(self):
        """Test is_high_cardinality returns False when cardinality <= 0.9."""
        dist = Distribution(
            column="status",
            total_rows=100,
            unique_values=50,
            null_count=0,
            top_values=[],
            sample_size=100,
        )
        assert dist.cardinality == 0.5
        assert dist.is_high_cardinality is False

    def test_is_high_cardinality_boundary(self):
        """Test is_high_cardinality at boundary (0.9)."""
        dist = Distribution(
            column="id",
            total_rows=100,
            unique_values=90,
            null_count=0,
            top_values=[],
            sample_size=100,
        )
        assert dist.cardinality == 0.9
        assert dist.is_high_cardinality is False  # Not > 0.9

    def test_is_low_cardinality_true(self):
        """Test is_low_cardinality returns True when cardinality < 0.1."""
        dist = Distribution(
            column="status",
            total_rows=100,
            unique_values=5,
            null_count=0,
            top_values=[],
            sample_size=100,
        )
        assert dist.cardinality == 0.05
        assert dist.is_low_cardinality is True

    def test_is_low_cardinality_false(self):
        """Test is_low_cardinality returns False when cardinality >= 0.1."""
        dist = Distribution(
            column="status",
            total_rows=100,
            unique_values=50,
            null_count=0,
            top_values=[],
            sample_size=100,
        )
        assert dist.cardinality == 0.5
        assert dist.is_low_cardinality is False

    def test_is_low_cardinality_boundary(self):
        """Test is_low_cardinality at boundary (0.1)."""
        dist = Distribution(
            column="status",
            total_rows=100,
            unique_values=10,
            null_count=0,
            top_values=[],
            sample_size=100,
        )
        assert dist.cardinality == 0.1
        assert dist.is_low_cardinality is False  # Not < 0.1


class TestColumnStats:
    """Tests for ColumnStats model."""

    @pytest.fixture
    def minimal_stats(self):
        """Create minimal column stats for testing."""
        return ColumnStats(
            column="test_col",
            data_type="integer",
            total_rows=100,
            null_count=10,
            sample_size=100,
        )

    @pytest.fixture
    def full_numeric_stats(self):
        """Create full numeric column stats for testing."""
        return ColumnStats(
            column="age",
            data_type="integer",
            total_rows=1000,
            null_count=50,
            distinct_count=80,
            min_value=18,
            max_value=95,
            avg_value=42.5,
            median_value=40,
            stddev_value=15.2,
            percentile_25=30,
            percentile_75=55,
            percentile_95=72,
            percentile_99=85,
            most_common_values=[
                {"value": 35, "count": 50},
                {"value": 42, "count": 45},
            ],
            sample_size=1000,
        )

    def test_null_percentage_with_nulls(self, minimal_stats):
        """Test null_percentage calculation."""
        assert minimal_stats.null_percentage == 10.0

    def test_null_percentage_no_nulls(self):
        """Test null_percentage when there are no null values."""
        stats = ColumnStats(
            column="id",
            data_type="integer",
            total_rows=100,
            null_count=0,
            sample_size=100,
        )
        assert stats.null_percentage == 0.0

    def test_null_percentage_all_nulls(self):
        """Test null_percentage when all values are null."""
        stats = ColumnStats(
            column="notes",
            data_type="text",
            total_rows=100,
            null_count=100,
            sample_size=100,
        )
        assert stats.null_percentage == 100.0

    def test_null_percentage_zero_rows(self):
        """Test null_percentage with zero total rows."""
        stats = ColumnStats(
            column="empty",
            data_type="integer",
            total_rows=0,
            null_count=0,
            sample_size=0,
        )
        assert stats.null_percentage == 0.0

    def test_completeness_full(self):
        """Test completeness when there are no null values."""
        stats = ColumnStats(
            column="id",
            data_type="integer",
            total_rows=100,
            null_count=0,
            sample_size=100,
        )
        assert stats.completeness == 1.0

    def test_completeness_partial(self):
        """Test completeness with some null values."""
        stats = ColumnStats(
            column="notes",
            data_type="text",
            total_rows=100,
            null_count=25,
            sample_size=100,
        )
        assert stats.completeness == 0.75

    def test_completeness_empty(self):
        """Test completeness when all values are null."""
        stats = ColumnStats(
            column="notes",
            data_type="text",
            total_rows=100,
            null_count=100,
            sample_size=100,
        )
        assert stats.completeness == 0.0

    def test_cardinality_with_distinct_count(self):
        """Test cardinality calculation with distinct_count."""
        stats = ColumnStats(
            column="status",
            data_type="text",
            total_rows=100,
            null_count=0,
            distinct_count=5,
            sample_size=100,
        )
        assert stats.cardinality == 0.05

    def test_cardinality_without_distinct_count(self):
        """Test cardinality returns None when distinct_count is None."""
        stats = ColumnStats(
            column="status",
            data_type="text",
            total_rows=100,
            null_count=0,
            sample_size=100,
        )
        assert stats.cardinality is None

    def test_cardinality_zero_rows(self):
        """Test cardinality returns None when total_rows is 0."""
        stats = ColumnStats(
            column="status",
            data_type="text",
            total_rows=0,
            null_count=0,
            distinct_count=5,
            sample_size=0,
        )
        assert stats.cardinality is None

    def test_has_advanced_stats_with_median(self):
        """Test has_advanced_stats returns True when median is present."""
        stats = ColumnStats(
            column="age",
            data_type="integer",
            total_rows=100,
            null_count=0,
            median_value=42,
            sample_size=100,
        )
        assert stats.has_advanced_stats is True

    def test_has_advanced_stats_with_percentile(self):
        """Test has_advanced_stats returns True when percentile_25 is present."""
        stats = ColumnStats(
            column="age",
            data_type="integer",
            total_rows=100,
            null_count=0,
            percentile_25=30,
            sample_size=100,
        )
        assert stats.has_advanced_stats is True

    def test_has_advanced_stats_with_stddev(self):
        """Test has_advanced_stats returns True when stddev_value is present."""
        stats = ColumnStats(
            column="age",
            data_type="integer",
            total_rows=100,
            null_count=0,
            stddev_value=15.2,
            sample_size=100,
        )
        assert stats.has_advanced_stats is True

    def test_has_advanced_stats_false(self):
        """Test has_advanced_stats returns False when no advanced stats."""
        stats = ColumnStats(
            column="age",
            data_type="integer",
            total_rows=100,
            null_count=0,
            sample_size=100,
        )
        assert stats.has_advanced_stats is False

    def test_is_numeric_with_avg(self):
        """Test is_numeric returns True when avg_value is present."""
        stats = ColumnStats(
            column="price",
            data_type="decimal",
            total_rows=100,
            null_count=0,
            avg_value=99.99,
            sample_size=100,
        )
        assert stats.is_numeric is True

    def test_is_numeric_with_stddev(self):
        """Test is_numeric returns True when stddev_value is present."""
        stats = ColumnStats(
            column="price",
            data_type="decimal",
            total_rows=100,
            null_count=0,
            stddev_value=25.0,
            sample_size=100,
        )
        assert stats.is_numeric is True

    def test_is_numeric_false(self):
        """Test is_numeric returns False for non-numeric columns."""
        stats = ColumnStats(
            column="name",
            data_type="text",
            total_rows=100,
            null_count=0,
            sample_size=100,
        )
        assert stats.is_numeric is False

    def test_range_value_numeric(self):
        """Test range_value calculation for numeric columns."""
        stats = ColumnStats(
            column="age",
            data_type="integer",
            total_rows=100,
            null_count=0,
            min_value=18,
            max_value=95,
            sample_size=100,
        )
        assert stats.range_value == 77

    def test_range_value_float(self):
        """Test range_value calculation for float columns."""
        stats = ColumnStats(
            column="price",
            data_type="decimal",
            total_rows=100,
            null_count=0,
            min_value=10.50,
            max_value=99.99,
            sample_size=100,
        )
        assert stats.range_value == pytest.approx(89.49)

    def test_range_value_no_min(self):
        """Test range_value returns None when min_value is None."""
        stats = ColumnStats(
            column="age",
            data_type="integer",
            total_rows=100,
            null_count=0,
            max_value=95,
            sample_size=100,
        )
        assert stats.range_value is None

    def test_range_value_no_max(self):
        """Test range_value returns None when max_value is None."""
        stats = ColumnStats(
            column="age",
            data_type="integer",
            total_rows=100,
            null_count=0,
            min_value=18,
            sample_size=100,
        )
        assert stats.range_value is None

    def test_range_value_non_numeric_types(self):
        """Test range_value returns None for non-subtractable types."""
        stats = ColumnStats(
            column="name",
            data_type="text",
            total_rows=100,
            null_count=0,
            min_value="aardvark",
            max_value="zebra",
            sample_size=100,
        )
        assert stats.range_value is None

    def test_get_quality_score_minimal(self):
        """Test quality score with minimal stats."""
        stats = ColumnStats(
            column="test",
            data_type="integer",
            total_rows=100,
            null_count=0,  # 100% completeness -> 40 points
            sample_size=100,
        )
        # Only completeness: 1.0 * 40 = 40 points
        assert stats.get_quality_score() == 40.0

    def test_get_quality_score_with_nulls(self):
        """Test quality score with null values affects completeness."""
        stats = ColumnStats(
            column="test",
            data_type="integer",
            total_rows=100,
            null_count=50,  # 50% completeness -> 20 points
            sample_size=100,
        )
        assert stats.get_quality_score() == 20.0

    def test_get_quality_score_with_distinct_count(self):
        """Test quality score includes distinct_count bonus."""
        stats = ColumnStats(
            column="test",
            data_type="integer",
            total_rows=100,
            null_count=0,  # 40 points
            distinct_count=50,  # +10 points
            sample_size=100,
        )
        assert stats.get_quality_score() == 50.0

    def test_get_quality_score_with_min_max(self):
        """Test quality score includes min/max bonus."""
        stats = ColumnStats(
            column="test",
            data_type="integer",
            total_rows=100,
            null_count=0,  # 40 points
            min_value=1,
            max_value=100,  # +10 points
            sample_size=100,
        )
        assert stats.get_quality_score() == 50.0

    def test_get_quality_score_with_advanced_stats(self):
        """Test quality score includes advanced stats bonus."""
        stats = ColumnStats(
            column="test",
            data_type="integer",
            total_rows=100,
            null_count=0,  # 40 points
            median_value=50,  # triggers has_advanced_stats -> +20 points
            sample_size=100,
        )
        assert stats.get_quality_score() == 60.0

    def test_get_quality_score_with_most_common(self):
        """Test quality score includes most_common_values bonus."""
        stats = ColumnStats(
            column="test",
            data_type="integer",
            total_rows=100,
            null_count=0,  # 40 points
            most_common_values=[{"value": 1, "count": 50}],  # +10 points
            sample_size=100,
        )
        assert stats.get_quality_score() == 50.0

    def test_get_quality_score_with_avg(self):
        """Test quality score includes avg_value bonus."""
        stats = ColumnStats(
            column="test",
            data_type="integer",
            total_rows=100,
            null_count=0,  # 40 points
            avg_value=50.0,  # +10 points
            sample_size=100,
        )
        assert stats.get_quality_score() == 50.0

    def test_get_quality_score_full(self, full_numeric_stats):
        """Test quality score with all stats present."""
        # completeness: 95% (950/1000) -> 38 points
        # distinct_count: 10 points
        # min/max: 10 points
        # advanced_stats (median, stddev, percentile_25): 20 points
        # most_common_values: 10 points
        # avg_value: 10 points
        # Total: 38 + 10 + 10 + 20 + 10 + 10 = 98 points
        score = full_numeric_stats.get_quality_score()
        assert score == pytest.approx(98.0)

    def test_get_quality_score_capped_at_100(self):
        """Test quality score is capped at 100."""
        # Create stats that would theoretically exceed 100
        stats = ColumnStats(
            column="test",
            data_type="integer",
            total_rows=100,
            null_count=0,  # 40 points
            distinct_count=50,  # 10 points
            min_value=1,
            max_value=100,  # 10 points
            avg_value=50.0,  # 10 points
            median_value=50,
            stddev_value=10.0,
            percentile_25=25,  # 20 points (advanced)
            most_common_values=[{"value": 1, "count": 50}],  # 10 points
            sample_size=100,
        )
        # Total would be 100 points, verify it's capped
        assert stats.get_quality_score() == 100.0

    def test_full_stats_properties(self, full_numeric_stats):
        """Test all properties on a fully populated stats object."""
        assert full_numeric_stats.null_percentage == 5.0
        assert full_numeric_stats.completeness == 0.95
        assert full_numeric_stats.cardinality == 0.08
        assert full_numeric_stats.has_advanced_stats is True
        assert full_numeric_stats.is_numeric is True
        assert full_numeric_stats.range_value == 77
