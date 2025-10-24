#!/usr/bin/env python
"""PostgreSQL Data Analyst MCP Server - Main Entry Point"""

import asyncio
import sys
from src.pg_da.server import main

# Fix for Windows: psycopg requires SelectorEventLoop on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Server error: {e}", file=sys.stderr)
        sys.exit(1)
