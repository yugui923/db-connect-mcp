"""Pytest configuration and fixtures for db-connect-mcp tests.

This module provides global pytest configuration and custom warning filters.
"""

import warnings

# Filter Pydantic warning about 'schema' field shadowing BaseModel attribute
# This is intentional - we need the 'schema' field for database schema names
warnings.filterwarnings(
    "ignore",
    message=r".*Field name \"schema\".*shadows an attribute.*",
    category=UserWarning,
)
