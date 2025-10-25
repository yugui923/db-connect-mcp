"""PostgreSQL Data Analyst MCP Server

A read-only MCP server for exploratory data analysis on PostgreSQL databases.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional, AsyncGenerator, Sequence, cast
from datetime import datetime

import psycopg
from psycopg.rows import dict_row, DictRow
from psycopg import sql
from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import (
    Tool,
    TextContent,
    Resource,
)
from pydantic import AnyUrl

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
DEFAULT_SCHEMA = "public"
DEFAULT_SAMPLE_LIMIT = 100
DEFAULT_QUERY_LIMIT = 1000
MAX_SAMPLE_LIMIT = 1000
MAX_QUERY_LIMIT = 10000


class PostgresAnalyst:
    """PostgreSQL database analyst with read-only access"""

    def __init__(self, connection_string: Optional[str] = None):
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        if not self.connection_string:
            raise ValueError(
                "DATABASE_URL environment variable or connection string must be provided"
            )
        # Note: Read-only mode is enforced in get_connection() via SET command
        # This approach works with all PostgreSQL databases including cloud providers like Neon

    @asynccontextmanager
    async def get_connection(
        self,
    ) -> AsyncGenerator[psycopg.AsyncConnection[DictRow], None]:
        """Get a read-only database connection"""
        assert self.connection_string is not None, "Connection string must be set"
        async with await psycopg.AsyncConnection.connect(
            self.connection_string,
            # dict_row factory type not fully compatible with generic RowFactory[Any]
            row_factory=dict_row,  # type: ignore[arg-type]
            autocommit=True,  # Use autocommit for read-only queries
        ) as conn:
            # Set session to read-only as an extra safety measure
            await conn.execute("SET default_transaction_read_only = ON")
            yield conn  # type: ignore[misc]  # row_factory=dict_row ensures DictRow type at runtime

    async def list_schemas(self) -> Sequence[Dict[str, Any]]:
        """List all schemas in the database"""
        async with self.get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT
                        schema_name,
                        schema_owner
                    FROM information_schema.schemata
                    WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                    ORDER BY schema_name
                """)
                return cast(Sequence[Dict[str, Any]], await cur.fetchall())

    async def list_tables(
        self, schema: str = DEFAULT_SCHEMA
    ) -> Sequence[Dict[str, Any]]:
        """List all tables in a schema with estimated row counts"""
        async with self.get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        t.table_schema,
                        t.table_name,
                        t.table_type,
                        obj_description(c.oid) as table_comment,
                        pg_size_pretty(pg_total_relation_size(c.oid)) as total_size,
                        pg_size_pretty(pg_table_size(c.oid)) as table_size,
                        pg_size_pretty(pg_indexes_size(c.oid)) as indexes_size, 
                        c.reltuples::bigint as row_count_estimate,
                        CASE
                            WHEN stat.n_live_tup IS NOT NULL THEN stat.n_live_tup
                            ELSE c.reltuples::bigint
                        END as row_count
                    FROM information_schema.tables t
                    JOIN pg_class c ON c.relname = t.table_name
                    JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.table_schema
                    LEFT JOIN pg_stat_user_tables stat
                        ON stat.schemaname = t.table_schema AND stat.relname = t.table_name
                    WHERE t.table_schema = %s
                    ORDER BY t.table_name
                """,
                    (schema,),
                )
                return cast(Sequence[Dict[str, Any]], await cur.fetchall())

    async def _get_constraints(
        self,
        conn: psycopg.AsyncConnection[DictRow],
        schema: str,
        table_name: str,
        constraint_type: str,
    ) -> Sequence[Dict[str, Any]] | Dict[str, Any] | None:
        """Helper to fetch table constraints by type

        Args:
            conn: Database connection
            schema: Schema name
            table_name: Table name
            constraint_type: Constraint type ('f' for foreign key, 'p' for primary key)

        Returns:
            List of constraints for foreign keys, single constraint dict for primary key
        """
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    conname as constraint_name,
                    pg_get_constraintdef(c.oid) as definition
                FROM pg_constraint c
                JOIN pg_namespace n ON n.oid = c.connamespace
                JOIN pg_class cl ON cl.oid = c.conrelid
                WHERE n.nspname = %s
                    AND cl.relname = %s
                    AND c.contype = %s
                """,
                (schema, table_name, constraint_type),
            )
            if constraint_type == "f":
                return cast(Sequence[Dict[str, Any]], await cur.fetchall())
            else:
                return await cur.fetchone()

    async def describe_table(
        self, table_name: str, schema: str = DEFAULT_SCHEMA
    ) -> Dict[str, Any]:
        """Get detailed information about a table including columns and indexes"""
        async with self.get_connection() as conn:
            async with conn.cursor() as cur:
                # Get column information
                await cur.execute(
                    """
                    SELECT
                        column_name,
                        data_type,
                        character_maximum_length,
                        numeric_precision,
                        numeric_scale,
                        is_nullable,
                        column_default,
                        col_description(pgc.oid, cols.ordinal_position) as column_comment
                    FROM information_schema.columns cols
                    JOIN pg_class pgc ON pgc.relname = cols.table_name
                    JOIN pg_namespace pgn ON pgn.oid = pgc.relnamespace
                        AND pgn.nspname = cols.table_schema
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                """,
                    (schema, table_name),
                )
                columns = await cur.fetchall()

                # Get indexes
                await cur.execute(
                    """
                    SELECT
                        indexname,
                        indexdef,
                        tablespace
                    FROM pg_indexes
                    WHERE schemaname = %s AND tablename = %s
                    ORDER BY indexname
                """,
                    (schema, table_name),
                )
                indexes = await cur.fetchall()

            # Get constraints using helper method
            foreign_keys = await self._get_constraints(conn, schema, table_name, "f")
            primary_key = await self._get_constraints(conn, schema, table_name, "p")

            return {
                "schema": schema,
                "table": table_name,
                "columns": columns,
                "indexes": indexes,
                "foreign_keys": foreign_keys,
                "primary_key": primary_key,
            }

    async def analyze_column(
        self, table_name: str, column_name: str, schema: str = DEFAULT_SCHEMA
    ) -> Dict[str, Any]:
        """Analyze a specific column with statistics"""
        async with self.get_connection() as conn:
            async with conn.cursor() as cur:
                # Basic statistics
                query = sql.SQL("""
                    SELECT
                        COUNT(*) as total_rows,
                        COUNT({col}) as non_null_count,
                        COUNT(DISTINCT {col}) as unique_count,
                        MIN({col}::text) as min_value,
                        MAX({col}::text) as max_value
                    FROM {schema}.{table}
                """).format(
                    col=sql.Identifier(column_name),
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table_name),
                )
                # execute() accepts Composed at runtime, but type stubs don't reflect this
                await cur.execute(query)  # type: ignore[arg-type]
                basic_stats = await cur.fetchone()

                # Get data type
                await cur.execute(
                    """
                    SELECT data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = %s
                    AND table_name = %s
                    AND column_name = %s
                """,
                    (schema, table_name, column_name),
                )
                column_info = await cur.fetchone()

                # Get top values
                query = sql.SQL("""
                    SELECT
                        {col} as value,
                        COUNT(*) as frequency,
                        ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage
                    FROM {schema}.{table}
                    WHERE {col} IS NOT NULL
                    GROUP BY {col}
                    ORDER BY frequency DESC
                    LIMIT 10
                """).format(
                    col=sql.Identifier(column_name),
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table_name),
                )
                # execute() accepts Composed at runtime, but type stubs don't reflect this
                await cur.execute(query)  # type: ignore[arg-type]
                top_values = await cur.fetchall()

                # Try to get numeric statistics if applicable
                numeric_stats = None
                if column_info and column_info["data_type"] in (
                    "integer",
                    "bigint",
                    "numeric",
                    "decimal",
                    "real",
                    "double precision",
                ):
                    try:
                        query = sql.SQL("""
                            SELECT
                                AVG({col})::numeric as mean,
                                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {col}) as median,
                                STDDEV({col}) as std_dev,
                                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {col}) as q1,
                                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {col}) as q3
                            FROM {schema}.{table}
                            WHERE {col} IS NOT NULL
                        """).format(
                            col=sql.Identifier(column_name),
                            schema=sql.Identifier(schema),
                            table=sql.Identifier(table_name),
                        )
                        # execute() accepts Composed at runtime, but type stubs don't reflect this
                        await cur.execute(query)  # type: ignore[arg-type]
                        numeric_stats = await cur.fetchone()
                    except Exception:
                        pass

                return {
                    "table": f"{schema}.{table_name}",
                    "column": column_name,
                    "data_type": (column_info or {}).get("data_type"),
                    "is_nullable": (column_info or {}).get("is_nullable"),
                    "basic_statistics": basic_stats,
                    "numeric_statistics": numeric_stats,
                    "top_values": top_values,
                    "null_percentage": round(
                        (basic_stats["total_rows"] - basic_stats["non_null_count"])
                        * 100.0
                        / basic_stats["total_rows"]
                        if basic_stats and basic_stats["total_rows"] > 0
                        else 0,
                        2,
                    ),
                    "cardinality": basic_stats["unique_count"]
                    / basic_stats["non_null_count"]
                    if basic_stats and basic_stats["non_null_count"] > 0
                    else None,
                }

    async def sample_data(
        self,
        table_name: str,
        schema: str = DEFAULT_SCHEMA,
        limit: int = DEFAULT_SAMPLE_LIMIT,
    ) -> Sequence[Dict[str, Any]]:
        """Get a sample of data from a table"""
        async with self.get_connection() as conn:
            async with conn.cursor() as cur:
                query = sql.SQL("SELECT * FROM {schema}.{table} LIMIT %s").format(
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table_name),
                )
                # execute() accepts Composed at runtime, but type stubs don't reflect this
                await cur.execute(query, (limit,))  # type: ignore[arg-type]
                return cast(Sequence[Dict[str, Any]], await cur.fetchall())

    async def execute_query(
        self, query: str, limit: Optional[int] = DEFAULT_QUERY_LIMIT
    ) -> Dict[str, Any]:
        """Execute a read-only SQL query"""
        # Basic SQL injection prevention - ensure it's a SELECT query
        query_upper = query.upper().strip()
        if not query_upper.startswith("SELECT") and not query_upper.startswith("WITH"):
            raise ValueError("Only SELECT and WITH queries are allowed")

        # Add LIMIT if not present and limit is specified
        if limit and "LIMIT" not in query_upper:
            query = f"{query} LIMIT {limit}"

        async with self.get_connection() as conn:
            async with conn.cursor() as cur:
                start_time = datetime.now()
                # execute() typing issue with cursor generic parameters
                await cur.execute(query)  # type: ignore[arg-type]
                rows = await cur.fetchall()
                execution_time = (datetime.now() - start_time).total_seconds()

                # Get column information
                columns = (
                    [desc.name for desc in cur.description] if cur.description else []
                )

                return {
                    "query": query,
                    "columns": columns,
                    "row_count": len(rows),
                    "execution_time_seconds": execution_time,
                    "data": rows[:100]
                    if len(rows) > 100
                    else rows,  # Limit response size
                    "truncated": len(rows) > 100,
                    "total_rows": len(rows),
                }

    async def get_table_relationships(
        self, schema: str = DEFAULT_SCHEMA
    ) -> Sequence[Dict[str, Any]]:
        """Get foreign key relationships between tables"""
        async with self.get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        tc.table_schema as source_schema,
                        tc.table_name as source_table,
                        kcu.column_name as source_column,
                        ccu.table_schema as target_schema,
                        ccu.table_name as target_table,
                        ccu.column_name as target_column,
                        tc.constraint_name
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage AS ccu
                        ON ccu.constraint_name = tc.constraint_name
                        AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                        AND tc.table_schema = %s
                    ORDER BY tc.table_name, tc.constraint_name
                """,
                    (schema,),
                )
                return cast(Sequence[Dict[str, Any]], await cur.fetchall())

    async def profile_database(self) -> Dict[str, Any]:
        """Get a high-level profile of the entire database"""
        async with self.get_connection() as conn:
            async with conn.cursor() as cur:
                # Database size
                await cur.execute("""
                    SELECT
                        current_database() as database_name,
                        pg_size_pretty(pg_database_size(current_database())) as database_size
                """)
                db_info = await cur.fetchone()

                # Schema statistics
                await cur.execute("""
                    SELECT
                        table_schema,
                        COUNT(*) as table_count,
                        SUM(pg_total_relation_size(pgc.oid)) as total_size
                    FROM information_schema.tables t
                    JOIN pg_class pgc ON pgc.relname = t.table_name
                    JOIN pg_namespace pgn ON pgn.oid = pgc.relnamespace
                        AND pgn.nspname = t.table_schema
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                    GROUP BY table_schema
                    ORDER BY total_size DESC
                """)
                schema_stats_raw = await cur.fetchall()

                # Format sizes - convert to mutable dicts
                schema_stats = [
                    {
                        **stat,  # DictRow can be unpacked directly
                        "total_size_pretty": self._format_bytes(
                            int(stat["total_size"] or 0)
                        ),
                    }
                    for stat in schema_stats_raw
                ]

                # Top 10 largest tables
                await cur.execute("""
                    SELECT
                        schemaname || '.' || tablename as table_name,
                        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
                        pg_total_relation_size(schemaname||'.'||tablename) as size_bytes
                    FROM pg_tables
                    WHERE schemaname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                    ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
                    LIMIT 10
                """)
                largest_tables = await cur.fetchall()

                return {
                    "database": db_info,
                    "schemas": schema_stats,
                    "largest_tables": largest_tables,
                    "profile_timestamp": datetime.now().isoformat(),
                }

    def _format_bytes(self, bytes_value: int) -> str:
        """Format bytes to human readable string"""
        value = float(bytes_value)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if value < 1024.0:
                return f"{value:.2f} {unit}"
            value /= 1024.0
        return f"{value:.2f} PB"


# Create MCP server
app = Server("pg-da")
analyst: Optional[PostgresAnalyst] = None


@app.list_resources()
async def list_resources() -> list[Resource]:
    """List available database resources"""
    if not analyst:
        return []

    try:
        schemas = await analyst.list_schemas()
        resources = []

        for schema in schemas:
            schema_name = str(schema["schema_name"])
            schema_owner = str(schema["schema_owner"])
            resources.append(
                Resource(
                    uri=AnyUrl(f"postgres://schema/{schema_name}"),  # type: ignore[call-arg]
                    name=f"Schema: {schema_name}",
                    description=f"PostgreSQL schema owned by {schema_owner}",
                    mimeType="application/json",
                )
            )

        return resources
    except Exception as e:
        logger.error(f"Error listing resources: {e}")
        return []


# MCP decorator type hints don't match runtime signature requirements
@app.read_resource()  # type: ignore[arg-type]
async def read_resource(uri: str) -> str:
    """Read database resource information"""
    if not analyst:
        raise ValueError("Database connection not initialized")

    if uri.startswith("postgres://schema/"):
        schema_name = uri.replace("postgres://schema/", "")
        tables = await analyst.list_tables(schema_name)
        return json.dumps({"schema": schema_name, "tables": tables}, default=str)

    raise ValueError(f"Unknown resource URI: {uri}")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available database analysis tools"""
    return [
        Tool(
            name="list_schemas",
            description="List all schemas in the PostgreSQL database",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="list_tables",
            description="List all tables in a schema with metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "schema": {
                        "type": "string",
                        "description": f"Schema name (default: {DEFAULT_SCHEMA})",
                        "default": DEFAULT_SCHEMA,
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="describe_table",
            description="Get detailed information about a table including columns, indexes, and constraints",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Name of the table",
                    },
                    "schema": {
                        "type": "string",
                        "description": f"Schema name (default: {DEFAULT_SCHEMA})",
                        "default": DEFAULT_SCHEMA,
                    },
                },
                "required": ["table_name"],
            },
        ),
        Tool(
            name="analyze_column",
            description="Analyze a specific column with statistics and distribution",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Name of the table",
                    },
                    "column_name": {
                        "type": "string",
                        "description": "Name of the column",
                    },
                    "schema": {
                        "type": "string",
                        "description": f"Schema name (default: {DEFAULT_SCHEMA})",
                        "default": DEFAULT_SCHEMA,
                    },
                },
                "required": ["table_name", "column_name"],
            },
        ),
        Tool(
            name="sample_data",
            description="Get a sample of data from a table",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Name of the table",
                    },
                    "schema": {
                        "type": "string",
                        "description": f"Schema name (default: {DEFAULT_SCHEMA})",
                        "default": DEFAULT_SCHEMA,
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Number of rows to sample (default: {DEFAULT_SAMPLE_LIMIT})",
                        "default": DEFAULT_SAMPLE_LIMIT,
                        "minimum": 1,
                        "maximum": MAX_SAMPLE_LIMIT,
                    },
                },
                "required": ["table_name"],
            },
        ),
        Tool(
            name="execute_query",
            description="Execute a read-only SQL query (SELECT or WITH statements only)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL query to execute (must be SELECT or WITH)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Maximum number of rows to return (default: {DEFAULT_QUERY_LIMIT})",
                        "default": DEFAULT_QUERY_LIMIT,
                        "minimum": 1,
                        "maximum": MAX_QUERY_LIMIT,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_table_relationships",
            description="Get foreign key relationships between tables in a schema",
            inputSchema={
                "type": "object",
                "properties": {
                    "schema": {
                        "type": "string",
                        "description": f"Schema name (default: {DEFAULT_SCHEMA})",
                        "default": DEFAULT_SCHEMA,
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="profile_database",
            description="Get a high-level profile of the entire database",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a database analysis tool"""
    if not analyst:
        raise ValueError("Database connection not initialized")

    # Create local reference for type narrowing in lambdas
    db = analyst

    try:
        # Map tool names to analyst methods and their parameter extraction logic
        tool_handlers = {
            "list_schemas": lambda: db.list_schemas(),
            "list_tables": lambda: db.list_tables(
                schema=arguments.get("schema", DEFAULT_SCHEMA)
            ),
            "describe_table": lambda: db.describe_table(
                table_name=arguments["table_name"],
                schema=arguments.get("schema", DEFAULT_SCHEMA),
            ),
            "analyze_column": lambda: db.analyze_column(
                table_name=arguments["table_name"],
                column_name=arguments["column_name"],
                schema=arguments.get("schema", DEFAULT_SCHEMA),
            ),
            "sample_data": lambda: db.sample_data(
                table_name=arguments["table_name"],
                schema=arguments.get("schema", DEFAULT_SCHEMA),
                limit=arguments.get("limit", DEFAULT_SAMPLE_LIMIT),
            ),
            "execute_query": lambda: db.execute_query(
                query=arguments["query"],
                limit=arguments.get("limit", DEFAULT_QUERY_LIMIT),
            ),
            "get_table_relationships": lambda: db.get_table_relationships(
                schema=arguments.get("schema", DEFAULT_SCHEMA)
            ),
            "profile_database": lambda: db.profile_database(),
        }

        if name not in tool_handlers:
            raise ValueError(f"Unknown tool: {name}")

        result = await tool_handlers[name]()
        return [
            TextContent(type="text", text=json.dumps(result, default=str, indent=2))
        ]
    except Exception as e:
        logger.error(f"Error executing tool {name}: {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def initialize_analyst(connection_string: Optional[str] = None) -> None:
    """Initialize the PostgreSQL connection"""
    global analyst

    try:
        analyst = PostgresAnalyst(connection_string)
        # Test the connection
        async with analyst.get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
        logger.info("PostgreSQL connection initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize PostgreSQL connection: {e}")
        raise


async def main():
    """Run the MCP server"""
    from mcp.server.stdio import stdio_server

    # Initialize the analyst with environment variable
    await initialize_analyst()

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
