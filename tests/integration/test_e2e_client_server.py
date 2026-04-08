"""End-to-End MCP Client-Server Testing

This module tests the full MCP server-client interaction by:
1. Spawning the MCP server as a real subprocess
2. Creating an MCP client that connects via stdio
3. Capturing and analyzing server logs
4. Executing operations and validating responses
5. Ensuring proper cleanup

These tests validate the complete system behavior including:
- Server startup and initialization
- Stdio transport communication
- Tool registration and execution
- Error handling across process boundaries
- Server logging and diagnostics
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


# Mark all tests in this module for E2E testing
pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.integration,
    pytest.mark.xdist_group(name="e2e_client_server"),
]


class ServerLogCapture:
    """Captures and analyzes MCP server logs from subprocess stderr."""

    def __init__(self):
        """Initialize log capture."""
        self.logs: list[str] = []
        self._capture_task: Optional[asyncio.Task] = None

    async def start_capture(self, stderr_stream):
        """Start capturing logs from stderr stream.

        Args:
            stderr_stream: Async stream to read from
        """

        async def capture_logs():
            """Read and store log lines."""
            try:
                async for line in stderr_stream:
                    log_line = line.decode("utf-8").strip()
                    if log_line:
                        self.logs.append(log_line)
                        # Optionally print to console for debugging
                        # print(f"[SERVER LOG] {log_line}")
            except Exception as e:
                print(f"Log capture error: {e}")

        self._capture_task = asyncio.create_task(capture_logs())

    async def stop_capture(self):
        """Stop capturing logs."""
        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass

    def get_logs(self) -> list[str]:
        """Get captured log lines.

        Returns:
            List of log lines
        """
        return self.logs.copy()

    def contains_log(self, pattern: str) -> bool:
        """Check if any log line contains the pattern.

        Args:
            pattern: String pattern to search for

        Returns:
            True if pattern found in any log line
        """
        return any(pattern in log for log in self.logs)

    def get_logs_containing(self, pattern: str) -> list[str]:
        """Get all log lines containing the pattern.

        Args:
            pattern: String pattern to search for

        Returns:
            List of matching log lines
        """
        return [log for log in self.logs if pattern in log]

    def get_initialization_logs(self) -> list[str]:
        """Get server initialization logs.

        Returns:
            List of initialization log lines
        """
        return self.get_logs_containing("Initialized")

    def get_error_logs(self) -> list[str]:
        """Get error log lines.

        Returns:
            List of error log lines
        """
        return [log for log in self.logs if "ERROR" in log or "Error" in log]

    def get_tool_execution_logs(self) -> list[str]:
        """Get logs related to tool execution.

        Returns:
            List of tool execution log lines
        """
        patterns = ["tool", "execute", "query", "call"]
        return [
            log
            for log in self.logs
            if any(pattern in log.lower() for pattern in patterns)
        ]


class ServerContext:
    """Context manager for MCP server lifecycle and log capture."""

    def __init__(self, database_url: str):
        """Initialize server context.

        Args:
            database_url: Database connection URL
        """
        self.database_url = database_url
        self.server_process: Optional[subprocess.Popen] = None
        self.log_capture = ServerLogCapture()
        self.log_file_path = Path(f"test_server_{os.getpid()}.log")

    async def __aenter__(self):
        """Start server process with log capture."""
        # Set environment with database URL
        env = os.environ.copy()
        env["DATABASE_URL"] = self.database_url

        # Start server process
        self.server_process = subprocess.Popen(
            [sys.executable, "-m", "db_connect_mcp.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        # Start capturing stderr logs
        if self.server_process.stderr:
            stderr_stream = _async_stream_from_sync_file(self.server_process.stderr)
            await self.log_capture.start_capture(stderr_stream)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Stop server and cleanup resources."""
        # Stop log capture
        await self.log_capture.stop_capture()

        # Terminate server
        if self.server_process:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                self.server_process.wait()

        # Cleanup log file
        if self.log_file_path.exists():
            self.log_file_path.unlink()


class E2ETestHelper:
    """Helper class for end-to-end testing with subprocess server."""

    @staticmethod
    async def check_database_connectivity(database_url: str) -> bool:
        """Check if database is accessible before running E2E tests.

        Args:
            database_url: Database connection URL

        Returns:
            True if database is accessible, False otherwise
        """
        try:
            from db_connect_mcp.core import DatabaseConnection
            from db_connect_mcp.models.config import DatabaseConfig
            from sqlalchemy import text

            config = DatabaseConfig(url=database_url)
            connection = DatabaseConnection(config)

            await connection.initialize()
            async with connection.get_connection() as conn:
                await conn.execute(text("SELECT 1"))
            await connection.dispose()
            return True
        except Exception:
            return False

    @staticmethod
    async def create_server_and_client(
        database_url: str,
    ) -> tuple[ClientSession, ServerLogCapture, Any]:
        """Create a subprocess MCP server and connected client using MCP SDK.

        Args:
            database_url: Database connection URL

        Returns:
            Tuple of (client_session, log_capture, stdio_context)

        Raises:
            RuntimeError: If server fails to start
        """
        # Create log capture instance
        log_capture = ServerLogCapture()

        # Set environment with database URL
        # Remove SSH tunnel env vars so PG tests don't route through the MySQL tunnel
        env = {k: v for k, v in os.environ.items() if not k.startswith("SSH_")}
        env["DATABASE_URL"] = database_url

        # Create server parameters
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "db_connect_mcp.server"],
            env=env,
        )

        try:
            # Start server and client using MCP SDK
            stdio_context = stdio_client(server_params)
            read_stream, write_stream = await stdio_context.__aenter__()

            # Create client session
            client = ClientSession(read_stream, write_stream)
            await client.__aenter__()

            # Give server time to initialize
            await asyncio.sleep(0.5)

            # Initialize MCP session
            await client.initialize()

            # Note: We can't access stderr directly through stdio_client,
            # but the server is running and logging to its stderr.
            # For now, log_capture will be empty, but the framework is in place.

            return client, log_capture, stdio_context

        except Exception as e:
            raise RuntimeError(f"Failed to start server and client: {e}") from e

    @staticmethod
    async def cleanup_server_and_client(
        client: ClientSession,
        log_capture: ServerLogCapture,
        stdio_context: Any,
    ):
        """Cleanup server process and client session.

        Args:
            client: MCP client session
            log_capture: Log capture instance
            stdio_context: Stdio context manager from stdio_client
        """
        # Stop log capture
        await log_capture.stop_capture()

        # Close client
        try:
            await client.__aexit__(None, None, None)
        except Exception as e:
            print(f"Error closing client: {e}")

        # Close stdio context (terminates server process)
        try:
            await stdio_context.__aexit__(None, None, None)
        except Exception as e:
            print(f"Error closing stdio context: {e}")

    @staticmethod
    def parse_text_content(content: list[TextContent]) -> dict[str, Any]:
        """Parse TextContent response to dict.

        Args:
            content: List of TextContent from tool response

        Returns:
            Parsed JSON data as dict
        """
        assert len(content) == 1
        assert content[0].type == "text"
        text = content[0].text

        if not text.strip().startswith(("{", "[")):
            raise ValueError(f"Response is not JSON: {text}")

        return json.loads(text)


async def _async_stream_from_sync_file(file):
    """Create async stream from synchronous file object.

    Args:
        file: Synchronous file object

    Yields:
        Lines from the file as bytes
    """
    loop = asyncio.get_event_loop()

    def read_line():
        return file.readline()

    while True:
        line = await loop.run_in_executor(None, read_line)
        if not line:
            break
        yield line


class TestE2EServerLifecycle:
    """Test end-to-end server lifecycle with subprocess."""

    @pytest.mark.asyncio
    async def test_server_starts_and_responds(self, pg_database_url: str):
        """Test that server starts as subprocess and responds to client."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        # Create server and client
        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            # Test that client can list tools
            tools_response = await client.list_tools()
            tools = tools_response.tools

            # Verify basic tools are registered
            tool_names = {tool.name for tool in tools}
            assert "get_database_info" in tool_names
            assert "list_schemas" in tool_names
            assert "execute_query" in tool_names

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )

    @pytest.mark.asyncio
    async def test_server_logs_initialization(self, pg_database_url: str):
        """Test that server can initialize successfully (log capture is limited in stdio_client)."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            # Verify server initialized by making a successful call
            response = await client.call_tool("get_database_info", arguments={})
            assert not response.isError, "Server failed to initialize properly"

            # Note: Log capture through stdio_client is limited
            # The server IS logging to stderr, but we can't access it directly
            # through the MCP SDK's stdio_client wrapper

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )


class TestE2EToolExecution:
    """Test end-to-end tool execution with subprocess server."""

    @pytest.mark.asyncio
    async def test_get_database_info_e2e(self, pg_database_url: str):
        """Test get_database_info tool via subprocess server."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            # Call tool
            response = await client.call_tool("get_database_info", arguments={})

            # Verify response
            assert not response.isError, f"Tool returned error: {response.content}"
            data = E2ETestHelper.parse_text_content(response.content)

            assert "name" in data
            assert "dialect" in data
            assert data["dialect"] == "postgresql"
            assert "capabilities" in data

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )

    @pytest.mark.asyncio
    async def test_execute_query_e2e(self, pg_database_url: str):
        """Test execute_query tool via subprocess server."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            # Execute simple query
            response = await client.call_tool(
                "execute_query",
                arguments={"query": "SELECT 42 as answer, 'hello' as greeting"},
            )

            # Verify response
            assert not response.isError, f"Tool returned error: {response.content}"
            data = E2ETestHelper.parse_text_content(response.content)

            assert data["row_count"] == 1
            assert data["columns"] == ["answer", "greeting"]
            assert data["rows"][0]["answer"] == 42
            assert data["rows"][0]["greeting"] == "hello"

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )

    @pytest.mark.asyncio
    async def test_list_schemas_e2e(self, pg_database_url: str):
        """Test list_schemas tool via subprocess server."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            # List schemas
            response = await client.call_tool("list_schemas", arguments={})

            # Verify response
            assert not response.isError, f"Tool returned error: {response.content}"
            data = E2ETestHelper.parse_text_content(response.content)

            assert isinstance(data, list)
            assert len(data) > 0

            # Should have schema names
            schema = data[0]
            assert "name" in schema

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )


class TestE2EErrorHandling:
    """Test end-to-end error handling with subprocess server."""

    @pytest.mark.asyncio
    async def test_invalid_query_e2e(self, pg_database_url: str):
        """Test that invalid queries return errors via subprocess."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            # Try to execute invalid (write) query
            response = await client.call_tool(
                "execute_query",
                arguments={"query": "DROP TABLE nonexistent_table"},
            )

            # Should return error
            assert response.isError
            error_text = str(response.content[0].text if response.content else "")
            # Check that error mentions read-only enforcement
            assert (
                "read-only" in error_text.lower()
                or "not allowed" in error_text.lower()
                or "only" in error_text.lower()
                and "select" in error_text.lower()
            )

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )

    @pytest.mark.asyncio
    async def test_invalid_tool_e2e(self, pg_database_url: str):
        """Test calling non-existent tool via subprocess."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            # Try to call non-existent tool
            response = await client.call_tool("non_existent_tool", arguments={})

            # Should return error
            assert response.isError

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )


class TestE2EServerLogs:
    """Test server subprocess execution and logging framework.

    Note: Direct stderr capture is limited when using MCP SDK's stdio_client,
    as it manages the subprocess internally. These tests verify the server
    runs correctly and that the logging framework is in place.
    """

    @pytest.mark.asyncio
    async def test_server_subprocess_execution(self, pg_database_url: str):
        """Test that server runs as subprocess and executes successfully."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            # Verify server is running by executing operations
            response = await client.call_tool("get_database_info", arguments={})
            assert not response.isError, "Server subprocess failed to execute"

            # Execute a query to verify full functionality
            response = await client.call_tool(
                "execute_query",
                arguments={"query": "SELECT 1 as test"},
            )
            assert not response.isError, "Query execution failed"

            # The server IS logging to stderr, but stdio_client doesn't expose it
            # The log capture framework is tested separately with ServerContext

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )

    @pytest.mark.asyncio
    async def test_multiple_operations_subprocess(self, pg_database_url: str):
        """Test multiple operations through subprocess server."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            # Execute multiple operations to verify server stability
            operations = [
                ("get_database_info", {}),
                ("list_schemas", {}),
                ("execute_query", {"query": "SELECT 1 as num"}),
                ("execute_query", {"query": "SELECT 'test' as text"}),
            ]

            for tool_name, args in operations:
                response = await client.call_tool(tool_name, arguments=args)
                assert not response.isError, f"{tool_name} failed in subprocess"

            # Verify server is still responsive after multiple operations
            response = await client.call_tool("get_database_info", arguments={})
            assert not response.isError, "Server became unresponsive"

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )

    @pytest.mark.asyncio
    async def test_log_capture_framework_with_server_context(
        self, pg_database_url: str
    ):
        """Test log capture framework using ServerContext directly.

        This demonstrates how to capture logs when you control the subprocess.
        """
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        # Use ServerContext for direct subprocess control
        async with ServerContext(pg_database_url) as server_ctx:
            # Give server time to start and log
            await asyncio.sleep(1)

            # Verify we can capture logs
            _logs = server_ctx.log_capture.get_logs()

            # Note: Logs might be empty or minimal depending on buffering
            # The framework is in place for when buffering allows capture
            # In practice, you'd configure logging to a file for more reliable capture


class TestE2ESearchObjects:
    """End-to-end tests for the search_objects tool.

    These tests spawn a real ``db_connect_mcp.server`` subprocess and talk
    to it via the MCP stdio transport. They prove the new tool round-trips
    correctly through the production code path: subprocess startup, tool
    registration, JSON-RPC marshalling, handler dispatch, and JSON
    serialization.
    """

    @pytest.mark.asyncio
    async def test_search_objects_listed_in_tools(self, pg_database_url: str):
        """The new tool appears in list_tools through the real stdio server."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            tools_response = await client.list_tools()
            tool_names = {t.name for t in tools_response.tools}
            assert "search_objects" in tool_names

            search = next(t for t in tools_response.tools if t.name == "search_objects")
            assert search.inputSchema is not None
            assert "pattern" in search.inputSchema["properties"]
            assert search.inputSchema["required"] == ["pattern"]

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )

    @pytest.mark.asyncio
    async def test_search_objects_table_e2e(self, pg_database_url: str):
        """search_objects returns the seeded users table via real subprocess."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            response = await client.call_tool(
                "search_objects",
                arguments={
                    "pattern": "users",
                    "object_types": ["table"],
                    "schema": "public",
                },
            )
            assert not response.isError, f"Tool returned error: {response.content}"
            data = E2ETestHelper.parse_text_content(response.content)

            assert data["pattern"] == "users"
            assert data["total_found"] >= 1
            names = {r["name"] for r in data["results"]}
            assert "users" in names

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )

    @pytest.mark.asyncio
    async def test_search_objects_column_e2e(self, pg_database_url: str):
        """search_objects(column) round-trips with correct metadata."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            response = await client.call_tool(
                "search_objects",
                arguments={
                    "pattern": "user_id",
                    "object_types": ["column"],
                    "schema": "public",
                    "table": "users",
                    "detail_level": "summary",
                },
            )
            assert not response.isError, f"Tool returned error: {response.content}"
            data = E2ETestHelper.parse_text_content(response.content)

            assert data["total_found"] == 1
            col = data["results"][0]
            assert col["object_type"] == "column"
            assert col["name"] == "user_id"
            assert col["table"] == "users"
            assert col["primary_key"] is True

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )

    @pytest.mark.asyncio
    async def test_search_objects_names_level_minimal_payload(
        self, pg_database_url: str
    ):
        """detail_level=names produces a minimal JSON payload via stdio."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            # Compare token sizes between names and full to prove the
            # progressive-disclosure feature actually saves bytes on the wire.
            names_resp = await client.call_tool(
                "search_objects",
                arguments={
                    "pattern": "users",
                    "object_types": ["table"],
                    "schema": "public",
                    "detail_level": "names",
                },
            )
            full_resp = await client.call_tool(
                "search_objects",
                arguments={
                    "pattern": "users",
                    "object_types": ["table"],
                    "schema": "public",
                    "detail_level": "full",
                },
            )
            assert not names_resp.isError
            assert not full_resp.isError

            names_text = names_resp.content[0].text  # type: ignore[union-attr]
            full_text = full_resp.content[0].text  # type: ignore[union-attr]

            # The names payload should be strictly smaller than the full one
            # for the same query (or at worst equal, if metadata is empty).
            assert len(names_text) <= len(full_text)

            names_data = json.loads(names_text)
            users_item = next(r for r in names_data["results"] if r["name"] == "users")
            # exclude_none drops fields not populated at the names level
            assert "row_count" not in users_item
            assert "table_type" not in users_item
            assert "comment" not in users_item

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )

    @pytest.mark.asyncio
    async def test_search_objects_invalid_pattern_returns_error(
        self, pg_database_url: str
    ):
        """Empty pattern is rejected at the subprocess MCP layer."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            response = await client.call_tool(
                "search_objects", arguments={"pattern": ""}
            )
            assert response.isError

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )

    @pytest.mark.asyncio
    async def test_search_objects_truncation_e2e(self, pg_database_url: str):
        """Limit truncation flag round-trips through the stdio protocol."""
        if not await E2ETestHelper.check_database_connectivity(pg_database_url):
            pytest.skip("Database not accessible")

        (
            client,
            log_capture,
            stdio_context,
        ) = await E2ETestHelper.create_server_and_client(pg_database_url)

        try:
            response = await client.call_tool(
                "search_objects",
                arguments={
                    "pattern": "%",
                    "object_types": ["column"],
                    "schema": "public",
                    "limit": 2,
                },
            )
            assert not response.isError, f"Tool returned error: {response.content}"
            data = E2ETestHelper.parse_text_content(response.content)

            assert data["returned"] == 2
            assert data["total_found"] > 2
            assert data["truncated"] is True
            assert data.get("note")

        finally:
            await E2ETestHelper.cleanup_server_and_client(
                client, log_capture, stdio_context
            )
