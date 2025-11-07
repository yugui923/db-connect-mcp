"""Type conversion utilities for JSON serialization.

Handles conversion of database-specific types to JSON-serializable formats.
"""

import datetime
import decimal
import ipaddress
import uuid
from typing import Any


def convert_value_to_json_safe(value: Any) -> Any:
    """
    Convert a value to a JSON-serializable format.

    Args:
        value: Value to convert

    Returns:
        JSON-serializable value
    """
    if value is None:
        return None

    # Handle datetime types
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()

    if isinstance(value, datetime.time):
        return value.isoformat()

    if isinstance(value, datetime.timedelta):
        return value.total_seconds()

    # Handle IP address types
    if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return str(value)

    if isinstance(value, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
        return str(value)

    # Handle UUID
    if isinstance(value, uuid.UUID):
        return str(value)

    # Handle Decimal (preserve precision as string)
    if isinstance(value, decimal.Decimal):
        # Convert to float for numbers, but keep as string if very large/precise
        if abs(value) < 1e15 and value == value.to_integral_value():
            # Integer-like decimal
            return int(value)
        elif abs(value) < 1e15:
            # Float-like decimal
            return float(value)
        else:
            # Very large or very precise - keep as string
            return str(value)

    # Handle bytes/bytea
    if isinstance(value, (bytes, bytearray)):
        # Try UTF-8 decode first, fall back to base64
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            import base64

            return base64.b64encode(value).decode("ascii")

    # Handle memoryview (from bytea)
    if isinstance(value, memoryview):
        return convert_value_to_json_safe(bytes(value))

    # Handle sets (convert to list)
    if isinstance(value, set):
        return list(value)

    # Handle arrays/lists (recursively convert elements)
    if isinstance(value, (list, tuple)):
        return [convert_value_to_json_safe(item) for item in value]

    # Handle dicts (recursively convert values)
    if isinstance(value, dict):
        return {key: convert_value_to_json_safe(val) for key, val in value.items()}

    # Handle PostgreSQL range types (if available)
    # These are typically from psycopg2.extras or asyncpg Range types
    if hasattr(value, "lower") and hasattr(value, "upper"):
        return {
            "lower": convert_value_to_json_safe(value.lower),
            "upper": convert_value_to_json_safe(value.upper),
            "bounds": getattr(value, "bounds", "[]"),
        }

    # For any other type, try to convert to string as fallback
    # This handles custom types, enums, etc.
    if not isinstance(value, (str, int, float, bool)):
        return str(value)

    return value


def convert_row_to_json_safe(row: dict[str, Any]) -> dict[str, Any]:
    """
    Convert all values in a row dict to JSON-serializable formats.

    Args:
        row: Dictionary representing a database row

    Returns:
        Dictionary with JSON-serializable values
    """
    return {key: convert_value_to_json_safe(value) for key, value in row.items()}


def convert_rows_to_json_safe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert all rows to JSON-serializable format.

    Args:
        rows: List of row dictionaries

    Returns:
        List of dictionaries with JSON-serializable values
    """
    return [convert_row_to_json_safe(row) for row in rows]
