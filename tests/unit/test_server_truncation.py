"""Unit tests for server module truncation and utility functions."""

import json

from db_connect_mcp.server import (
    _truncate_comment,
    _truncate_list,
    _truncate_string,
    apply_dynamic_comment_limits,
    apply_truncation_to_analyze_column,
    apply_truncation_to_explain_query,
    apply_truncation_to_list_schemas,
    apply_truncation_to_list_tables,
    apply_truncation_to_sample_data,
    truncate_json_response,
    wrap_list_response_with_truncation_info,
    wrap_response_with_truncation_info,
)


class TestTruncateString:
    """Tests for _truncate_string helper function."""

    def test_string_under_limit(self):
        """Test string under limit is not truncated."""
        result, was_truncated = _truncate_string("hello", 10)
        assert result == "hello"
        assert was_truncated is False

    def test_string_at_limit(self):
        """Test string at exact limit is not truncated."""
        result, was_truncated = _truncate_string("hello", 5)
        assert result == "hello"
        assert was_truncated is False

    def test_string_over_limit(self):
        """Test string over limit is truncated with ellipsis."""
        result, was_truncated = _truncate_string("hello world", 8)
        assert result == "hello..."
        assert was_truncated is True
        assert len(result) == 8

    def test_none_value(self):
        """Test None value returns None."""
        result, was_truncated = _truncate_string(None, 10)
        assert result is None
        assert was_truncated is False

    def test_small_max_length(self):
        """Test very small max_length handles edge cases."""
        result, was_truncated = _truncate_string("hello", 3)
        assert result == "..."
        assert was_truncated is True

    def test_max_length_two(self):
        """Test max_length of 2 returns truncated ellipsis."""
        result, was_truncated = _truncate_string("hello", 2)
        assert result == ".."
        assert was_truncated is True

    def test_max_length_one(self):
        """Test max_length of 1 returns single dot."""
        result, was_truncated = _truncate_string("hello", 1)
        assert result == "."
        assert was_truncated is True

    def test_max_length_zero(self):
        """Test max_length of 0 returns None."""
        result, was_truncated = _truncate_string("hello", 0)
        assert result is None
        assert was_truncated is True


class TestTruncateComment:
    """Tests for _truncate_comment wrapper function."""

    def test_truncate_comment_short(self):
        """Test short comment is not truncated."""
        result = _truncate_comment("Short comment", 100)
        assert result == "Short comment"

    def test_truncate_comment_long(self):
        """Test long comment is truncated."""
        long_comment = "A" * 100
        result = _truncate_comment(long_comment, 50)
        assert result.endswith("...")
        assert len(result) == 50

    def test_truncate_comment_none(self):
        """Test None comment returns None."""
        result = _truncate_comment(None, 100)
        assert result is None


class TestTruncateList:
    """Tests for _truncate_list helper function."""

    def test_list_under_limit(self):
        """Test list under limit is not truncated."""
        items = [1, 2, 3]
        result, was_truncated = _truncate_list(items, 5)
        assert result == [1, 2, 3]
        assert was_truncated is False

    def test_list_at_limit(self):
        """Test list at exact limit is not truncated."""
        items = [1, 2, 3]
        result, was_truncated = _truncate_list(items, 3)
        assert result == [1, 2, 3]
        assert was_truncated is False

    def test_list_over_limit(self):
        """Test list over limit is truncated."""
        items = [1, 2, 3, 4, 5]
        result, was_truncated = _truncate_list(items, 3)
        assert result == [1, 2, 3]
        assert was_truncated is True

    def test_empty_list(self):
        """Test empty list is not truncated."""
        result, was_truncated = _truncate_list([], 10)
        assert result == []
        assert was_truncated is False


class TestTruncateJsonResponse:
    """Tests for truncate_json_response function."""

    def test_response_under_limit(self):
        """Test response under limit is returned as-is."""
        data = '{"key": "value"}'
        result = truncate_json_response(data, 100)
        assert result == data

    def test_response_at_limit(self):
        """Test response at exact limit is returned as-is."""
        data = '{"key": "value"}'
        result = truncate_json_response(data, len(data))
        assert result == data

    def test_response_over_limit(self):
        """Test response over limit returns error JSON."""
        data = '{"key": "' + "a" * 100 + '"}'
        result = truncate_json_response(data, 50)

        parsed = json.loads(result)
        assert parsed["error"] == "Response too large"
        assert parsed["original_size"] == len(data)
        assert parsed["limit"] == 50
        assert "message" in parsed


class TestWrapResponseWithTruncationInfo:
    """Tests for wrap_response_with_truncation_info function."""

    def test_no_truncation(self):
        """Test response without truncation is returned as-is."""
        data = {"key": "value"}
        result = wrap_response_with_truncation_info(data, [])
        assert result == {"key": "value"}

    def test_with_truncation(self):
        """Test response with truncation includes metadata."""
        data = {"key": "value"}
        result = wrap_response_with_truncation_info(data, ["field1"])

        assert "data" in result or "key" in result
        assert "_truncation_info" in result
        assert result["_truncation_info"]["truncated"] is True
        assert result["_truncation_info"]["truncated_fields"] == ["field1"]

    def test_list_data_no_truncation(self):
        """Test list response without truncation is wrapped."""
        data = [{"id": 1}, {"id": 2}]
        result = wrap_response_with_truncation_info(data, [])
        assert result == {"data": data}

    def test_list_data_with_truncation(self):
        """Test list response with truncation includes metadata."""
        data = [{"id": 1}, {"id": 2}]
        result = wrap_response_with_truncation_info(data, ["items"])

        assert "data" in result
        assert "_truncation_info" in result


class TestWrapListResponseWithTruncationInfo:
    """Tests for wrap_list_response_with_truncation_info function."""

    def test_no_truncation_returns_list(self):
        """Test list without truncation is returned as-is."""
        data = [{"id": 1}, {"id": 2}]
        result = wrap_list_response_with_truncation_info(data, [])
        assert result == data
        assert isinstance(result, list)

    def test_with_truncation_returns_wrapped(self):
        """Test list with truncation is wrapped with metadata."""
        data = [{"id": 1}, {"id": 2}]
        result = wrap_list_response_with_truncation_info(data, ["comment"])

        assert isinstance(result, dict)
        assert "_truncation_info" in result


class TestApplyTruncationToListSchemas:
    """Tests for apply_truncation_to_list_schemas function."""

    def test_no_comments(self):
        """Test schemas without comments are unchanged."""
        schemas = [{"name": "public"}, {"name": "private"}]
        result, truncated = apply_truncation_to_list_schemas(schemas, 100000)

        assert result == schemas
        assert truncated == []

    def test_short_comments(self):
        """Test schemas with short comments are unchanged."""
        schemas = [
            {"name": "public", "comment": "Public schema"},
            {"name": "private", "comment": "Private schema"},
        ]
        result, truncated = apply_truncation_to_list_schemas(schemas, 100000)

        assert result[0]["comment"] == "Public schema"
        assert truncated == []

    def test_long_comments_truncated(self):
        """Test schemas with long comments are truncated."""
        long_comment = "A" * 2000
        schemas = [{"name": "public", "comment": long_comment}]
        result, truncated = apply_truncation_to_list_schemas(schemas, 100000)

        assert len(result[0]["comment"]) <= 1000
        assert result[0]["comment"].endswith("...")
        assert "schemas[0].comment" in truncated


class TestApplyTruncationToListTables:
    """Tests for apply_truncation_to_list_tables function."""

    def test_no_comments(self):
        """Test tables without comments are unchanged."""
        tables = [{"name": "users"}, {"name": "orders"}]
        result, truncated = apply_truncation_to_list_tables(tables, 100000)

        assert result == tables
        assert truncated == []

    def test_short_comments(self):
        """Test tables with short comments are unchanged."""
        tables = [
            {"name": "users", "comment": "User table"},
            {"name": "orders", "comment": "Order table"},
        ]
        result, truncated = apply_truncation_to_list_tables(tables, 100000)

        assert result[0]["comment"] == "User table"
        assert truncated == []

    def test_long_comments_truncated(self):
        """Test tables with long comments are truncated."""
        long_comment = "A" * 1000
        tables = [{"name": "users", "comment": long_comment}]
        result, truncated = apply_truncation_to_list_tables(tables, 100000)

        assert len(result[0]["comment"]) <= 500
        assert "tables[0].comment" in truncated


class TestApplyTruncationToSampleData:
    """Tests for apply_truncation_to_sample_data function."""

    def test_short_values(self):
        """Test short string values are unchanged."""
        data = {"rows": [{"name": "Alice", "email": "alice@example.com"}]}
        result, truncated = apply_truncation_to_sample_data(data, 100000)

        assert result["rows"][0]["name"] == "Alice"
        assert truncated == []

    def test_long_values_truncated(self):
        """Test long string values are truncated."""
        long_value = "A" * 1000
        data = {"rows": [{"name": "Alice", "bio": long_value}]}
        result, truncated = apply_truncation_to_sample_data(data, 100000)

        assert len(result["rows"][0]["bio"]) <= 500
        assert "rows[].bio" in truncated

    def test_non_string_values_unchanged(self):
        """Test non-string values are unchanged."""
        data = {"rows": [{"id": 123, "active": True, "score": 98.5}]}
        result, truncated = apply_truncation_to_sample_data(data, 100000)

        assert result["rows"][0]["id"] == 123
        assert result["rows"][0]["active"] is True
        assert result["rows"][0]["score"] == 98.5
        assert truncated == []

    def test_empty_rows(self):
        """Test empty rows are handled."""
        data = {"rows": []}
        result, truncated = apply_truncation_to_sample_data(data, 100000)

        assert result["rows"] == []
        assert truncated == []


class TestApplyTruncationToAnalyzeColumn:
    """Tests for apply_truncation_to_analyze_column function."""

    def test_no_common_values(self):
        """Test stats without most_common_values are unchanged."""
        data = {"column": "id", "total_rows": 100}
        result, truncated = apply_truncation_to_analyze_column(data, 50000)

        assert result == data
        assert truncated == []

    def test_short_common_values(self):
        """Test short common values list is unchanged."""
        data = {
            "column": "status",
            "most_common_values": [
                {"value": "active", "count": 50},
                {"value": "inactive", "count": 30},
            ],
        }
        result, truncated = apply_truncation_to_analyze_column(data, 50000)

        assert len(result["most_common_values"]) == 2
        assert truncated == []

    def test_long_common_values_list_truncated(self):
        """Test long common values list is truncated."""
        data = {
            "column": "category",
            "most_common_values": [{"value": f"cat{i}", "count": i} for i in range(50)],
        }
        result, truncated = apply_truncation_to_analyze_column(data, 50000)

        assert len(result["most_common_values"]) <= 20
        assert "most_common_values" in truncated

    def test_long_value_strings_truncated(self):
        """Test long string values in common values are truncated."""
        long_value = "A" * 1000
        data = {
            "column": "description",
            "most_common_values": [{"value": long_value, "count": 10}],
        }
        result, truncated = apply_truncation_to_analyze_column(data, 50000)

        assert len(result["most_common_values"][0]["value"]) <= 500
        assert "most_common_values[].value" in truncated

    def test_long_min_max_values_truncated(self):
        """Test long min/max string values are truncated."""
        long_value = "Z" * 1000
        data = {
            "column": "text_col",
            "min_value": long_value,
            "max_value": long_value,
        }
        result, truncated = apply_truncation_to_analyze_column(data, 50000)

        assert len(result["min_value"]) <= 500
        assert len(result["max_value"]) <= 500
        assert "min_value" in truncated
        assert "max_value" in truncated


class TestApplyTruncationToExplainQuery:
    """Tests for apply_truncation_to_explain_query function."""

    def test_short_plan(self):
        """Test short plan is unchanged."""
        data = {"plan": "Seq Scan on users"}
        result, truncated = apply_truncation_to_explain_query(data, 100000)

        assert result["plan"] == "Seq Scan on users"
        assert truncated == []

    def test_long_plan_truncated(self):
        """Test long plan text is truncated."""
        long_plan = "Seq Scan -> " * 5000
        data = {"plan": long_plan}
        result, truncated = apply_truncation_to_explain_query(data, 100000)

        assert len(result["plan"]) <= 10000
        assert "plan" in truncated

    def test_large_plan_json_removed(self):
        """Test large plan_json is removed."""
        large_json = {"nodes": [{"type": "Seq Scan"} for _ in range(1000)]}
        data = {"plan": "Seq Scan", "plan_json": large_json}
        result, truncated = apply_truncation_to_explain_query(data, 100000)

        assert result["plan_json"] is None
        assert "plan_json_note" in result
        assert "plan_json" in truncated

    def test_small_plan_json_preserved(self):
        """Test small plan_json is preserved."""
        small_json = {"type": "Seq Scan", "table": "users"}
        data = {"plan": "Seq Scan", "plan_json": small_json}
        result, truncated = apply_truncation_to_explain_query(data, 100000)

        assert result["plan_json"] == small_json
        assert "plan_json" not in truncated


class TestApplyDynamicCommentLimits:
    """Tests for apply_dynamic_comment_limits function."""

    def test_no_comments(self):
        """Test table without comments is unchanged."""
        table_data = {"name": "users", "comment": None, "columns": []}
        result, truncated = apply_dynamic_comment_limits(table_data, 100000)

        assert result["comment"] is None
        assert truncated == []

    def test_table_comment_only(self):
        """Test table with only table comment."""
        table_data = {
            "name": "users",
            "comment": "User account table",
            "columns": [],
        }
        result, truncated = apply_dynamic_comment_limits(table_data, 100000)

        assert result["comment"] == "User account table"
        assert truncated == []

    def test_column_comments_only(self):
        """Test table with only column comments."""
        table_data = {
            "name": "users",
            "comment": None,
            "columns": [
                {"name": "id", "comment": "Primary key"},
                {"name": "email", "comment": "Email address"},
            ],
        }
        result, truncated = apply_dynamic_comment_limits(table_data, 100000)

        assert result["columns"][0]["comment"] == "Primary key"
        assert result["columns"][1]["comment"] == "Email address"
        assert truncated == []

    def test_long_table_comment_truncated(self):
        """Test long table comment is truncated."""
        long_comment = "A" * 10000
        table_data = {
            "name": "users",
            "comment": long_comment,
            "columns": [],
        }
        result, truncated = apply_dynamic_comment_limits(table_data, 5000)

        # With budget, table comment should be limited
        assert len(result["comment"]) < len(long_comment)
        assert "comment" in truncated

    def test_long_column_comments_truncated(self):
        """Test long column comments are truncated."""
        long_comment = "B" * 10000
        table_data = {
            "name": "users",
            "comment": None,
            "columns": [
                {"name": "col1", "comment": long_comment},
                {"name": "col2", "comment": long_comment},
            ],
        }
        result, truncated = apply_dynamic_comment_limits(table_data, 5000)

        for col in result["columns"]:
            assert len(col["comment"]) < len(long_comment)
        assert "columns[].comment" in truncated

    def test_budget_allocation_mixed_comments(self):
        """Test budget is allocated between table and column comments."""
        table_data = {
            "name": "users",
            "comment": "Table comment",
            "columns": [
                {"name": "col1", "comment": "Column 1 comment"},
                {"name": "col2", "comment": "Column 2 comment"},
            ],
        }
        result, truncated = apply_dynamic_comment_limits(table_data, 100000)

        # All comments should be preserved with large budget
        assert result["comment"] == "Table comment"
        assert result["columns"][0]["comment"] == "Column 1 comment"
        assert truncated == []

    def test_zero_budget_removes_comments(self):
        """Test zero available budget removes all comments."""
        # Create a table_data that when serialized without comments
        # leaves no room for comments
        table_data = {
            "name": "users",
            "comment": "Some comment",
            "columns": [{"name": "col1", "comment": "Col comment"}],
        }
        # Set a very small max_response_size
        result, truncated = apply_dynamic_comment_limits(table_data, 10)

        # Comments should be truncated or removed due to small budget
        # The function should handle this gracefully
        assert "comment" in truncated or "columns[].comment" in truncated
