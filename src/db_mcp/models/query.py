"""Query execution and explain plan models."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class QueryResult(BaseModel):
    """Result of a query execution."""

    query: str = Field(..., description="Executed SQL query")
    rows: list[dict[str, Any]] = Field(..., description="Result rows as dictionaries")
    row_count: int = Field(..., description="Number of rows returned")
    columns: list[str] = Field(..., description="Column names in order")
    execution_time_ms: Optional[float] = Field(
        None, description="Execution time in milliseconds"
    )
    truncated: bool = Field(
        default=False, description="Whether results were truncated due to limits"
    )
    warning: Optional[str] = Field(None, description="Warning message if applicable")

    @property
    def is_empty(self) -> bool:
        """Check if result set is empty."""
        return self.row_count == 0

    @property
    def column_count(self) -> int:
        """Get number of columns."""
        return len(self.columns)

    def get_column_values(self, column: str) -> list[Any]:
        """Extract all values for a specific column."""
        return [row.get(column) for row in self.rows]

    def to_table_string(self, max_rows: int = 10) -> str:
        """Format result as a simple table string."""
        if self.is_empty:
            return "No rows returned"

        # Header
        result_lines = [" | ".join(self.columns)]
        result_lines.append("-" * len(result_lines[0]))

        # Rows (truncated if needed)
        display_rows = self.rows[:max_rows]
        for row in display_rows:
            values = [str(row.get(col, "NULL")) for col in self.columns]
            result_lines.append(" | ".join(values))

        if len(self.rows) > max_rows:
            result_lines.append(f"... ({self.row_count - max_rows} more rows)")

        return "\n".join(result_lines)


class ExplainPlan(BaseModel):
    """Query execution plan from EXPLAIN."""

    query: str = Field(..., description="Analyzed SQL query")
    plan: str = Field(..., description="Execution plan as formatted string")
    plan_json: Optional[dict[str, Any]] = Field(
        None, description="Execution plan as JSON (if supported)"
    )
    estimated_cost: Optional[float] = Field(None, description="Estimated query cost")
    estimated_rows: Optional[int] = Field(None, description="Estimated rows to process")
    actual_time_ms: Optional[float] = Field(
        None, description="Actual execution time if ANALYZE"
    )
    actual_rows: Optional[int] = Field(
        None, description="Actual rows processed if ANALYZE"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Performance warnings"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Optimization recommendations"
    )

    @property
    def has_actual_stats(self) -> bool:
        """Check if this is an EXPLAIN ANALYZE with actual statistics."""
        return self.actual_time_ms is not None

    @property
    def cost_per_row(self) -> Optional[float]:
        """Calculate estimated cost per row."""
        if self.estimated_cost and self.estimated_rows and self.estimated_rows > 0:
            return self.estimated_cost / self.estimated_rows
        return None

    def add_warning(self, warning: str) -> None:
        """Add a performance warning."""
        if warning not in self.warnings:
            self.warnings.append(warning)

    def add_recommendation(self, recommendation: str) -> None:
        """Add an optimization recommendation."""
        if recommendation not in self.recommendations:
            self.recommendations.append(recommendation)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "SELECT * FROM users WHERE email = 'test@example.com'",
                    "plan": "Seq Scan on users  (cost=0.00..25.88 rows=1 width=100)",
                    "plan_json": None,
                    "estimated_cost": 25.88,
                    "estimated_rows": 1,
                    "actual_time_ms": None,
                    "actual_rows": None,
                    "warnings": ["Sequential scan on large table"],
                    "recommendations": ["Consider adding index on email column"],
                }
            ]
        }
    }
