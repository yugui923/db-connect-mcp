"""MCP Protocol-Level Server Testing

Tests the DatabaseMCPServer at the protocol level using MCP SDK's ClientSession.
This validates:
- MCP server initialization and lifecycle
- Tool registration based on database capabilities
- Tool input validation (JSON schema)
- Tool call handling through the MCP protocol
- Response serialization to MCP TextContent format
- Error handling at the protocol layer

Run with: pytest tests/test_mcp_server.py -v

Note: These tests use in-memory streams that cannot be serialized for parallel
execution. Run these tests serially (without -n flag) or they will be grouped
in the same worker.
"""

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from db_connect_mcp.models.config import DatabaseConfig
from db_connect_mcp.server import DatabaseMCPServer
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.types import TextContent

# Mark all tests in this module to run in the same xdist worker
# This is necessary because MemoryObjectSendStream cannot be serialized
pytestmark = [pytest.mark.postgresql, pytest.mark.integration, pytest.mark.xdist_group(name="mcp_server")]


class MCPServerTestHelper:
    """Helper class for MCP server testing.

    This provides utilities for creating in-memory MCP client-server connections
    for protocol-level testing without needing stdio or network transport.
    """

    @staticmethod
    async def create_test_server_and_client(
        config: DatabaseConfig,
    ) -> tuple[DatabaseMCPServer, ClientSession]:
        """Create a test server and connected client for testing.

        This creates an in-memory connection between a DatabaseMCPServer
        and a ClientSession for protocol-level testing.

        Args:
            config: Database configuration

        Returns:
            Tuple of (server, client) ready for testing

        Note:
            The caller is responsible for calling server.cleanup() when done.
        """
        import anyio

        # Create server
        server = DatabaseMCPServer(config)
        await server.initialize()

        # Register server handlers (mimic what happens in main())
        @server.server.list_tools()
        async def list_tools():
            """List available tools."""
            tools = [
                server._create_get_database_info_tool(),
                server._create_list_schemas_tool(),
                server._create_list_tables_tool(),
                server._create_describe_table_tool(),
                server._create_execute_query_tool(),
                server._create_sample_data_tool(),
            ]

            # Add conditional tools
            if server.adapter.capabilities.foreign_keys:
                tools.append(server._create_get_relationships_tool())

            if server.adapter.capabilities.advanced_stats:
                tools.append(server._create_analyze_column_tool())

            if server.adapter.capabilities.explain_plans:
                tools.append(server._create_explain_query_tool())

            if server.adapter.capabilities.profiling:
                tools.append(server._create_profile_database_tool())

            return tools

        @server.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            """Handle tool calls."""
            handlers = {
                "get_database_info": server.handle_get_database_info,
                "list_schemas": server.handle_list_schemas,
                "list_tables": server.handle_list_tables,
                "describe_table": server.handle_describe_table,
                "execute_query": server.handle_execute_query,
                "sample_data": server.handle_sample_data,
                "get_table_relationships": server.handle_get_relationships,
                "analyze_column": server.handle_analyze_column,
                "explain_query": server.handle_explain_query,
                "profile_database": server.handle_profile_database,
            }

            handler = handlers.get(name)
            if handler is None:
                raise ValueError(f"Unknown tool: {name}")

            return await handler(arguments)

        # Create in-memory streams for testing
        # These replace stdio streams for testing
        # Create paired streams using anyio's factory function
        server_to_client_send, server_to_client_recv = anyio.create_memory_object_stream()
        client_to_server_send, client_to_server_recv = anyio.create_memory_object_stream()

        # Create client session
        client = ClientSession(
            server_to_client_recv,
            client_to_server_send,
        )

        # Start server in background
        async def run_server():
            """Run the MCP server."""
            async with server_to_client_send, client_to_server_recv:
                await server.server.run(
                    client_to_server_recv,
                    server_to_client_send,
                    server.server.create_initialization_options(),
                )

        # Start server task
        server_task = anyio.create_task_group()
        await server_task.__aenter__()
        server_task.start_soon(run_server)

        # Initialize client
        await client.__aenter__()
        await client.initialize()

        return server, client

    @staticmethod
    def parse_text_content(content: list[TextContent]) -> dict[str, Any]:
        """Parse TextContent response to dict.

        Args:
            content: List of TextContent from tool response

        Returns:
            Parsed JSON data as dict

        Raises:
            ValueError: If the content is an error message, not JSON
        """
        assert len(content) == 1
        assert content[0].type == "text"
        text = content[0].text

        # If it looks like an error message (not JSON), raise a clear error
        if not text.strip().startswith(('{', '[')):
            raise ValueError(f"Response is not JSON (likely an error): {text}")

        return json.loads(text)

    @staticmethod
    def check_and_parse_response(response) -> dict[str, Any]:
        """Check response for errors and parse content.

        Args:
            response: CallToolResult from client.call_tool()

        Returns:
            Parsed JSON data as dict

        Raises:
            pytest.skip: If response contains a database connection error
            AssertionError: If response contains unexpected error
        """
        # Check for error responses
        if response.isError:
            error_text = str(response.content[0].text if response.content else "Unknown error")

            # Skip test on connection errors (network, DNS, etc.)
            if any(err in error_text.lower() for err in ["errno", "connection", "resolution", "refused"]):
                pytest.skip(f"Database connection error: {error_text}")

            # For other errors, fail the test
            raise AssertionError(f"Tool call returned error: {error_text}")

        # Parse and return successful response
        return MCPServerTestHelper.check_and_parse_response(response)


class TestMCPServerInitialization:
    """Test MCP server initialization and lifecycle."""

    @pytest.mark.asyncio
    async def test_server_initialization(self, pg_config: DatabaseConfig):
        """Test server initializes correctly with database connection."""
        server = DatabaseMCPServer(pg_config)

        # Before initialization
        assert server.inspector is None
        assert server.executor is None
        assert server.analyzer is None

        await server.initialize()

        # After initialization
        assert server.inspector is not None
        assert server.executor is not None
        assert server.analyzer is not None
        assert server.adapter is not None

        # Cleanup
        await server.cleanup()

    @pytest.mark.asyncio
    async def test_server_cleanup(self, pg_config: DatabaseConfig):
        """Test server cleans up resources properly."""
        server = DatabaseMCPServer(pg_config)
        await server.initialize()

        # Should not raise
        await server.cleanup()

        # Connection should be disposed
        # Verify we can't get a connection after cleanup
        with pytest.raises(Exception):
            async with server.connection.get_connection() as conn:
                pass


class TestMCPToolRegistration:
    """Test MCP tool registration based on database capabilities."""

    @pytest.mark.asyncio
    async def test_list_tools_basic(self, pg_config: DatabaseConfig):
        """Test that basic tools are always registered."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # Get tools via protocol
            tools_response = await client.list_tools()
            tools = tools_response.tools

            # Basic tools should always be present
            tool_names = {tool.name for tool in tools}
            assert "get_database_info" in tool_names
            assert "list_schemas" in tool_names
            assert "list_tables" in tool_names
            assert "describe_table" in tool_names
            assert "execute_query" in tool_names
            assert "sample_data" in tool_names

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_list_tools_conditional_postgresql(self, pg_config: DatabaseConfig):
        """Test PostgreSQL-specific tools are registered."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            tools_response = await client.list_tools()
            tools = tools_response.tools
            tool_names = {tool.name for tool in tools}

            # PostgreSQL supports these features
            assert "get_table_relationships" in tool_names  # foreign_keys
            assert "analyze_column" in tool_names  # advanced_stats
            assert "explain_query" in tool_names  # explain_plans
            assert "profile_database" in tool_names  # profiling

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_tool_input_schemas(self, pg_config: DatabaseConfig):
        """Test that all tools have valid input schemas."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            tools_response = await client.list_tools()
            tools = tools_response.tools

            for tool in tools:
                # Every tool should have an input schema
                assert tool.inputSchema is not None
                assert "type" in tool.inputSchema
                assert tool.inputSchema["type"] == "object"
                assert "properties" in tool.inputSchema
                assert "required" in tool.inputSchema

                # Validate required fields
                required = tool.inputSchema["required"]
                assert isinstance(required, list)

                # All required fields should be in properties
                properties = tool.inputSchema["properties"]
                for field in required:
                    assert field in properties

        finally:
            await server.cleanup()


class TestMCPToolCalls:
    """Test MCP tool calls through the protocol layer."""

    @pytest.mark.asyncio
    async def test_get_database_info_protocol(self, pg_config: DatabaseConfig):
        """Test get_database_info via MCP protocol."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # Call tool via protocol
            response = await client.call_tool("get_database_info", arguments={})

            # Parse response (skips on connection errors)
            data = MCPServerTestHelper.check_and_parse_response(response)

            # Validate data structure
            assert "name" in data
            assert "dialect" in data
            assert "version" in data
            assert "capabilities" in data
            assert data["dialect"] == "postgresql"
            assert "PostgreSQL" in data["version"] or "postgres" in data["version"].lower()

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_list_schemas_protocol(self, pg_config: DatabaseConfig):
        """Test list_schemas via MCP protocol."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            response = await client.call_tool("list_schemas", arguments={})
            data = MCPServerTestHelper.check_and_parse_response(response)

            # Should return list of schemas
            assert isinstance(data, list)
            assert len(data) > 0

            # Validate schema structure
            schema = data[0]
            assert "name" in schema
            assert "table_count" in schema

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_list_tables_protocol(self, pg_config: DatabaseConfig):
        """Test list_tables via MCP protocol."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            response = await client.call_tool(
                "list_tables",
                arguments={"schema": "public", "include_views": True},
            )
            data = MCPServerTestHelper.check_and_parse_response(response)

            # Should return list of tables
            assert isinstance(data, list)

            if len(data) > 0:
                table = data[0]
                assert "name" in table
                assert "schema" in table
                assert "table_type" in table

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_execute_query_protocol(self, pg_config: DatabaseConfig):
        """Test execute_query via MCP protocol."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            response = await client.call_tool(
                "execute_query",
                arguments={"query": "SELECT 1 as test_col", "limit": 10},
            )
            data = MCPServerTestHelper.check_and_parse_response(response)

            # Validate query result structure
            assert "query" in data
            assert "row_count" in data
            assert "columns" in data
            assert "rows" in data
            assert "execution_time_ms" in data

            assert data["row_count"] == 1
            assert data["columns"] == ["test_col"]
            assert data["rows"][0]["test_col"] == 1

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_sample_data_protocol(self, pg_config: DatabaseConfig):
        """Test sample_data via MCP protocol with JSON serialization."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # First get a table to sample from
            tables_response = await client.call_tool("list_tables", arguments={})
            tables = MCPServerTestHelper.check_and_parse_response(tables_response)

            if not tables:
                pytest.skip("No tables available for testing")

            table_name = tables[0]["name"]

            # Sample data
            response = await client.call_tool(
                "sample_data",
                arguments={"table": table_name, "schema": "public", "limit": 5},
            )
            data = MCPServerTestHelper.check_and_parse_response(response)

            # Validate structure
            assert "row_count" in data
            assert "columns" in data
            assert "rows" in data

            # Critical: Verify JSON serialization works
            # This was a major bug - data with special types failed to serialize
            for row in data["rows"]:
                # Should be able to serialize to JSON
                json.dumps(row)

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_tool_call_missing_required_argument(self, pg_config: DatabaseConfig):
        """Test that missing required arguments return proper errors."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # describe_table requires 'table' argument
            response = await client.call_tool("describe_table", arguments={})

            # MCP returns error responses, doesn't raise exceptions
            # Check if the response indicates an error
            assert response.isError or "table" in str(response.content).lower()

        finally:
            await server.cleanup()


class TestMCPErrorHandling:
    """Test error handling at the MCP protocol level."""

    @pytest.mark.asyncio
    async def test_invalid_tool_name(self, pg_config: DatabaseConfig):
        """Test calling a non-existent tool."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            response = await client.call_tool("non_existent_tool", arguments={})

            # MCP returns error response for invalid tool
            assert response.isError
            # Error message should mention the tool name
            error_text = str(response.content[0].text if response.content else "")
            assert "non_existent_tool" in error_text or "unknown" in error_text.lower()

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_invalid_query_readonly_enforcement(self, pg_config: DatabaseConfig):
        """Test that write queries are rejected."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            response = await client.call_tool(
                "execute_query",
                arguments={"query": "DROP TABLE users", "limit": 10},
            )

            # MCP returns error response for invalid queries
            assert response.isError
            # Error message should mention read-only or not allowed
            error_text = str(response.content[0].text if response.content else "").lower()
            assert "read-only" in error_text or "not allowed" in error_text or "drop" in error_text

        finally:
            await server.cleanup()


class TestMCPDataSerialization:
    """Test data serialization through the MCP protocol."""

    @pytest.mark.asyncio
    async def test_timestamp_serialization(self, pg_config: DatabaseConfig):
        """Test that timestamp data serializes correctly via MCP protocol."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            response = await client.call_tool(
                "execute_query",
                arguments={
                    "query": "SELECT NOW() as ts, CURRENT_DATE as dt, CURRENT_TIME as tm",
                    "limit": 1,
                },
            )
            data = MCPServerTestHelper.check_and_parse_response(response)

            # Verify we got results
            assert data["row_count"] == 1
            row = data["rows"][0]

            # All should be strings (ISO format)
            assert isinstance(row["ts"], str)
            assert isinstance(row["dt"], str)
            assert isinstance(row["tm"], str)

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_special_types_serialization(self, pg_config: DatabaseConfig):
        """Test PostgreSQL special types serialize via MCP protocol."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            response = await client.call_tool(
                "execute_query",
                arguments={
                    "query": "SELECT '192.168.1.1'::inet as ip, gen_random_uuid() as id",
                    "limit": 1,
                },
            )
            data = MCPServerTestHelper.check_and_parse_response(response)

            row = data["rows"][0]

            # Both should be strings
            assert isinstance(row["ip"], str)
            assert isinstance(row["id"], str)
            assert "192.168.1.1" in row["ip"]

        finally:
            await server.cleanup()


class TestMCPServerIntegration:
    """Integration tests for full MCP server workflow."""

    @pytest.mark.asyncio
    async def test_full_workflow_explore_database(self, pg_config: DatabaseConfig):
        """Test a complete workflow: get info -> list schemas -> list tables -> describe table."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # 1. Get database info
            info_response = await client.call_tool("get_database_info", arguments={})
            info = MCPServerTestHelper.check_and_parse_response(info_response)
            assert "dialect" in info

            # 2. List schemas
            schemas_response = await client.call_tool("list_schemas", arguments={})
            schemas = MCPServerTestHelper.check_and_parse_response(schemas_response)
            assert len(schemas) > 0

            # 3. List tables in first schema
            schema_name = schemas[0]["name"]
            tables_response = await client.call_tool(
                "list_tables", arguments={"schema": schema_name}
            )
            tables = MCPServerTestHelper.check_and_parse_response(tables_response)

            if tables:
                # 4. Describe first table
                table_name = tables[0]["name"]
                describe_response = await client.call_tool(
                    "describe_table",
                    arguments={"table": table_name, "schema": schema_name},
                )
                table_info = MCPServerTestHelper.parse_text_content(
                    describe_response.content
                )

                assert table_info["name"] == table_name
                assert "columns" in table_info
                assert len(table_info["columns"]) > 0

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_full_workflow_query_and_analyze(self, pg_config: DatabaseConfig):
        """Test workflow: query data -> analyze results."""
        server, client = await MCPServerTestHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # 1. Execute a query
            query_response = await client.call_tool(
                "execute_query",
                arguments={"query": "SELECT 1 as num, 'text' as txt", "limit": 10},
            )
            result = MCPServerTestHelper.check_and_parse_response(query_response)

            assert result["row_count"] == 1
            assert result["columns"] == ["num", "txt"]

            # 2. Get execution plan
            if server.adapter.capabilities.explain_plans:
                explain_response = await client.call_tool(
                    "explain_query",
                    arguments={"query": "SELECT 1", "analyze": False},
                )
                plan = MCPServerTestHelper.check_and_parse_response(explain_response)

                assert "query" in plan
                assert "plan" in plan

        finally:
            await server.cleanup()
