"""Unit tests for dynamic comment truncation in describe_table responses."""

from db_connect_mcp.server import (
    _truncate_comment,
    _truncate_string,
    apply_dynamic_comment_limits,
    apply_truncation_to_list_schemas,
    apply_truncation_to_list_tables,
    apply_truncation_to_sample_data,
    apply_truncation_to_analyze_column,
    apply_truncation_to_explain_query,
    wrap_response_with_truncation_info,
)


class TestTruncateComment:
    """Test the _truncate_comment helper function."""

    def test_none_comment_returns_none(self):
        """None comment should return None."""
        assert _truncate_comment(None, 100) is None

    def test_short_comment_unchanged(self):
        """Comment within limit should be unchanged."""
        comment = "Short comment"
        assert _truncate_comment(comment, 100) == comment

    def test_exact_length_unchanged(self):
        """Comment exactly at limit should be unchanged."""
        comment = "X" * 50
        assert _truncate_comment(comment, 50) == comment

    def test_long_comment_truncated(self):
        """Comment exceeding limit should be truncated with ellipsis."""
        comment = "A" * 100
        result = _truncate_comment(comment, 50)
        assert len(result) == 50
        assert result.endswith("...")
        assert result == "A" * 47 + "..."

    def test_very_short_limit(self):
        """Very short limit should still work."""
        comment = "Hello world"
        result = _truncate_comment(comment, 5)
        assert len(result) == 5
        assert result == "He..."

    def test_limit_of_three(self):
        """Limit of 3 should just return ellipsis."""
        comment = "Hello world"
        result = _truncate_comment(comment, 3)
        assert result == "..."

    def test_limit_less_than_three(self):
        """Limit less than 3 should return partial ellipsis."""
        comment = "Hello world"
        assert _truncate_comment(comment, 2) == ".."
        assert _truncate_comment(comment, 1) == "."
        assert _truncate_comment(comment, 0) is None


class TestTruncateString:
    """Test the _truncate_string helper function with truncation indicator."""

    def test_returns_tuple(self):
        """Should return (value, was_truncated) tuple."""
        result = _truncate_string("short", 100)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_not_truncated(self):
        """Short string should not be truncated."""
        value, was_truncated = _truncate_string("short", 100)
        assert value == "short"
        assert was_truncated is False

    def test_truncated(self):
        """Long string should be truncated with indicator."""
        value, was_truncated = _truncate_string("A" * 100, 50)
        assert len(value) == 50
        assert value.endswith("...")
        assert was_truncated is True


class TestApplyDynamicCommentLimits:
    """Test the apply_dynamic_comment_limits function."""

    def test_empty_table(self):
        """Empty table should work."""
        table_data = {
            "name": "test",
            "columns": [],
            "comment": None,
        }
        result, truncated_fields = apply_dynamic_comment_limits(table_data, 10000)
        assert result["name"] == "test"
        assert result["comment"] is None
        assert truncated_fields == []

    def test_small_table_comments_preserved(self):
        """Small table with short comments should preserve them."""
        table_data = {
            "name": "test",
            "comment": "Table comment",
            "columns": [
                {"name": "id", "comment": "ID column"},
                {"name": "name", "comment": "Name column"},
            ],
        }
        result, truncated_fields = apply_dynamic_comment_limits(table_data, 100000)
        assert result["comment"] == "Table comment"
        assert result["columns"][0]["comment"] == "ID column"
        assert result["columns"][1]["comment"] == "Name column"
        assert truncated_fields == []

    def test_long_comment_truncated(self):
        """Very long comment should be truncated."""
        long_comment = "X" * 10000
        table_data = {
            "name": "test",
            "comment": long_comment,
            "columns": [
                {"name": "id", "comment": "Short"},
            ],
        }
        result, truncated_fields = apply_dynamic_comment_limits(table_data, 5000)

        # Table comment should be truncated
        assert len(result["comment"]) < len(long_comment)
        assert result["comment"].endswith("...")
        assert "comment" in truncated_fields

    def test_many_columns_share_budget(self):
        """Many columns should share the comment budget."""
        # Create a table with 100 columns, each with a 500-char comment
        columns = [{"name": f"col_{i}", "comment": "X" * 500} for i in range(100)]
        table_data = {
            "name": "test",
            "comment": "Table comment",
            "columns": columns,
        }

        # With 50K limit, each column should get roughly 450 chars for comments
        # (50K - base_size - safety_margin) / 100 columns
        result, truncated_fields = apply_dynamic_comment_limits(table_data, 50000)

        # All column comments should be present but potentially truncated
        for col in result["columns"]:
            assert col["comment"] is not None
            # Each should be much shorter than original 500
            assert len(col["comment"]) < 500

        # Truncation should be recorded
        assert "columns[].comment" in truncated_fields

    def test_single_huge_comment_doesnt_dominate(self):
        """One huge comment shouldn't take all the budget."""
        columns = [
            {"name": "id", "comment": "Normal short comment"},
            {"name": "huge", "comment": "X" * 50000},  # 50K comment
            {"name": "other", "comment": "Another normal comment"},
        ]
        table_data = {
            "name": "test",
            "comment": None,
            "columns": columns,
        }

        result, truncated_fields = apply_dynamic_comment_limits(table_data, 10000)

        # The huge comment should be truncated significantly
        huge_col = next(c for c in result["columns"] if c["name"] == "huge")
        assert len(huge_col["comment"]) < 5000

        # Other comments should still exist
        id_col = next(c for c in result["columns"] if c["name"] == "id")
        other_col = next(c for c in result["columns"] if c["name"] == "other")

        # Short comments might be fully preserved if within budget
        assert id_col["comment"] is not None
        assert other_col["comment"] is not None

    def test_budget_distribution_proportional(self):
        """Budget should be distributed giving table comment 10%."""
        table_data = {
            "name": "test",
            "comment": "T" * 5000,  # Long table comment
            "columns": [
                {"name": "c1", "comment": "C" * 5000},
                {"name": "c2", "comment": "C" * 5000},
            ],
        }

        result, truncated_fields = apply_dynamic_comment_limits(table_data, 10000)

        # Table comment should be limited (gets 10% of comment budget, max 2000)
        assert len(result["comment"]) <= 2000

        # Column comments should share the remaining budget
        for col in result["columns"]:
            assert col["comment"] is not None

        # Both should be truncated
        assert "comment" in truncated_fields
        assert "columns[].comment" in truncated_fields

    def test_no_comments_preserved(self):
        """Table with no comments should work fine."""
        table_data = {
            "name": "test",
            "comment": None,
            "columns": [
                {"name": "id", "comment": None},
                {"name": "name", "comment": None},
            ],
        }
        result, truncated_fields = apply_dynamic_comment_limits(table_data, 10000)
        assert result["comment"] is None
        assert all(c["comment"] is None for c in result["columns"])
        assert truncated_fields == []

    def test_only_table_comment(self):
        """Table with only table comment should allocate more budget."""
        # Table with NO columns - table comment gets full budget
        table_data = {
            "name": "test",
            "comment": "X" * 10000,
            "columns": [],
        }
        result, truncated_fields = apply_dynamic_comment_limits(table_data, 10000)

        # With only table comment and no columns, it gets more budget (up to 5000)
        assert result["comment"] is not None
        # Should be truncated to 5000 max
        assert len(result["comment"]) <= 5000
        assert len(result["comment"]) > 1000
        assert "comment" in truncated_fields

    def test_response_fits_within_limit(self):
        """Final response should fit within the limit."""
        import json

        # Create a table that would exceed the limit without truncation
        columns = [
            {"name": f"col_{i}", "data_type": "text", "comment": "X" * 1000}
            for i in range(50)
        ]
        table_data = {
            "name": "large_table",
            "schema": "public",
            "table_type": "BASE TABLE",
            "comment": "Table with many columns and long comments " * 100,
            "columns": columns,
            "indexes": [],
            "constraints": [],
        }

        max_size = 20000
        result, _ = apply_dynamic_comment_limits(table_data, max_size)

        # Serialize to JSON
        json_result = json.dumps(result, indent=2)

        # Should fit within limit (with some margin for other serialization)
        assert len(json_result) < max_size


class TestApplyTruncationToListSchemas:
    """Test list_schemas truncation."""

    def test_short_comments_unchanged(self):
        """Short comments should not be truncated."""
        schemas = [
            {"name": "public", "comment": "Short comment"},
            {"name": "private", "comment": "Another short one"},
        ]
        result, truncated_fields = apply_truncation_to_list_schemas(schemas, 100000)
        assert result[0]["comment"] == "Short comment"
        assert truncated_fields == []

    def test_long_comments_truncated(self):
        """Long schema comments should be truncated."""
        schemas = [
            {"name": "public", "comment": "X" * 2000},
        ]
        result, truncated_fields = apply_truncation_to_list_schemas(schemas, 100000)
        assert len(result[0]["comment"]) <= 1000  # MAX_SCHEMA_COMMENT_LENGTH
        assert "schemas[0].comment" in truncated_fields


class TestApplyTruncationToListTables:
    """Test list_tables truncation."""

    def test_short_comments_unchanged(self):
        """Short comments should not be truncated."""
        tables = [
            {"name": "users", "comment": "User table"},
            {"name": "orders", "comment": "Order table"},
        ]
        result, truncated_fields = apply_truncation_to_list_tables(tables, 100000)
        assert result[0]["comment"] == "User table"
        assert truncated_fields == []

    def test_long_comments_truncated(self):
        """Long table comments should be truncated."""
        tables = [
            {"name": "users", "comment": "X" * 1000},
        ]
        result, truncated_fields = apply_truncation_to_list_tables(tables, 100000)
        assert len(result[0]["comment"]) <= 500  # MAX_TABLE_COMMENT_LENGTH
        assert "tables[0].comment" in truncated_fields


class TestApplyTruncationToSampleData:
    """Test sample_data truncation."""

    def test_short_values_unchanged(self):
        """Short cell values should not be truncated."""
        data = {
            "rows": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ]
        }
        result, truncated_fields = apply_truncation_to_sample_data(data, 100000)
        assert result["rows"][0]["name"] == "Alice"
        assert truncated_fields == []

    def test_long_string_values_truncated(self):
        """Long string values in rows should be truncated."""
        data = {
            "rows": [
                {"id": 1, "description": "X" * 1000},
            ]
        }
        result, truncated_fields = apply_truncation_to_sample_data(data, 100000)
        assert len(result["rows"][0]["description"]) <= 500  # MAX_STRING_VALUE_LENGTH
        assert "rows[].description" in truncated_fields

    def test_non_string_values_unchanged(self):
        """Non-string values should not be affected."""
        data = {
            "rows": [
                {"id": 12345678901234567890, "price": 99.99, "active": True},
            ]
        }
        result, truncated_fields = apply_truncation_to_sample_data(data, 100000)
        assert result["rows"][0]["id"] == 12345678901234567890
        assert result["rows"][0]["price"] == 99.99
        assert truncated_fields == []


class TestApplyTruncationToAnalyzeColumn:
    """Test analyze_column truncation."""

    def test_short_values_unchanged(self):
        """Short most_common_values should not be truncated."""
        data = {
            "most_common_values": [
                {"value": "short", "count": 100},
            ]
        }
        result, truncated_fields = apply_truncation_to_analyze_column(data, 50000)
        assert result["most_common_values"][0]["value"] == "short"
        assert truncated_fields == []

    def test_long_string_values_truncated(self):
        """Long string values in most_common_values should be truncated."""
        data = {
            "most_common_values": [
                {"value": "X" * 1000, "count": 100},
            ]
        }
        result, truncated_fields = apply_truncation_to_analyze_column(data, 50000)
        assert len(result["most_common_values"][0]["value"]) <= 500
        assert "most_common_values[].value" in truncated_fields

    def test_too_many_common_values_truncated(self):
        """More than MAX_COMMON_VALUES entries should be truncated."""
        data = {
            "most_common_values": [
                {"value": f"val_{i}", "count": 100 - i} for i in range(30)
            ]
        }
        result, truncated_fields = apply_truncation_to_analyze_column(data, 50000)
        assert len(result["most_common_values"]) <= 20  # MAX_COMMON_VALUES
        assert "most_common_values" in truncated_fields


class TestApplyTruncationToExplainQuery:
    """Test explain_query truncation."""

    def test_short_plan_unchanged(self):
        """Short plan should not be truncated."""
        data = {
            "plan": "Seq Scan on users (cost=0.00..10.00 rows=100)",
            "plan_json": None,
        }
        result, truncated_fields = apply_truncation_to_explain_query(data, 100000)
        assert "Seq Scan" in result["plan"]
        assert truncated_fields == []

    def test_long_plan_truncated(self):
        """Very long plan text should be truncated."""
        data = {
            "plan": "X" * 20000,
            "plan_json": None,
        }
        result, truncated_fields = apply_truncation_to_explain_query(data, 100000)
        assert len(result["plan"]) <= 10000  # MAX_PLAN_LENGTH
        assert "plan" in truncated_fields

    def test_huge_plan_json_removed(self):
        """Huge plan_json should be removed with note."""
        data = {
            "plan": "Short plan text",
            "plan_json": {"deep": {"nested": "X" * 20000}},
        }
        result, truncated_fields = apply_truncation_to_explain_query(data, 100000)
        assert result["plan_json"] is None
        assert "plan_json_note" in result
        assert "plan_json" in truncated_fields


class TestWrapResponseWithTruncationInfo:
    """Test response wrapping with truncation metadata."""

    def test_no_truncation_returns_original(self):
        """No truncation should return original data unchanged."""
        data = {"name": "test", "value": 123}
        result = wrap_response_with_truncation_info(data, [])
        assert result == data

    def test_with_truncation_adds_metadata(self):
        """Truncation should add _truncation_info."""
        data = {"name": "test", "comment": "truncated..."}
        result = wrap_response_with_truncation_info(data, ["comment"])

        assert "data" in result or "name" in result
        assert "_truncation_info" in result
        assert result["_truncation_info"]["truncated"] is True
        assert "comment" in result["_truncation_info"]["truncated_fields"]

    def test_list_wrapping(self):
        """List data should be wrapped correctly."""
        data = [{"name": "a"}, {"name": "b"}]
        result = wrap_response_with_truncation_info(data, ["name"])

        assert "_truncation_info" in result
        assert "data" in result
        assert len(result["data"]) == 2


class TestIntegrationWithRealTable:
    """Integration tests with realistic table structures."""

    def test_products_like_table(self):
        """Test with a table structure similar to products."""
        table_data = {
            "name": "products",
            "schema": "public",
            "table_type": "BASE TABLE",
            "row_count": 10000,
            "size_bytes": 1048576,
            "comment": "Product catalog with various data types for comprehensive testing",
            "columns": [
                {
                    "name": "product_id",
                    "data_type": "integer",
                    "nullable": False,
                    "primary_key": True,
                    "comment": "Unique product identifier",
                },
                {
                    "name": "sku",
                    "data_type": "varchar(50)",
                    "nullable": False,
                    "comment": "Stock Keeping Unit - unique inventory code",
                },
                {
                    "name": "name",
                    "data_type": "varchar(200)",
                    "nullable": False,
                    "comment": "Product display name shown to customers",
                },
                {
                    "name": "description",
                    "data_type": "text",
                    "nullable": True,
                    "comment": "Full product description with HTML allowed",
                },
                {
                    "name": "price",
                    "data_type": "numeric(10,2)",
                    "nullable": False,
                    "comment": "Current selling price in USD, must be >= 0",
                },
            ],
            "indexes": [
                {"name": "products_pkey", "columns": ["product_id"], "unique": True},
            ],
            "constraints": [],
        }

        result, truncated_fields = apply_dynamic_comment_limits(table_data, 100000)

        # All comments should be preserved (small table, large budget)
        assert result["comment"] == table_data["comment"]
        for i, col in enumerate(result["columns"]):
            assert col["comment"] == table_data["columns"][i]["comment"]
        assert truncated_fields == []

    def test_data_type_examples_like_table(self):
        """Test with a table that has many columns with long comments."""
        # Simulate data_type_examples with 29 columns
        columns = []
        for i in range(29):
            comment = f"This is column {i} with a moderately long comment " * 10
            columns.append(
                {
                    "name": f"col_{i}",
                    "data_type": "text",
                    "nullable": True,
                    "comment": comment,
                }
            )

        # Add one very long comment
        columns[0]["comment"] = "X" * 5000  # 5K comment

        table_data = {
            "name": "data_type_examples",
            "schema": "public",
            "table_type": "BASE TABLE",
            "comment": "Comprehensive data type coverage for serialization testing",
            "columns": columns,
            "indexes": [],
            "constraints": [],
        }

        result, truncated_fields = apply_dynamic_comment_limits(table_data, 50000)

        # The very long comment should be truncated
        assert len(result["columns"][0]["comment"]) < 5000

        # All other comments should still be present
        for col in result["columns"][1:]:
            assert col["comment"] is not None

        # Should indicate truncation
        assert "columns[].comment" in truncated_fields
