"""Multi-database MCP Server

A Model Context Protocol (MCP) server providing database analysis and querying
capabilities for PostgreSQL, MySQL, and ClickHouse databases.
"""

import asyncio
import json
import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import TextContent, Tool

from db_connect_mcp.adapters import create_adapter
from db_connect_mcp.core import (
    DatabaseConnection,
    MetadataInspector,
    QueryExecutor,
    StatisticsAnalyzer,
)
from db_connect_mcp.models.config import DatabaseConfig

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Response size limits (in characters) for MCP tool responses
# These limits prevent context window exhaustion while preserving useful information
MAX_RESPONSE_DATABASE_INFO = 2000  # Basic database metadata
MAX_RESPONSE_PROFILE_DATABASE = 2000  # High-level database overview
MAX_RESPONSE_LIST_SCHEMAS = 3000  # Schema listings
MAX_RESPONSE_GET_RELATIONSHIPS = 3000  # Foreign key relationships
MAX_RESPONSE_SAMPLE_DATA = 5000  # Table data preview
MAX_RESPONSE_LIST_TABLES = 5000  # Table listings with metadata
MAX_RESPONSE_ANALYZE_COLUMN = 5000  # Column statistics
MAX_RESPONSE_DESCRIBE_TABLE = 8000  # Detailed table structure
MAX_RESPONSE_EXPLAIN_QUERY = 8000  # Query execution plans
MAX_RESPONSE_EXECUTE_QUERY = 10000  # Query results (up to 1000 rows)


def truncate_json_response(data: str, max_length: int) -> str:
    """
    Truncate JSON response to a maximum length while preserving JSON structure.

    Args:
        data: JSON string to truncate
        max_length: Maximum length in characters

    Returns:
        Truncated JSON string with truncation notice if needed
    """
    if len(data) <= max_length:
        return data

    # Calculate space for truncation message
    truncation_msg = f"\n\n... [Response truncated: {len(data)} chars -> {max_length} chars to preserve context window]"
    available_length = max_length - len(truncation_msg)

    if available_length < 100:
        # If we have very little space, just return a simple message
        return json.dumps(
            {
                "error": "Response too large",
                "original_size": len(data),
                "limit": max_length,
                "message": "Response exceeds size limit. Please use more specific filters or query directly.",
            },
            indent=2,
        )

    # Truncate the data and add message
    truncated = data[:available_length]

    # Try to truncate at a reasonable point (end of a line)
    last_newline = truncated.rfind("\n")
    if (
        last_newline > available_length * 0.8
    ):  # Only use newline if it's in the last 20%
        truncated = truncated[:last_newline]

    return truncated + truncation_msg


class DatabaseMCPServer:
    """MCP server for multi-database operations."""

    def __init__(self, config: DatabaseConfig):
        """
        Initialize database MCP server.

        Args:
            config: Database configuration
        """
        self.config = config
        self.connection = DatabaseConnection(config)
        self.adapter = create_adapter(config)
        self.inspector: Optional[MetadataInspector] = None
        self.executor: Optional[QueryExecutor] = None
        self.analyzer: Optional[StatisticsAnalyzer] = None
        self.server = Server("db-connect-mcp")

    async def initialize(self) -> None:
        """Initialize all components."""
        await self.connection.initialize()

        self.inspector = MetadataInspector(self.connection, self.adapter)
        self.executor = QueryExecutor(self.connection, self.adapter)
        self.analyzer = StatisticsAnalyzer(self.connection, self.adapter)

        # Register MCP tool handlers
        await self._register_tools()

        logger.info(
            f"Initialized {self.config.dialect} MCP server "
            f"({len(self.adapter.capabilities.get_supported_features())} features)"
        )

    async def _register_tools(self) -> None:
        """Register MCP tools based on database capabilities."""
        # Note: Tools are registered via the list_tools decorator, not add_tool
        # This method is kept for initializing any tool-related state
        pass

    def _create_get_database_info_tool(self) -> Tool:
        """Create get_database_info tool."""
        return Tool(
            name="get_database_info",
            description="Get database information including version, size, and capabilities",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        )

    def _create_list_schemas_tool(self) -> Tool:
        """Create list_schemas tool."""
        return Tool(
            name="list_schemas",
            description="List all schemas/databases in the database instance",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        )

    def _create_list_tables_tool(self) -> Tool:
        """Create list_tables tool."""
        return Tool(
            name="list_tables",
            description="List all tables and views in a schema",
            inputSchema={
                "type": "object",
                "properties": {
                    "schema": {
                        "type": "string",
                        "description": "Schema name (optional, uses default if not specified)",
                    },
                    "include_views": {
                        "type": "boolean",
                        "description": "Whether to include views (default: true)",
                        "default": True,
                    },
                },
                "required": [],
            },
        )

    def _create_describe_table_tool(self) -> Tool:
        """Create describe_table tool."""
        return Tool(
            name="describe_table",
            description="Get comprehensive table information including columns, indexes, and constraints",
            inputSchema={
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "Table name"},
                    "schema": {
                        "type": "string",
                        "description": "Schema name (optional)",
                    },
                },
                "required": ["table"],
            },
        )

    def _create_execute_query_tool(self) -> Tool:
        """Create execute_query tool."""
        return Tool(
            name="execute_query",
            description="Execute a read-only SQL query (SELECT, WITH, EXPLAIN)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL query to execute",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of rows to return (default: 1000)",
                        "default": 1000,
                    },
                },
                "required": ["query"],
            },
        )

    def _create_sample_data_tool(self) -> Tool:
        """Create sample_data tool."""
        return Tool(
            name="sample_data",
            description="Sample data from a table efficiently",
            inputSchema={
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "Table name"},
                    "schema": {
                        "type": "string",
                        "description": "Schema name (optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of rows to sample (default: 100)",
                        "default": 100,
                    },
                },
                "required": ["table"],
            },
        )

    def _create_get_relationships_tool(self) -> Tool:
        """Create get_table_relationships tool."""
        return Tool(
            name="get_table_relationships",
            description="Get foreign key relationships for a table",
            inputSchema={
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "Table name"},
                    "schema": {
                        "type": "string",
                        "description": "Schema name (optional)",
                    },
                },
                "required": ["table"],
            },
        )

    def _create_analyze_column_tool(self) -> Tool:
        """Create analyze_column tool."""
        return Tool(
            name="analyze_column",
            description="Get comprehensive column statistics including percentiles and distributions",
            inputSchema={
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "Table name"},
                    "column": {"type": "string", "description": "Column name"},
                    "schema": {
                        "type": "string",
                        "description": "Schema name (optional)",
                    },
                },
                "required": ["table", "column"],
            },
        )

    def _create_explain_query_tool(self) -> Tool:
        """Create explain_query tool."""
        return Tool(
            name="explain_query",
            description="Get query execution plan to analyze performance",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL query to explain",
                    },
                    "analyze": {
                        "type": "boolean",
                        "description": "Whether to execute the query (EXPLAIN ANALYZE)",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        )

    def _create_profile_database_tool(self) -> Tool:
        """Create profile_database tool."""
        return Tool(
            name="profile_database",
            description="Get database-wide profiling information (size, table counts, etc.)",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        )

    # Tool handlers
    async def handle_get_database_info(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle get_database_info request."""
        assert self.inspector is not None

        version = await self.connection.get_version()

        # Sanitize connection URL (remove password)
        url_parts = self.config.url.split("@")
        if len(url_parts) > 1:
            sanitized_url = f"<credentials>@{url_parts[-1]}"
        else:
            sanitized_url = self.config.url

        from db_connect_mcp.models.database import DatabaseInfo

        db_info = DatabaseInfo(
            name=self.config.url.split("/")[-1],  # Extract DB name from URL
            dialect=self.config.dialect,
            version=version,
            size_bytes=None,
            schema_count=None,
            table_count=None,
            capabilities=self.adapter.capabilities,
            server_encoding=None,
            collation=None,
            connection_url=sanitized_url,
            read_only=self.config.read_only,
        )

        response = json.dumps(db_info.model_dump(), indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_DATABASE_INFO),
            )
        ]

    async def handle_list_schemas(self, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle list_schemas request."""
        assert self.inspector is not None

        schemas = await self.inspector.get_schemas()
        schemas_data = [s.model_dump() for s in schemas]

        response = json.dumps(schemas_data, indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_LIST_SCHEMAS),
            )
        ]

    async def handle_list_tables(self, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle list_tables request."""
        assert self.inspector is not None

        schema = arguments.get("schema")
        include_views = arguments.get("include_views", True)

        tables = await self.inspector.get_tables(schema, include_views)
        tables_data = [t.model_dump() for t in tables]

        response = json.dumps(tables_data, indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_LIST_TABLES),
            )
        ]

    async def handle_describe_table(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle describe_table request."""
        assert self.inspector is not None

        table = arguments["table"]
        schema = arguments.get("schema")

        table_info = await self.inspector.describe_table(table, schema)

        response = json.dumps(table_info.model_dump(), indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_DESCRIBE_TABLE),
            )
        ]

    async def handle_execute_query(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle execute_query request."""
        assert self.executor is not None

        query = arguments["query"]
        limit = arguments.get("limit", 1000)

        result = await self.executor.execute_query(query, limit=limit)

        response = json.dumps(result.model_dump(), indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_EXECUTE_QUERY),
            )
        ]

    async def handle_sample_data(self, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle sample_data request."""
        assert self.executor is not None

        table = arguments["table"]
        schema = arguments.get("schema")
        limit = arguments.get("limit", 100)

        result = await self.executor.sample_data(table, schema, limit)

        response = json.dumps(result.model_dump(), indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_SAMPLE_DATA),
            )
        ]

    async def handle_get_relationships(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle get_table_relationships request."""
        assert self.inspector is not None

        table = arguments["table"]
        schema = arguments.get("schema")

        relationships = await self.inspector.get_relationships(table, schema)
        relationships_data = [r.model_dump() for r in relationships]

        response = json.dumps(relationships_data, indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_GET_RELATIONSHIPS),
            )
        ]

    async def handle_analyze_column(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle analyze_column request."""
        assert self.analyzer is not None

        table = arguments["table"]
        column = arguments["column"]
        schema = arguments.get("schema")

        stats = await self.analyzer.analyze_column(table, column, schema)

        response = json.dumps(stats.model_dump(), indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_ANALYZE_COLUMN),
            )
        ]

    async def handle_explain_query(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle explain_query request."""
        assert self.executor is not None

        query = arguments["query"]
        analyze = arguments.get("analyze", False)

        plan = await self.executor.explain_query(query, analyze)

        response = json.dumps(plan.model_dump(), indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_EXPLAIN_QUERY),
            )
        ]

    async def handle_profile_database(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle profile_database request."""
        assert self.inspector is not None

        # Extract database name from configuration
        database_name = self.config.url.split("/")[-1].split("?")[0]

        async with self.connection.get_connection() as conn:
            # Use adapter to generate database profile
            profile = await self.adapter.profile_database(conn, database_name)

            response = json.dumps(profile.model_dump(), indent=2)
            return [
                TextContent(
                    type="text",
                    text=truncate_json_response(
                        response, MAX_RESPONSE_PROFILE_DATABASE
                    ),
                )
            ]

    async def cleanup(self) -> None:
        """Cleanup resources."""
        await self.connection.dispose()
        logger.info("Database MCP server cleaned up")


async def main() -> None:
    """Main entry point for the MCP server."""
    # Get database URL from environment
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable must be set")

    # Create configuration
    config = DatabaseConfig(url=database_url)

    # Create and initialize server
    mcp_server = DatabaseMCPServer(config)

    try:
        await mcp_server.initialize()

        # Register list_tools handler
        @mcp_server.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available tools based on database capabilities."""
            tools = [
                mcp_server._create_get_database_info_tool(),
                mcp_server._create_list_schemas_tool(),
                mcp_server._create_list_tables_tool(),
                mcp_server._create_describe_table_tool(),
                mcp_server._create_execute_query_tool(),
                mcp_server._create_sample_data_tool(),
            ]

            # Add conditional tools
            if mcp_server.adapter.capabilities.foreign_keys:
                tools.append(mcp_server._create_get_relationships_tool())

            if mcp_server.adapter.capabilities.advanced_stats:
                tools.append(mcp_server._create_analyze_column_tool())

            if mcp_server.adapter.capabilities.explain_plans:
                tools.append(mcp_server._create_explain_query_tool())

            if mcp_server.adapter.capabilities.profiling:
                tools.append(mcp_server._create_profile_database_tool())

            return tools

        # Register tool call handlers
        @mcp_server.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            """Handle tool calls."""
            handlers = {
                "get_database_info": mcp_server.handle_get_database_info,
                "list_schemas": mcp_server.handle_list_schemas,
                "list_tables": mcp_server.handle_list_tables,
                "describe_table": mcp_server.handle_describe_table,
                "execute_query": mcp_server.handle_execute_query,
                "sample_data": mcp_server.handle_sample_data,
                "get_table_relationships": mcp_server.handle_get_relationships,
                "analyze_column": mcp_server.handle_analyze_column,
                "explain_query": mcp_server.handle_explain_query,
                "profile_database": mcp_server.handle_profile_database,
            }

            handler = handlers.get(name)
            if handler is None:
                raise ValueError(f"Unknown tool: {name}")

            return await handler(arguments)

        # Run the server
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await mcp_server.server.run(
                read_stream,
                write_stream,
                mcp_server.server.create_initialization_options(),
            )

    finally:
        await mcp_server.cleanup()


def cli_entry() -> None:
    """
    Synchronous entry point for console script.

    This function is called by the 'db-connect-mcp' console script.
    It sets up the event loop and runs the async main() function.
    """
    # Windows-specific event loop policy
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    cli_entry()
