"""Tests for serialization utilities."""

import datetime
import decimal
import ipaddress
import json
import uuid
from typing import Any

import pytest

from db_connect_mcp.utils.serialization import (
    convert_row_to_json_safe,
    convert_rows_to_json_safe,
    convert_value_to_json_safe,
)


class TestValueConversion:
    """Test individual value conversion."""

    def test_none_conversion(self):
        """Test None value conversion."""
        assert convert_value_to_json_safe(None) is None

    def test_basic_types(self):
        """Test basic Python types pass through unchanged."""
        assert convert_value_to_json_safe("string") == "string"
        assert convert_value_to_json_safe(42) == 42
        assert convert_value_to_json_safe(3.14) == 3.14
        assert convert_value_to_json_safe(True) is True
        assert convert_value_to_json_safe(False) is False

    def test_datetime_conversion(self):
        """Test datetime types are converted to ISO format strings."""
        dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        assert convert_value_to_json_safe(dt) == "2024-01-15T10:30:00"

        date = datetime.date(2024, 1, 15)
        assert convert_value_to_json_safe(date) == "2024-01-15"

        time = datetime.time(10, 30, 0)
        assert convert_value_to_json_safe(time) == "10:30:00"

        delta = datetime.timedelta(days=1, hours=2, minutes=30)
        assert convert_value_to_json_safe(delta) == 95400.0  # Total seconds

    def test_ip_address_conversion(self):
        """Test IP address types are converted to strings."""
        ipv4 = ipaddress.IPv4Address("192.168.1.1")
        assert convert_value_to_json_safe(ipv4) == "192.168.1.1"

        ipv6 = ipaddress.IPv6Address("::1")
        assert convert_value_to_json_safe(ipv6) == "::1"

        ipv4_net = ipaddress.IPv4Network("192.168.1.0/24")
        assert convert_value_to_json_safe(ipv4_net) == "192.168.1.0/24"

    def test_uuid_conversion(self):
        """Test UUID is converted to string."""
        test_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert (
            convert_value_to_json_safe(test_uuid)
            == "12345678-1234-5678-1234-567812345678"
        )

    def test_decimal_conversion(self):
        """Test Decimal conversion.

        orjson preserves Decimals as strings to maintain precision,
        which is the correct behavior for financial/precision data.
        """
        # Integer-like decimal - orjson keeps as string for precision
        assert convert_value_to_json_safe(decimal.Decimal("42")) == "42"

        # Float-like decimal - also kept as string
        assert convert_value_to_json_safe(decimal.Decimal("3.14")) == "3.14"

        # Very large decimal - string preserves full precision
        large = decimal.Decimal("12345678901234567890.123456789")
        result = convert_value_to_json_safe(large)
        assert isinstance(result, str)
        assert result == "12345678901234567890.123456789"

    def test_bytes_conversion(self):
        """Test bytes/bytearray conversion."""
        # UTF-8 decodable bytes
        utf8_bytes = b"Hello, World!"
        assert convert_value_to_json_safe(utf8_bytes) == "Hello, World!"

        # Non-UTF-8 bytes - should be base64 encoded
        binary_bytes = bytes([0xFF, 0xFE, 0xFD])
        result = convert_value_to_json_safe(binary_bytes)
        assert isinstance(result, str)
        # Should be base64 encoded
        import base64

        assert result == base64.b64encode(binary_bytes).decode("ascii")

    def test_memoryview_conversion(self):
        """Test memoryview conversion (from bytea)."""
        data = b"test data"
        mv = memoryview(data)
        assert convert_value_to_json_safe(mv) == "test data"

    def test_set_conversion(self):
        """Test set is converted to list."""
        test_set = {1, 2, 3}
        result = convert_value_to_json_safe(test_set)
        assert isinstance(result, list)
        assert set(result) == test_set

    def test_list_conversion(self):
        """Test list with nested values is recursively converted."""
        test_list = [1, "text", datetime.date(2024, 1, 15), None]
        result = convert_value_to_json_safe(test_list)
        assert result == [1, "text", "2024-01-15", None]

    def test_dict_conversion(self):
        """Test dict with nested values is recursively converted."""
        test_dict = {
            "number": 42,
            "date": datetime.date(2024, 1, 15),
            "uuid": uuid.UUID("12345678-1234-5678-1234-567812345678"),
        }
        result = convert_value_to_json_safe(test_dict)
        assert result == {
            "number": 42,
            "date": "2024-01-15",
            "uuid": "12345678-1234-5678-1234-567812345678",
        }

    def test_string_not_treated_as_range(self):
        """Test that regular strings are NOT converted as range types.

        This is the critical bug fix - strings have .lower and .upper methods
        but should not be treated as PostgreSQL range types.
        """
        # Simple string
        assert convert_value_to_json_safe("table_name") == "table_name"

        # String with various cases
        assert convert_value_to_json_safe("MyTableName") == "MyTableName"

        # Empty string
        assert convert_value_to_json_safe("") == ""

        # String with special characters
        assert convert_value_to_json_safe("hello_world_123") == "hello_world_123"

    def test_mock_range_type(self):
        """Test that actual range-like objects ARE converted correctly."""

        class MockRange:
            """Mock PostgreSQL range type."""

            def __init__(self, lower, upper, bounds="[]"):
                self.lower = lower
                self.upper = upper
                self.bounds = bounds

        mock_range = MockRange(1, 10, "[)")
        result = convert_value_to_json_safe(mock_range)

        assert isinstance(result, dict)
        assert result == {"lower": 1, "upper": 10, "bounds": "[)"}

    def test_fallback_to_string(self):
        """Test that unknown types fall back to string conversion."""

        class CustomType:
            def __str__(self):
                return "custom_value"

        custom = CustomType()
        assert convert_value_to_json_safe(custom) == "custom_value"


class TestRowConversion:
    """Test row dictionary conversion."""

    def test_empty_row(self):
        """Test empty row conversion."""
        assert convert_row_to_json_safe({}) == {}

    def test_simple_row(self):
        """Test row with basic types."""
        row = {
            "id": 1,
            "name": "test",
            "active": True,
            "score": 3.14,
        }
        assert convert_row_to_json_safe(row) == row

    def test_complex_row(self):
        """Test row with complex types."""
        row = {
            "id": 1,
            "created_at": datetime.datetime(2024, 1, 15, 10, 30),
            "user_uuid": uuid.UUID("12345678-1234-5678-1234-567812345678"),
            "ip_address": ipaddress.IPv4Address("192.168.1.1"),
            "metadata": {"key": "value"},
        }

        result = convert_row_to_json_safe(row)

        assert result["id"] == 1
        assert result["created_at"] == "2024-01-15T10:30:00"
        assert result["user_uuid"] == "12345678-1234-5678-1234-567812345678"
        assert result["ip_address"] == "192.168.1.1"
        assert result["metadata"] == {"key": "value"}


class TestRowsConversion:
    """Test multiple rows conversion."""

    def test_empty_rows(self):
        """Test empty rows list."""
        assert convert_rows_to_json_safe([]) == []

    def test_multiple_rows(self):
        """Test multiple rows conversion."""
        rows = [
            {"id": 1, "name": "Alice", "created": datetime.date(2024, 1, 1)},
            {"id": 2, "name": "Bob", "created": datetime.date(2024, 1, 2)},
        ]

        result = convert_rows_to_json_safe(rows)

        assert len(result) == 2
        assert result[0]["created"] == "2024-01-01"
        assert result[1]["created"] == "2024-01-02"


class TestJSONSerialization:
    """Test that converted values are actually JSON-serializable."""

    def test_converted_values_are_json_safe(self):
        """Test all converted values can be serialized to JSON."""
        test_values = [
            None,
            "string",
            42,
            3.14,
            True,
            datetime.datetime(2024, 1, 15),
            datetime.date(2024, 1, 15),
            ipaddress.IPv4Address("192.168.1.1"),
            uuid.UUID("12345678-1234-5678-1234-567812345678"),
            decimal.Decimal("123.45"),
            b"hello",
            [1, 2, 3],
            {"key": "value"},
        ]

        for value in test_values:
            converted = convert_value_to_json_safe(value)
            # This should not raise an exception
            json.dumps(converted)

    def test_query_result_like_structure(self):
        """Test structure similar to actual query results."""
        # Simulate a query result with string values (the bug scenario)
        rows = [
            {"table_name": "users"},
            {"table_name": "products"},
            {"table_name": "orders"},
        ]

        # Convert rows (this was failing before the fix)
        converted_rows = convert_rows_to_json_safe(rows)

        # Verify strings are preserved
        assert converted_rows[0]["table_name"] == "users"
        assert converted_rows[1]["table_name"] == "products"
        assert converted_rows[2]["table_name"] == "orders"

        # Verify JSON serialization works
        json_str = json.dumps(converted_rows)

        # Verify we can deserialize and get original values back
        deserialized = json.loads(json_str)
        assert deserialized == converted_rows

    def test_mixed_types_in_row(self):
        """Test row with mixed types including strings (regression test)."""
        row = {
            "id": 42,
            "table_name": "my_table",  # This was being incorrectly converted
            "schema": "public",  # This too
            "created_at": datetime.datetime(2024, 1, 15, 10, 30),
            "is_active": True,
            "metadata": {"type": "base_table"},  # Nested strings
        }

        converted = convert_row_to_json_safe(row)

        # All strings should be preserved as-is
        assert converted["table_name"] == "my_table"
        assert converted["schema"] == "public"
        assert converted["metadata"]["type"] == "base_table"

        # Other types should be converted appropriately
        assert converted["id"] == 42
        assert converted["created_at"] == "2024-01-15T10:30:00"
        assert converted["is_active"] is True

        # Verify full JSON serialization
        json_str = json.dumps(converted)
        assert "my_table" in json_str
        assert "public" in json_str
