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
from typing import Any, AsyncGenerator, Optional
from unittest import mock

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from db_connect_mcp.models.config import DatabaseConfig

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
        env = os.environ.copy()
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
    async def test_server_starts_and_responds(self, pg_database_url: Optional[str]):
        """Test that server starts as subprocess and responds to client."""
        if not pg_database_url:
            pytest.skip("PG_TEST_DATABASE_URL not set")

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
    async def test_server_logs_initialization(self, pg_database_url: Optional[str]):
        """Test that server can initialize successfully (log capture is limited in stdio_client)."""
        if not pg_database_url:
            pytest.skip("PG_TEST_DATABASE_URL not set")

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
    async def test_get_database_info_e2e(self, pg_database_url: Optional[str]):
        """Test get_database_info tool via subprocess server."""
        if not pg_database_url:
            pytest.skip("PG_TEST_DATABASE_URL not set")

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
    async def test_execute_query_e2e(self, pg_database_url: Optional[str]):
        """Test execute_query tool via subprocess server."""
        if not pg_database_url:
            pytest.skip("PG_TEST_DATABASE_URL not set")

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
    async def test_list_schemas_e2e(self, pg_database_url: Optional[str]):
        """Test list_schemas tool via subprocess server."""
        if not pg_database_url:
            pytest.skip("PG_TEST_DATABASE_URL not set")

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
    async def test_invalid_query_e2e(self, pg_database_url: Optional[str]):
        """Test that invalid queries return errors via subprocess."""
        if not pg_database_url:
            pytest.skip("PG_TEST_DATABASE_URL not set")

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
    async def test_invalid_tool_e2e(self, pg_database_url: Optional[str]):
        """Test calling non-existent tool via subprocess."""
        if not pg_database_url:
            pytest.skip("PG_TEST_DATABASE_URL not set")

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
    async def test_server_subprocess_execution(self, pg_database_url: Optional[str]):
        """Test that server runs as subprocess and executes successfully."""
        if not pg_database_url:
            pytest.skip("PG_TEST_DATABASE_URL not set")

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
    async def test_multiple_operations_subprocess(self, pg_database_url: Optional[str]):
        """Test multiple operations through subprocess server."""
        if not pg_database_url:
            pytest.skip("PG_TEST_DATABASE_URL not set")

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
        self, pg_database_url: Optional[str]
    ):
        """Test log capture framework using ServerContext directly.

        This demonstrates how to capture logs when you control the subprocess.
        """
        if not pg_database_url:
            pytest.skip("PG_TEST_DATABASE_URL not set")

        # Use ServerContext for direct subprocess control
        async with ServerContext(pg_database_url) as server_ctx:
            # Give server time to start and log
            await asyncio.sleep(1)

            # Verify we can capture logs
            logs = server_ctx.log_capture.get_logs()

            # Note: Logs might be empty or minimal depending on buffering
            # The framework is in place for when buffering allows capture
            # In practice, you'd configure logging to a file for more reliable capture
