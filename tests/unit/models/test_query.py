"""Tests for query execution and explain plan models."""

import pytest

from db_connect_mcp.models.query import ExplainPlan, QueryResult


class TestQueryResult:
    """Tests for QueryResult model."""

    @pytest.fixture
    def sample_result(self):
        """Create a sample query result for testing."""
        return QueryResult(
            query="SELECT id, name FROM users",
            rows=[
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
                {"id": 3, "name": "Charlie"},
            ],
            row_count=3,
            columns=["id", "name"],
            execution_time_ms=5.2,
        )

    @pytest.fixture
    def empty_result(self):
        """Create an empty query result for testing."""
        return QueryResult(
            query="SELECT * FROM users WHERE id = -1",
            rows=[],
            row_count=0,
            columns=["id", "name"],
        )

    def test_basic_creation(self):
        """Test creating a query result with required fields."""
        result = QueryResult(
            query="SELECT 1",
            rows=[{"?column?": 1}],
            row_count=1,
            columns=["?column?"],
        )
        assert result.query == "SELECT 1"
        assert result.row_count == 1
        assert result.truncated is False
        assert result.warning is None
        assert result.execution_time_ms is None

    def test_is_empty_true(self, empty_result):
        """Test is_empty returns True for empty result set."""
        assert empty_result.is_empty is True

    def test_is_empty_false(self, sample_result):
        """Test is_empty returns False for non-empty result set."""
        assert sample_result.is_empty is False

    def test_column_count(self, sample_result):
        """Test column_count returns correct number of columns."""
        assert sample_result.column_count == 2

    def test_column_count_empty(self, empty_result):
        """Test column_count works with empty result."""
        assert empty_result.column_count == 2

    def test_column_count_many_columns(self):
        """Test column_count with many columns."""
        result = QueryResult(
            query="SELECT *",
            rows=[],
            row_count=0,
            columns=["a", "b", "c", "d", "e", "f", "g", "h"],
        )
        assert result.column_count == 8

    def test_get_column_values(self, sample_result):
        """Test get_column_values extracts column data."""
        ids = sample_result.get_column_values("id")
        assert ids == [1, 2, 3]

        names = sample_result.get_column_values("name")
        assert names == ["Alice", "Bob", "Charlie"]

    def test_get_column_values_missing_column(self, sample_result):
        """Test get_column_values with non-existent column returns None values."""
        values = sample_result.get_column_values("nonexistent")
        assert values == [None, None, None]

    def test_get_column_values_empty_result(self, empty_result):
        """Test get_column_values with empty result set."""
        values = empty_result.get_column_values("id")
        assert values == []

    def test_get_column_values_with_nulls(self):
        """Test get_column_values with rows containing null values."""
        result = QueryResult(
            query="SELECT id, email FROM users",
            rows=[
                {"id": 1, "email": "alice@example.com"},
                {"id": 2, "email": None},
                {"id": 3, "email": "charlie@example.com"},
            ],
            row_count=3,
            columns=["id", "email"],
        )
        emails = result.get_column_values("email")
        assert emails == ["alice@example.com", None, "charlie@example.com"]

    def test_to_table_string_empty(self, empty_result):
        """Test to_table_string with empty result set."""
        output = empty_result.to_table_string()
        assert output == "No rows returned"

    def test_to_table_string_basic(self, sample_result):
        """Test to_table_string formats correctly."""
        output = sample_result.to_table_string()
        lines = output.split("\n")

        # Check header
        assert lines[0] == "id | name"
        # Check divider
        assert lines[1].startswith("-")
        # Check data rows
        assert "1 | Alice" in lines[2]
        assert "2 | Bob" in lines[3]
        assert "3 | Charlie" in lines[4]

    def test_to_table_string_truncation(self):
        """Test to_table_string truncates when exceeding max_rows."""
        rows = [{"id": i, "name": f"User{i}"} for i in range(1, 16)]
        result = QueryResult(
            query="SELECT id, name FROM users",
            rows=rows,
            row_count=15,
            columns=["id", "name"],
        )
        output = result.to_table_string(max_rows=10)
        lines = output.split("\n")

        # Header + divider + 10 data rows + truncation message = 13 lines
        assert len(lines) == 13
        assert "... (5 more rows)" in lines[-1]

    def test_to_table_string_no_truncation_at_limit(self):
        """Test to_table_string doesn't show truncation message at exact limit."""
        rows = [{"id": i, "name": f"User{i}"} for i in range(1, 11)]
        result = QueryResult(
            query="SELECT id, name FROM users",
            rows=rows,
            row_count=10,
            columns=["id", "name"],
        )
        output = result.to_table_string(max_rows=10)
        assert "more rows" not in output

    def test_to_table_string_custom_max_rows(self):
        """Test to_table_string with custom max_rows."""
        rows = [{"id": i} for i in range(1, 21)]
        result = QueryResult(
            query="SELECT id FROM numbers",
            rows=rows,
            row_count=20,
            columns=["id"],
        )
        output = result.to_table_string(max_rows=5)
        lines = output.split("\n")

        # Header + divider + 5 rows + truncation = 8 lines
        assert len(lines) == 8
        assert "... (15 more rows)" in lines[-1]

    def test_to_table_string_null_values(self):
        """Test to_table_string handles null values."""
        result = QueryResult(
            query="SELECT id, email FROM users",
            rows=[
                {"id": 1, "email": None},
            ],
            row_count=1,
            columns=["id", "email"],
        )
        output = result.to_table_string()
        # None values are converted to string "None"
        assert "None" in output

    def test_to_table_string_missing_column_in_row(self):
        """Test to_table_string handles rows missing columns."""
        result = QueryResult(
            query="SELECT id, email FROM users",
            rows=[
                {"id": 1},  # Missing 'email' key
            ],
            row_count=1,
            columns=["id", "email"],
        )
        output = result.to_table_string()
        assert "NULL" in output

    def test_truncated_flag(self):
        """Test truncated flag is set correctly."""
        result = QueryResult(
            query="SELECT * FROM big_table",
            rows=[{"id": i} for i in range(1000)],
            row_count=1000,
            columns=["id"],
            truncated=True,
        )
        assert result.truncated is True

    def test_warning_field(self):
        """Test warning field."""
        result = QueryResult(
            query="SELECT * FROM big_table",
            rows=[],
            row_count=0,
            columns=["id"],
            warning="Query took longer than expected",
        )
        assert result.warning == "Query took longer than expected"


class TestExplainPlan:
    """Tests for ExplainPlan model."""

    @pytest.fixture
    def basic_plan(self):
        """Create a basic explain plan for testing."""
        return ExplainPlan(
            query="SELECT * FROM users WHERE id = 1",
            plan="Index Scan using users_pkey on users (cost=0.15..8.17 rows=1 width=100)",
            estimated_cost=8.17,
            estimated_rows=1,
        )

    @pytest.fixture
    def analyze_plan(self):
        """Create an EXPLAIN ANALYZE plan for testing."""
        return ExplainPlan(
            query="SELECT * FROM users WHERE id = 1",
            plan="Index Scan using users_pkey on users (cost=0.15..8.17 rows=1 width=100) (actual time=0.023..0.024 rows=1 loops=1)",
            estimated_cost=8.17,
            estimated_rows=1,
            actual_time_ms=0.024,
            actual_rows=1,
        )

    def test_basic_creation(self):
        """Test creating an explain plan with required fields."""
        plan = ExplainPlan(
            query="SELECT 1",
            plan="Result (cost=0.00..0.01 rows=1 width=4)",
        )
        assert plan.query == "SELECT 1"
        assert plan.estimated_cost is None
        assert plan.estimated_rows is None
        assert plan.actual_time_ms is None
        assert plan.warnings == []
        assert plan.recommendations == []

    def test_has_actual_stats_true(self, analyze_plan):
        """Test has_actual_stats returns True with ANALYZE results."""
        assert analyze_plan.has_actual_stats is True

    def test_has_actual_stats_false(self, basic_plan):
        """Test has_actual_stats returns False without ANALYZE."""
        assert basic_plan.has_actual_stats is False

    def test_cost_per_row_normal(self):
        """Test cost_per_row calculation with normal values."""
        plan = ExplainPlan(
            query="SELECT * FROM users",
            plan="Seq Scan on users (cost=0.00..100.00 rows=10 width=100)",
            estimated_cost=100.0,
            estimated_rows=10,
        )
        assert plan.cost_per_row == 10.0

    def test_cost_per_row_fractional(self):
        """Test cost_per_row with fractional result."""
        plan = ExplainPlan(
            query="SELECT * FROM users",
            plan="Seq Scan on users (cost=0.00..25.88 rows=1000 width=100)",
            estimated_cost=25.88,
            estimated_rows=1000,
        )
        assert plan.cost_per_row == pytest.approx(0.02588)

    def test_cost_per_row_no_cost(self):
        """Test cost_per_row returns None when no estimated_cost."""
        plan = ExplainPlan(
            query="SELECT 1",
            plan="Result",
            estimated_rows=1,
        )
        assert plan.cost_per_row is None

    def test_cost_per_row_no_rows(self):
        """Test cost_per_row returns None when no estimated_rows."""
        plan = ExplainPlan(
            query="SELECT 1",
            plan="Result",
            estimated_cost=0.01,
        )
        assert plan.cost_per_row is None

    def test_cost_per_row_zero_rows(self):
        """Test cost_per_row returns None when estimated_rows is 0."""
        plan = ExplainPlan(
            query="SELECT * FROM empty_table",
            plan="Seq Scan on empty_table",
            estimated_cost=0.0,
            estimated_rows=0,
        )
        assert plan.cost_per_row is None

    def test_add_warning(self, basic_plan):
        """Test add_warning adds a warning."""
        basic_plan.add_warning("Sequential scan on large table")
        assert "Sequential scan on large table" in basic_plan.warnings
        assert len(basic_plan.warnings) == 1

    def test_add_warning_no_duplicates(self, basic_plan):
        """Test add_warning prevents duplicate warnings."""
        basic_plan.add_warning("Sequential scan on large table")
        basic_plan.add_warning("Sequential scan on large table")
        assert len(basic_plan.warnings) == 1

    def test_add_warning_multiple(self, basic_plan):
        """Test add_warning allows multiple different warnings."""
        basic_plan.add_warning("Sequential scan on large table")
        basic_plan.add_warning("Missing index on filter column")
        assert len(basic_plan.warnings) == 2

    def test_add_recommendation(self, basic_plan):
        """Test add_recommendation adds a recommendation."""
        basic_plan.add_recommendation("Consider adding index on email column")
        assert "Consider adding index on email column" in basic_plan.recommendations
        assert len(basic_plan.recommendations) == 1

    def test_add_recommendation_no_duplicates(self, basic_plan):
        """Test add_recommendation prevents duplicate recommendations."""
        basic_plan.add_recommendation("Consider adding index on email column")
        basic_plan.add_recommendation("Consider adding index on email column")
        assert len(basic_plan.recommendations) == 1

    def test_add_recommendation_multiple(self, basic_plan):
        """Test add_recommendation allows multiple different recommendations."""
        basic_plan.add_recommendation("Consider adding index on email column")
        basic_plan.add_recommendation("Consider partitioning the table")
        assert len(basic_plan.recommendations) == 2

    def test_plan_json_field(self):
        """Test plan_json field with JSON plan."""
        plan = ExplainPlan(
            query="SELECT * FROM users",
            plan="Index Scan",
            plan_json={
                "Plan": {
                    "Node Type": "Index Scan",
                    "Relation Name": "users",
                    "Total Cost": 8.17,
                }
            },
        )
        assert plan.plan_json is not None
        assert plan.plan_json["Plan"]["Node Type"] == "Index Scan"

    def test_full_plan_with_all_fields(self, analyze_plan):
        """Test a fully populated explain plan."""
        analyze_plan.add_warning("High cost query")
        analyze_plan.add_recommendation("Consider using LIMIT")

        assert analyze_plan.has_actual_stats is True
        assert analyze_plan.cost_per_row == 8.17
        assert len(analyze_plan.warnings) == 1
        assert len(analyze_plan.recommendations) == 1
