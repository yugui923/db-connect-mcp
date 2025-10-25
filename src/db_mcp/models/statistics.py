"""Column statistics and distribution models."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class Distribution(BaseModel):
    """Value distribution for a column."""

    column: str = Field(..., description="Column name")
    total_rows: int = Field(..., description="Total rows analyzed")
    unique_values: int = Field(..., description="Number of unique values")
    null_count: int = Field(..., description="Number of NULL values")
    top_values: list[dict[str, Any]] = Field(
        ..., description="Top N most frequent values with counts"
    )
    sample_size: int = Field(..., description="Number of rows sampled")

    @property
    def null_percentage(self) -> float:
        """Percentage of NULL values."""
        if self.total_rows == 0:
            return 0.0
        return (self.null_count / self.total_rows) * 100

    @property
    def cardinality(self) -> float:
        """Cardinality (unique values / total rows)."""
        if self.total_rows == 0:
            return 0.0
        return self.unique_values / self.total_rows

    @property
    def is_high_cardinality(self) -> bool:
        """Check if column has high cardinality (>0.9)."""
        return self.cardinality > 0.9

    @property
    def is_low_cardinality(self) -> bool:
        """Check if column has low cardinality (<0.1)."""
        return self.cardinality < 0.1


class ColumnStats(BaseModel):
    """Statistical information about a column."""

    column: str = Field(..., description="Column name")
    data_type: str = Field(..., description="Column data type")
    total_rows: int = Field(..., description="Total rows in table")
    null_count: int = Field(..., description="Number of NULL values")
    distinct_count: Optional[int] = Field(None, description="Number of distinct values")
    min_value: Optional[Any] = Field(None, description="Minimum value")
    max_value: Optional[Any] = Field(None, description="Maximum value")
    avg_value: Optional[float] = Field(
        None, description="Average value (numeric columns)"
    )
    median_value: Optional[Any] = Field(None, description="Median value")
    stddev_value: Optional[float] = Field(None, description="Standard deviation")
    percentile_25: Optional[Any] = Field(None, description="25th percentile")
    percentile_75: Optional[Any] = Field(None, description="75th percentile")
    percentile_95: Optional[Any] = Field(None, description="95th percentile")
    percentile_99: Optional[Any] = Field(None, description="99th percentile")
    most_common_values: list[dict[str, Any]] = Field(
        default_factory=list, description="Most common values with frequencies"
    )
    sample_size: int = Field(..., description="Number of rows sampled for statistics")
    warning: Optional[str] = Field(
        None, description="Warning message if stats unavailable"
    )

    @property
    def null_percentage(self) -> float:
        """Percentage of NULL values."""
        if self.total_rows == 0:
            return 0.0
        return (self.null_count / self.total_rows) * 100

    @property
    def completeness(self) -> float:
        """Data completeness (1 - null percentage as decimal)."""
        return 1.0 - (self.null_percentage / 100.0)

    @property
    def cardinality(self) -> Optional[float]:
        """Cardinality ratio (distinct / total)."""
        if self.distinct_count is None or self.total_rows == 0:
            return None
        return self.distinct_count / self.total_rows

    @property
    def has_advanced_stats(self) -> bool:
        """Check if advanced statistics are available."""
        return any(
            [
                self.median_value is not None,
                self.percentile_25 is not None,
                self.stddev_value is not None,
            ]
        )

    @property
    def is_numeric(self) -> bool:
        """Check if column appears to be numeric based on available stats."""
        return self.avg_value is not None or self.stddev_value is not None

    @property
    def range_value(self) -> Optional[Any]:
        """Calculate range (max - min) for numeric columns."""
        if self.min_value is not None and self.max_value is not None:
            try:
                return self.max_value - self.min_value
            except (TypeError, ValueError):
                return None
        return None

    def get_quality_score(self) -> float:
        """
        Calculate data quality score (0-100).
        Based on completeness, cardinality, and availability of stats.
        """
        score = 0.0

        # Completeness (0-40 points)
        score += self.completeness * 40

        # Has distinct count (10 points)
        if self.distinct_count is not None:
            score += 10

        # Has min/max (10 points)
        if self.min_value is not None and self.max_value is not None:
            score += 10

        # Has advanced stats (20 points)
        if self.has_advanced_stats:
            score += 20

        # Has most common values (10 points)
        if self.most_common_values:
            score += 10

        # Has average (10 points if numeric)
        if self.avg_value is not None:
            score += 10

        return min(score, 100.0)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "column": "age",
                    "data_type": "integer",
                    "total_rows": 10000,
                    "null_count": 50,
                    "distinct_count": 95,
                    "min_value": 18,
                    "max_value": 95,
                    "avg_value": 42.5,
                    "median_value": 41,
                    "stddev_value": 15.2,
                    "percentile_25": 30,
                    "percentile_75": 55,
                    "percentile_95": 72,
                    "percentile_99": 85,
                    "most_common_values": [
                        {"value": 35, "count": 250},
                        {"value": 42, "count": 230},
                    ],
                    "sample_size": 10000,
                    "warning": None,
                }
            ]
        }
    }
