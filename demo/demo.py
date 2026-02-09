#!/usr/bin/env python3
"""Demo script for db-connect-mcp showcasing database exploration capabilities.

This script demonstrates the MCP server's ability to:
- Connect to a database and retrieve info
- List schemas and tables
- Describe table structure
- Sample data
- Execute read-only queries
- Analyze column statistics

Run with: uv run python demo/demo.py
Requires: DATABASE_URL environment variable or local test database running
"""

import asyncio
import json
import logging
import os
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Suppress noisy logs for cleaner demo output
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("db_connect_mcp").setLevel(logging.WARNING)
logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger("sshtunnel").setLevel(logging.WARNING)

# Demo timing constants (seconds)
TOOL_CALL_DELAY = 1.5  # Delay before calling tool (simulates thinking)
RESPONSE_DELAY = 4.0  # Delay after tool response (lets user read output)

# ANSI color codes for terminal output
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def header(text: str) -> None:
    """Print a styled section header."""
    print(f"\n{CYAN}{BOLD}{'─' * 60}{RESET}")
    print(f"{CYAN}{BOLD}  {text}{RESET}")
    print(f"{CYAN}{BOLD}{'─' * 60}{RESET}\n")


def subheader(text: str) -> None:
    """Print a styled subheader."""
    print(f"\n{YELLOW}▸ {text}{RESET}")


def tool_call(name: str) -> None:
    """Print tool call indicator."""
    print(f"{DIM}Calling:{RESET} {MAGENTA}{name}{RESET}")


def success(text: str) -> None:
    """Print success message."""
    print(f"{GREEN}✓{RESET} {text}")


def print_table(
    rows: list[dict], columns: list[str] | None = None, max_rows: int = 5
) -> None:
    """Print data as a formatted table."""
    if not rows:
        print(f"{DIM}  (no data){RESET}")
        return

    cols = columns or list(rows[0].keys())
    # Calculate column widths
    widths = {col: len(col) for col in cols}
    for row in rows[:max_rows]:
        for col in cols:
            val = str(row.get(col, ""))[:30]  # Truncate long values
            widths[col] = max(widths[col], len(val))

    # Print header
    header_line = " │ ".join(f"{col:<{widths[col]}}" for col in cols)
    print(f"  {BLUE}{header_line}{RESET}")
    print(f"  {'─' * len(header_line)}")

    # Print rows
    for row in rows[:max_rows]:
        row_line = " │ ".join(
            f"{str(row.get(col, ''))[:30]:<{widths[col]}}" for col in cols
        )
        print(f"  {row_line}")

    if len(rows) > max_rows:
        print(f"  {DIM}... and {len(rows) - max_rows} more rows{RESET}")


async def call_tool(client: ClientSession, name: str, args: dict | None = None) -> dict:
    """Call an MCP tool and return the parsed result."""
    tool_call(name)
    time.sleep(TOOL_CALL_DELAY)  # Simulate thinking before call

    response = await client.call_tool(name, arguments=args or {})

    if response.isError:
        raise RuntimeError(f"Tool error: {response.content}")

    # Parse the JSON response from the first text content
    result = {}
    for content in response.content:
        if hasattr(content, "text"):
            result = json.loads(content.text)
            break

    return result


def pause_for_reading() -> None:
    """Pause to let user read the output."""
    time.sleep(RESPONSE_DELAY)


async def run_demo() -> None:
    """Run the database exploration demo."""
    # Check for database URL (prefer PG_TEST_DATABASE_URL for demo)
    database_url = os.environ.get("PG_TEST_DATABASE_URL") or os.environ.get(
        "DATABASE_URL"
    )
    if not database_url:
        # Try local test database
        database_url = "postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb"
        print(f"{DIM}Using local test database: {database_url[:50]}...{RESET}")

    # Build clean environment without SSH tunnel vars for demo
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("SSH_")}
    clean_env["DATABASE_URL"] = database_url
    clean_env["LOG_LEVEL"] = "WARNING"  # Suppress noisy server logs

    header("db-connect-mcp Demo")
    print("Demonstrating read-only database exploration via MCP protocol\n")

    # Server parameters
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "db_connect_mcp"],
        env=clean_env,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as client:
            # Initialize the session
            await client.initialize()
            success("Connected to db-connect-mcp server")

            # List available tools
            subheader("Available Tools")
            tools = await client.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"  {', '.join(tool_names)}")
            pause_for_reading()

            # ─────────────────────────────────────────────────────────────
            header("1. Database Information")
            # ─────────────────────────────────────────────────────────────

            db_info = await call_tool(client, "get_database_info")
            print(f"  Dialect:    {BOLD}{db_info.get('dialect', 'unknown')}{RESET}")
            print(f"  Version:    {db_info.get('version', 'unknown')}")
            print(f"  Read-only:  {GREEN}{db_info.get('read_only', True)}{RESET}")
            print(f"  Database:   {db_info.get('database', 'unknown')}")
            pause_for_reading()

            # ─────────────────────────────────────────────────────────────
            header("2. Schema Exploration")
            # ─────────────────────────────────────────────────────────────

            schemas = await call_tool(client, "list_schemas")
            schema_names = [s["name"] for s in schemas]
            print(f"  Schemas: {', '.join(schema_names)}")
            pause_for_reading()

            # List tables in public schema
            subheader("Tables in 'public' schema")
            tables = await call_tool(client, "list_tables", {"schema": "public"})
            for t in tables[:8]:
                type_indicator = "📊" if t.get("table_type") == "VIEW" else "📋"
                size = t.get("size_display", "")
                rows = t.get("estimated_rows", "")
                row_info = f" ({rows:,} rows)" if isinstance(rows, int) else ""
                print(
                    f"  {type_indicator} {t['name']:<20} {DIM}{size}{row_info}{RESET}"
                )
            if len(tables) > 8:
                print(f"  {DIM}... and {len(tables) - 8} more{RESET}")
            pause_for_reading()

            # ─────────────────────────────────────────────────────────────
            header("3. Table Structure")
            # ─────────────────────────────────────────────────────────────

            # Pick a table to describe
            target_table = (
                "users"
                if any(t["name"] == "users" for t in tables)
                else tables[0]["name"]
            )
            subheader(f"Describing '{target_table}' table")

            table_info = await call_tool(
                client, "describe_table", {"table": target_table, "schema": "public"}
            )

            # Show columns
            print(f"\n  {BLUE}Columns:{RESET}")
            for col in table_info.get("columns", [])[:6]:
                nullable = "NULL" if col.get("nullable") else "NOT NULL"
                pk = " 🔑" if col.get("is_primary_key") else ""
                print(
                    f"    • {col['name']:<15} {DIM}{col['data_type']:<12} {nullable}{pk}{RESET}"
                )
            if len(table_info.get("columns", [])) > 6:
                print(f"    {DIM}... and more columns{RESET}")

            # Show indexes if available
            indexes = table_info.get("indexes", [])
            if indexes:
                print(f"\n  {BLUE}Indexes:{RESET}")
                for idx in indexes[:3]:
                    unique = "UNIQUE " if idx.get("is_unique") else ""
                    print(f"    • {unique}{idx['name']}: {idx.get('columns', [])}")
            pause_for_reading()

            # ─────────────────────────────────────────────────────────────
            header("4. Data Sampling")
            # ─────────────────────────────────────────────────────────────

            subheader(f"Sample data from '{target_table}'")
            sample = await call_tool(
                client,
                "sample_data",
                {"table": target_table, "schema": "public", "limit": 5},
            )
            print_table(sample.get("rows", []), sample.get("columns"), max_rows=5)
            pause_for_reading()

            # ─────────────────────────────────────────────────────────────
            header("5. Column Analysis")
            # ─────────────────────────────────────────────────────────────

            # Find a good column to analyze
            columns = table_info.get("columns", [])
            analyze_col = next(
                (c["name"] for c in columns if "email" in c["name"].lower()),
                columns[0]["name"] if columns else None,
            )

            if analyze_col:
                subheader(f"Statistics for '{target_table}.{analyze_col}'")
                stats = await call_tool(
                    client,
                    "analyze_column",
                    {"table": target_table, "column": analyze_col, "schema": "public"},
                )
                print(f"  Total rows:     {stats.get('total_rows', 0):,}")
                print(f"  Null count:     {stats.get('null_count', 0):,}")
                print(f"  Unique values:  {stats.get('unique_count', 'N/A')}")
                if stats.get("min_value"):
                    print(f"  Min value:      {stats.get('min_value')}")
                if stats.get("max_value"):
                    print(f"  Max value:      {stats.get('max_value')}")
            pause_for_reading()

            # ─────────────────────────────────────────────────────────────
            header("6. Custom Query")
            # ─────────────────────────────────────────────────────────────

            query = f"SELECT COUNT(*) as total FROM {target_table}"
            subheader(f"Executing: {query}")

            result = await call_tool(client, "execute_query", {"query": query})
            print(
                f"  Result: {BOLD}{result.get('rows', [{}])[0].get('total', 0):,}{RESET} rows"
            )
            pause_for_reading()

            # ─────────────────────────────────────────────────────────────
            header("7. Table Relationships")
            # ─────────────────────────────────────────────────────────────

            subheader("Foreign key relationships in 'public' schema")
            try:
                rels = await call_tool(
                    client,
                    "get_table_relationships",
                    {"table": target_table, "schema": "public"},
                )
                if rels:
                    for r in rels[:5]:
                        print(
                            f"  {r['from_table']}.{r['from_columns']} → {r['to_table']}.{r['to_columns']}"
                        )
                else:
                    print(f"  {DIM}No foreign keys defined for this table{RESET}")
            except Exception:
                print(f"  {DIM}Relationship discovery not available{RESET}")
            pause_for_reading()

            # ─────────────────────────────────────────────────────────────
            print(f"\n{GREEN}{BOLD}Demo complete!{RESET}")
            print(f"{DIM}All operations were read-only and safe.{RESET}\n")


def main() -> None:
    """Entry point."""
    try:
        asyncio.run(run_demo())
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Demo interrupted{RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{YELLOW}Error: {e}{RESET}")
        print(f"{DIM}Make sure the test database is running:{RESET}")
        print("  cd tests/docker && docker-compose up -d")
        sys.exit(1)


if __name__ == "__main__":
    main()
