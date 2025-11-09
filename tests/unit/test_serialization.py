"""Tests for direct orjson serialization used in the codebase."""

import datetime
import decimal
import ipaddress
import json
import uuid

import orjson


class TestOrjsonSerialization:
    """Test orjson's native serialization capabilities."""

    def test_orjson_basic_types(self):
        """Test that orjson handles basic types correctly."""
        data = {
            "string": "test",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
        }

        # orjson should handle all basic types
        json_bytes = orjson.dumps(data)
        result = orjson.loads(json_bytes)
        assert result == data

    def test_orjson_datetime_types(self):
        """Test that orjson handles datetime types natively."""
        dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        date = datetime.date(2024, 1, 15)
        time = datetime.time(10, 30, 0)

        # orjson converts these to ISO format strings
        assert orjson.loads(orjson.dumps(dt)) == "2024-01-15T10:30:00"
        assert orjson.loads(orjson.dumps(date)) == "2024-01-15"
        assert orjson.loads(orjson.dumps(time)) == "10:30:00"

    def test_orjson_uuid(self):
        """Test that orjson handles UUID natively."""
        test_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        result = orjson.loads(orjson.dumps(test_uuid))
        assert result == "12345678-1234-5678-1234-567812345678"

    def test_orjson_decimal(self):
        """Test that orjson handles Decimal with str() default handler."""
        # orjson doesn't handle Decimal natively, need default handler
        dec = decimal.Decimal("123.456789")
        result = orjson.loads(orjson.dumps(dec, default=str))
        assert result == "123.456789"

    def test_orjson_with_str_default(self):
        """Test using str() as default handler for unsupported types."""
        # Types orjson doesn't handle natively
        test_data = {
            "ipv4": ipaddress.IPv4Address("192.168.1.1"),
            "ipv6": ipaddress.IPv6Address("::1"),
            "timedelta": datetime.timedelta(days=1),
            "set": {1, 2, 3},
        }

        # Use str() as default handler (as we do in the codebase)
        json_bytes = orjson.dumps(test_data, default=str)
        result = orjson.loads(json_bytes)

        # All non-native types should be converted to strings
        assert result["ipv4"] == "192.168.1.1"
        assert result["ipv6"] == "::1"
        assert "1 day" in result["timedelta"] or "86400" in result["timedelta"]
        assert "{" in result["set"]  # Set converted to string representation


class TestQueryResultSerialization:
    """Test serialization patterns used in QueryExecutor."""

    def test_query_result_pattern(self):
        """Test the pattern used in executor.py for query results."""
        # Simulate database query result rows
        rows = [
            {
                "id": 1,
                "name": "Alice",
                "created": datetime.datetime(2024, 1, 15, 10, 30, 0),
                "ip": ipaddress.IPv4Address("192.168.1.1"),
                "price": decimal.Decimal("19.99"),
            },
            {
                "id": 2,
                "name": "Bob",
                "created": datetime.datetime(2024, 1, 16, 11, 45, 0),
                "ip": ipaddress.IPv4Address("192.168.1.2"),
                "price": decimal.Decimal("29.99"),
            },
        ]

        # This is exactly how executor.py handles rows
        json_bytes = orjson.dumps(rows, default=str)
        result = orjson.loads(json_bytes)

        # Verify the results
        assert result[0]["id"] == 1
        assert result[0]["name"] == "Alice"
        assert result[0]["created"] == "2024-01-15T10:30:00"
        assert result[0]["ip"] == "192.168.1.1"
        assert result[0]["price"] == "19.99"

        assert result[1]["id"] == 2
        assert result[1]["name"] == "Bob"

    def test_mixed_types_in_row(self):
        """Test rows with various database types."""
        row = {
            "id": 42,
            "table_name": "my_table",  # Should remain as string
            "schema": "public",  # Should remain as string
            "created_at": datetime.datetime(2024, 1, 15, 10, 30),
            "is_active": True,
            "metadata": {"type": "base_table"},  # Nested dict
            "tags": ["tag1", "tag2"],  # List
            "uuid": uuid.UUID("12345678-1234-5678-1234-567812345678"),
        }

        # Use orjson with str() default as in the codebase
        json_bytes = orjson.dumps(row, default=str)
        result = orjson.loads(json_bytes)

        # Strings should be preserved as-is
        assert result["table_name"] == "my_table"
        assert result["schema"] == "public"

        # Other types should be converted appropriately
        assert result["id"] == 42
        assert result["created_at"] == "2024-01-15T10:30:00"
        assert result["is_active"] is True
        assert result["metadata"] == {"type": "base_table"}
        assert result["tags"] == ["tag1", "tag2"]
        assert result["uuid"] == "12345678-1234-5678-1234-567812345678"


class TestAdapterSerialization:
    """Test the safe_value pattern used in database adapters."""

    def test_safe_value_pattern(self):
        """Test the safe_value function pattern used in adapters."""

        def safe_value(val):
            """Replicate the safe_value function from adapters."""
            if val is None:
                return None
            try:
                orjson.dumps(val)
                return val
            except Exception:
                return str(val)

        # Test various values
        assert safe_value(None) is None
        assert safe_value("string") == "string"
        assert safe_value(42) == 42
        assert safe_value(3.14) == 3.14
        assert safe_value(True) is True

        # datetime is handled by orjson
        dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        assert safe_value(dt) == dt

        # UUID is handled by orjson
        test_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert safe_value(test_uuid) == test_uuid

        # IP addresses need str() conversion
        ipv4 = ipaddress.IPv4Address("192.168.1.1")
        assert safe_value(ipv4) == "192.168.1.1"

        # Custom class falls back to str()
        class CustomType:
            def __str__(self):
                return "custom_value"

        custom = CustomType()
        assert safe_value(custom) == "custom_value"


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_collections(self):
        """Test empty collections."""
        data = {
            "empty_list": [],
            "empty_dict": {},
            "empty_string": "",
        }

        json_bytes = orjson.dumps(data)
        result = orjson.loads(json_bytes)
        assert result == data

    def test_nested_structures(self):
        """Test deeply nested structures."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "values": [1, 2, 3],
                        "date": datetime.date(2024, 1, 15),
                    }
                }
            }
        }

        json_bytes = orjson.dumps(data)
        result = orjson.loads(json_bytes)

        assert result["level1"]["level2"]["level3"]["values"] == [1, 2, 3]
        assert result["level1"]["level2"]["level3"]["date"] == "2024-01-15"

    def test_large_dataset(self):
        """Test with larger dataset to ensure performance."""
        # Create 1000 rows
        rows = []
        for i in range(1000):
            rows.append(
                {
                    "id": i,
                    "name": f"User {i}",
                    "created": datetime.datetime(2024, 1, 15, 10, 30, 0),
                    "value": decimal.Decimal(f"{i}.99"),
                }
            )

        # Should handle large datasets efficiently
        json_bytes = orjson.dumps(rows, default=str)
        result = orjson.loads(json_bytes)

        assert len(result) == 1000
        assert result[0]["id"] == 0
        assert result[999]["id"] == 999

    def test_null_values(self):
        """Test handling of null/None values."""
        rows = [
            {"id": 1, "value": None},
            {"id": 2, "value": "not null"},
        ]

        json_bytes = orjson.dumps(rows)
        result = orjson.loads(json_bytes)

        assert result[0]["value"] is None
        assert result[1]["value"] == "not null"


class TestCompatibility:
    """Test that orjson output is compatible with standard json."""

    def test_orjson_json_compatibility(self):
        """Test that orjson output can be read by standard json."""
        data = {
            "string": "test",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
            "list": [1, 2, 3],
            "dict": {"key": "value"},
            "date": datetime.date(2024, 1, 15),
        }

        # Serialize with orjson
        orjson_bytes = orjson.dumps(data)
        orjson_str = orjson_bytes.decode("utf-8")

        # Should be readable by standard json
        json_result = json.loads(orjson_str)

        assert json_result["string"] == "test"
        assert json_result["number"] == 42
        assert json_result["date"] == "2024-01-15"
