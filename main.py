#!/usr/bin/env python
"""
Legacy entry point for db-connect-mcp.

DEPRECATED: This file is kept for backward compatibility only.

Preferred ways to run the server:
1. If installed: db-connect-mcp
2. As a module: python -m db_connect_mcp
3. With uv: uv run db-connect-mcp

This file will be removed in a future version.
"""

import warnings

from db_connect_mcp.server import cli_entry

# Show deprecation warning
warnings.warn(
    "Running via main.py is deprecated. "
    "Use 'db-connect-mcp' (if installed) or 'python -m db_connect_mcp' instead.",
    DeprecationWarning,
    stacklevel=2,
)

if __name__ == "__main__":
    cli_entry()
