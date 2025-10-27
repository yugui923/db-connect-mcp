"""Entry point for running db_mcp as a module."""

import asyncio
import sys

from src.server import main

if __name__ == "__main__":
    # Windows-specific event loop policy
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]

    asyncio.run(main())
