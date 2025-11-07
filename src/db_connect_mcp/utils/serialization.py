"""JSON serialization utilities using orjson for speed and correctness.

orjson handles most database types automatically and correctly:
- datetime, date, time → ISO format
- UUID → string
- Decimal → number or string (preserving precision)
- bytes → base64
- dataclasses, pydantic models → dict

We only need to handle a few special cases.
"""

import datetime
import ipaddress
from typing import Any

import orjson


def _default_handler(obj: Any) -> Any:
    """
    Custom default handler for types orjson doesn't handle natively.

    Args:
        obj: Object to serialize

    Returns:
        JSON-serializable representation

    Raises:
        TypeError: If object cannot be serialized
    """
    # timedelta - convert to total seconds
    if isinstance(obj, datetime.timedelta):
        return obj.total_seconds()

    # bytes/bytearray - try UTF-8 decode, fall back to base64
    if isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            import base64

            return base64.b64encode(obj).decode("ascii")

    # Memoryview (from bytea)
    if isinstance(obj, memoryview):
        data = bytes(obj)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            import base64

            return base64.b64encode(data).decode("ascii")

    # Sets - convert to list
    if isinstance(obj, set):
        return list(obj)

    # IP address types
    if isinstance(obj, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return str(obj)
    if isinstance(obj, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
        return str(obj)

    # PostgreSQL range types (have lower, upper, bounds attributes)
    if (
        hasattr(obj, "lower")
        and hasattr(obj, "upper")
        and hasattr(obj, "bounds")
        and not isinstance(obj, str)
        and not callable(obj.lower)
    ):
        return {
            "lower": obj.lower,
            "upper": obj.upper,
            "bounds": obj.bounds,
        }

    # Fallback for other types
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def convert_value_to_json_safe(value: Any) -> Any:
    """
    Convert a value to JSON-serializable format.

    Uses orjson's serialization and decodes back to Python objects.
    This ensures consistency with what will actually be serialized.

    Args:
        value: Value to convert

    Returns:
        JSON-serializable value
    """
    try:
        # Use orjson to serialize then deserialize - this ensures
        # the value is actually JSON-safe and matches final output
        json_bytes = orjson.dumps(value, default=_default_handler)
        return orjson.loads(json_bytes)
    except TypeError:
        # If orjson can't handle it, convert to string as fallback
        return str(value)


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


def dumps(obj: Any) -> str:
    """
    Serialize object to JSON string using orjson.

    Args:
        obj: Object to serialize

    Returns:
        JSON string
    """
    return orjson.dumps(obj, default=_default_handler).decode("utf-8")
