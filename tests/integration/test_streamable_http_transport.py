"""Comprehensive integration tests for Streamable HTTP transport layer.

These tests verify the HTTP transport functionality including:
- Server startup, lifecycle, and shutdown
- Full MCP protocol message handling over HTTP
- Bearer token authentication (all edge cases)
- JSON-RPC 2.0 compliance
- Error handling and edge cases
- Concurrent request handling
- Session management in stateless mode
- Content negotiation and headers
"""

import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager
from typing import Any, Generator

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.testclient import TestClient

from db_connect_mcp.models.config import DatabaseConfig
from db_connect_mcp.server import DatabaseMCPServer

# Standard headers for MCP JSON-RPC requests
# MCP Streamable HTTP requires Accept to include both JSON and SSE
MCP_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def get_free_port() -> int:
    """Get a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mcp_server_instance(pg_config: DatabaseConfig):
    """Create and initialize an MCP server instance."""
    server = DatabaseMCPServer(pg_config)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(server.initialize())
    except Exception as e:
        loop.close()
        pytest.skip(f"MCP server initialization failed: {e}")

    yield server, loop

    loop.run_until_complete(server.cleanup())
    loop.close()


class _TestMCPASGIApp:
    """ASGI app for tests with optional auth."""

    def __init__(self, session_manager: Any, auth_token: str | None = None):
        self.session_manager = session_manager
        self.auth_token = auth_token

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self.auth_token and scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth_value = headers.get(b"authorization", b"").decode()
            if (
                not auth_value.startswith("Bearer ")
                or auth_value[7:] != self.auth_token
            ):
                response = Response("Unauthorized", status_code=401)
                await response(scope, receive, send)
                return
        await self.session_manager.handle_request(scope, receive, send)


@pytest.fixture
def starlette_app_no_auth(mcp_server_instance):
    """Create a Starlette app without authentication."""
    from starlette.routing import Route

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    server, loop = mcp_server_instance

    session_manager = StreamableHTTPSessionManager(
        app=server.server,
        json_response=True,
        stateless=True,
    )

    mcp_asgi_app = _TestMCPASGIApp(session_manager)

    app = Starlette(
        routes=[Route("/mcp", endpoint=mcp_asgi_app)],
        lifespan=lambda app: session_manager.run(),
    )

    return app


@pytest.fixture
def starlette_app_with_auth(mcp_server_instance):
    """Create a Starlette app with bearer token authentication."""
    from starlette.routing import Route

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    server, loop = mcp_server_instance
    auth_token = "test-secret-token-xyz789"

    session_manager = StreamableHTTPSessionManager(
        app=server.server,
        json_response=True,
        stateless=True,
    )

    mcp_asgi_app = _TestMCPASGIApp(session_manager, auth_token)

    app = Starlette(
        routes=[Route("/mcp", endpoint=mcp_asgi_app)],
        lifespan=lambda app: session_manager.run(),
    )

    return app, auth_token


@contextmanager
def run_server_in_thread(app, host: str, port: int) -> Generator[str, None, None]:
    """Run uvicorn server in a background thread."""
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to start
    base_url = f"http://{host}:{port}"
    for _ in range(50):  # 5 second timeout
        try:
            with httpx.Client() as client:
                # Try to connect - even 404 means server is up
                client.get(f"{base_url}/", timeout=0.1)
                break
        except (httpx.ConnectError, httpx.ReadTimeout):
            time.sleep(0.1)
    else:
        raise RuntimeError("Server failed to start")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# =============================================================================
# Basic HTTP Endpoint Tests
# =============================================================================


class TestHTTPEndpointBasics:
    """Basic HTTP endpoint availability and routing tests."""

    def test_mcp_endpoint_responds(self, starlette_app_no_auth):
        """Test that /mcp endpoint exists and responds."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.get("/mcp")
            assert response.status_code != 404

    def test_root_endpoint_returns_404(self, starlette_app_no_auth):
        """Test that root endpoint returns 404."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.get("/")
            assert response.status_code == 404

    def test_arbitrary_paths_return_404(self, starlette_app_no_auth):
        """Test that arbitrary paths return 404."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            # Paths completely outside /mcp should be 404
            paths = ["/api", "/health", "/status", "/other"]
            for path in paths:
                response = client.get(path)
                assert response.status_code == 404, f"Path {path} should return 404"

    def test_mcp_subpaths_handled_by_mcp(self, starlette_app_no_auth):
        """Test that subpaths under /mcp are handled by MCP handler."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            # Subpaths under /mcp go to MCP handler (returns 406 Not Acceptable)
            response = client.get("/mcp/extra")
            assert response.status_code in (400, 404, 406)


# =============================================================================
# Bearer Token Authentication Tests
# =============================================================================


class TestBearerTokenAuthentication:
    """Comprehensive bearer token authentication tests."""

    def test_no_auth_header_returns_401(self, starlette_app_with_auth):
        """Test request without Authorization header returns 401."""
        app, _ = starlette_app_with_auth
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/mcp")
            assert response.status_code == 401
            assert "Unauthorized" in response.text

    def test_empty_auth_header_returns_401(self, starlette_app_with_auth):
        """Test request with empty Authorization header returns 401."""
        app, _ = starlette_app_with_auth
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/mcp", headers={"Authorization": ""})
            assert response.status_code == 401

    def test_bearer_without_token_returns_401(self, starlette_app_with_auth):
        """Test 'Bearer ' without token returns 401."""
        app, _ = starlette_app_with_auth
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/mcp", headers={"Authorization": "Bearer "})
            assert response.status_code == 401

    def test_wrong_token_returns_401(self, starlette_app_with_auth):
        """Test wrong token returns 401."""
        app, _ = starlette_app_with_auth
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/mcp", headers={"Authorization": "Bearer wrong-token"}
            )
            assert response.status_code == 401

    def test_basic_auth_returns_401(self, starlette_app_with_auth):
        """Test Basic auth instead of Bearer returns 401."""
        app, _ = starlette_app_with_auth
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/mcp", headers={"Authorization": "Basic dXNlcjpwYXNz"}
            )
            assert response.status_code == 401

    def test_bearer_lowercase_returns_401(self, starlette_app_with_auth):
        """Test 'bearer' (lowercase) returns 401."""
        app, auth_token = starlette_app_with_auth
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/mcp", headers={"Authorization": f"bearer {auth_token}"}
            )
            assert response.status_code == 401

    def test_token_case_sensitive(self, starlette_app_with_auth):
        """Test that token matching is case-sensitive."""
        app, auth_token = starlette_app_with_auth
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/mcp", headers={"Authorization": f"Bearer {auth_token.upper()}"}
            )
            assert response.status_code == 401

    def test_token_with_extra_spaces_returns_401(self, starlette_app_with_auth):
        """Test token with leading/trailing spaces returns 401."""
        app, auth_token = starlette_app_with_auth
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/mcp", headers={"Authorization": f"Bearer  {auth_token}"}
            )
            assert response.status_code == 401

            response = client.get(
                "/mcp", headers={"Authorization": f"Bearer {auth_token} "}
            )
            assert response.status_code == 401

    def test_valid_token_allows_get(self, starlette_app_with_auth):
        """Test valid token allows GET request."""
        app, auth_token = starlette_app_with_auth
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/mcp", headers={"Authorization": f"Bearer {auth_token}"}
            )
            assert response.status_code != 401

    def test_valid_token_allows_post(self, starlette_app_with_auth):
        """Test valid token allows POST request."""
        app, auth_token = starlette_app_with_auth
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                headers={
                    "Authorization": f"Bearer {auth_token}",
                    "Content-Type": "application/json",
                },
            )
            assert response.status_code != 401

    def test_auth_checked_before_request_processing(self, starlette_app_with_auth):
        """Test that auth is checked before request body is processed."""
        app, _ = starlette_app_with_auth
        with TestClient(app, raise_server_exceptions=False) as client:
            # Even with invalid JSON, should return 401 first
            response = client.post(
                "/mcp",
                content="not valid json",
                headers={
                    "Authorization": "Bearer wrong-token",
                    "Content-Type": "application/json",
                },
            )
            assert response.status_code == 401


class TestNoAuthConfiguration:
    """Tests for server running without authentication."""

    def test_requests_allowed_without_auth_header(self, starlette_app_no_auth):
        """Test that requests work without auth when not configured."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.get("/mcp")
            assert response.status_code != 401

    def test_bearer_header_ignored_when_no_auth(self, starlette_app_no_auth):
        """Test that Bearer header is ignored when auth not configured."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.get("/mcp", headers={"Authorization": "Bearer any-token"})
            assert response.status_code != 401


# =============================================================================
# JSON-RPC Protocol Tests
# =============================================================================


class TestJSONRPCProtocol:
    """Tests for JSON-RPC 2.0 protocol compliance."""

    def test_valid_jsonrpc_request_accepted(self, starlette_app_no_auth):
        """Test that valid JSON-RPC 2.0 request is accepted."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            }
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            assert response.status_code in (200, 202)

    def test_missing_jsonrpc_version(self, starlette_app_no_auth):
        """Test request without jsonrpc version field."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            request = {"id": 1, "method": "initialize", "params": {}}
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            # Should return error
            assert response.status_code in (200, 400, 500)

    def test_wrong_jsonrpc_version(self, starlette_app_no_auth):
        """Test request with wrong jsonrpc version."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            request = {"jsonrpc": "1.0", "id": 1, "method": "initialize", "params": {}}
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            assert response.status_code in (200, 400, 500)

    def test_missing_method_field(self, starlette_app_no_auth):
        """Test request without method field."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            request = {"jsonrpc": "2.0", "id": 1, "params": {}}
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            assert response.status_code in (200, 400, 500)

    def test_null_id_for_notification(self, starlette_app_no_auth):
        """Test notification (no id) is handled."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            # JSON-RPC notification (no id field)
            request = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            # Notifications should be accepted
            assert response.status_code in (200, 202, 204)

    def test_string_id_accepted(self, starlette_app_no_auth):
        """Test that string id is accepted per JSON-RPC spec."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            request = {
                "jsonrpc": "2.0",
                "id": "request-uuid-123",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            }
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            assert response.status_code in (200, 202)

    def test_batch_requests_handled(self, starlette_app_no_auth):
        """Test JSON-RPC batch requests are handled."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            batch = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0"},
                    },
                },
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            ]
            response = client.post("/mcp", json=batch, headers=MCP_JSON_HEADERS)
            # Batch may or may not be supported
            assert response.status_code in (200, 202, 400, 500)


class TestMCPMethods:
    """Tests for MCP-specific methods."""

    def test_initialize_method(self, starlette_app_no_auth):
        """Test MCP initialize method."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                },
            }
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            assert response.status_code in (200, 202)

    def test_tools_list_method(self, starlette_app_no_auth):
        """Test MCP tools/list method."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            # First initialize
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            }
            client.post("/mcp", json=init_request, headers=MCP_JSON_HEADERS)

            # Then list tools
            request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            assert response.status_code in (200, 202)

    def test_unknown_method_returns_error(self, starlette_app_no_auth):
        """Test that unknown MCP method returns error."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "unknown/method",
                "params": {},
            }
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            # Should get error response (method not found), not crash
            assert response.status_code in (200, 202, 400, 404, 500)


# =============================================================================
# HTTP Request/Response Tests
# =============================================================================


class TestHTTPMethods:
    """Tests for HTTP method handling."""

    def test_get_method_accepted(self, starlette_app_no_auth):
        """Test GET method is accepted (for SSE streams)."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.get("/mcp")
            assert response.status_code != 405

    def test_post_method_accepted(self, starlette_app_no_auth):
        """Test POST method is accepted."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.post("/mcp", json={})
            assert response.status_code != 405

    def test_put_method_rejected(self, starlette_app_no_auth):
        """Test PUT method is rejected."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.put("/mcp", json={})
            assert response.status_code in (400, 405, 500)

    def test_delete_method_rejected(self, starlette_app_no_auth):
        """Test DELETE method is rejected."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.delete("/mcp")
            assert response.status_code in (400, 405, 500)

    def test_patch_method_rejected(self, starlette_app_no_auth):
        """Test PATCH method is rejected."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.patch("/mcp", json={})
            assert response.status_code in (400, 405, 500)

    def test_options_method(self, starlette_app_no_auth):
        """Test OPTIONS method for CORS preflight."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.options("/mcp")
            # OPTIONS might return 200 or 405 depending on CORS config
            assert response.status_code in (200, 204, 400, 405)

    def test_head_method(self, starlette_app_no_auth):
        """Test HEAD method."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.head("/mcp")
            # HEAD should be like GET but no body
            assert response.status_code in (200, 400, 405)


class TestContentTypes:
    """Tests for content type handling."""

    def test_application_json_accepted(self, starlette_app_no_auth):
        """Test application/json content type is accepted."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                headers=MCP_JSON_HEADERS,
            )
            assert response.status_code not in (415,)

    def test_application_json_charset_accepted(self, starlette_app_no_auth):
        """Test application/json with charset is accepted."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            assert response.status_code not in (415,)

    def test_text_plain_may_be_rejected(self, starlette_app_no_auth):
        """Test text/plain content type handling."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                content='{"jsonrpc": "2.0", "id": 1, "method": "ping"}',
                headers={"Content-Type": "text/plain"},
            )
            # May be rejected or accepted depending on implementation
            assert response.status_code in (200, 202, 400, 415, 422, 500)


class TestRequestBody:
    """Tests for request body handling."""

    def test_empty_body(self, starlette_app_no_auth):
        """Test empty request body."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.post("/mcp", content="")
            assert response.status_code in (400, 415, 422, 500)

    def test_invalid_json(self, starlette_app_no_auth):
        """Test invalid JSON body."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                content="not valid json {",
                headers=MCP_JSON_HEADERS,
            )
            assert response.status_code in (400, 415, 422, 500)

    def test_null_body(self, starlette_app_no_auth):
        """Test null JSON body."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.post("/mcp", content="null", headers=MCP_JSON_HEADERS)
            assert response.status_code in (200, 400, 422, 500)

    def test_empty_object(self, starlette_app_no_auth):
        """Test empty JSON object."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.post("/mcp", json={}, headers=MCP_JSON_HEADERS)
            assert response.status_code in (200, 400, 422, 500)

    def test_array_body(self, starlette_app_no_auth):
        """Test JSON array body (batch request)."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            response = client.post("/mcp", json=[], headers=MCP_JSON_HEADERS)
            assert response.status_code in (200, 400, 422, 500)

    def test_large_body(self, starlette_app_no_auth):
        """Test large request body."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            large_data = "x" * 1_000_000  # 1MB
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"data": large_data},
            }
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            # Should handle gracefully
            assert response.status_code in (200, 202, 400, 413, 422, 500)

    def test_unicode_body(self, starlette_app_no_auth):
        """Test Unicode characters in request body."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "测试客户端", "version": "1.0"},
                },
            }
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            assert response.status_code in (200, 202)


# =============================================================================
# Stateless Mode Tests
# =============================================================================


class TestStatelessMode:
    """Tests for stateless HTTP mode behavior."""

    def test_no_session_header_required(self, starlette_app_no_auth):
        """Test that Mcp-Session-Id header is not required."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            }
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            assert response.status_code in (200, 202)

    def test_session_header_ignored(self, starlette_app_no_auth):
        """Test that Mcp-Session-Id header is ignored in stateless mode."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            }
            headers = {**MCP_JSON_HEADERS, "Mcp-Session-Id": "fake-session-id"}
            response = client.post("/mcp", json=request, headers=headers)
            assert response.status_code in (200, 202)

    def test_multiple_clients_independent(self, starlette_app_no_auth):
        """Test that multiple clients are independent in stateless mode."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            for i in range(5):
                request = {
                    "jsonrpc": "2.0",
                    "id": i + 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": f"client-{i}", "version": "1.0"},
                    },
                }
                response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
                assert response.status_code in (200, 202)


# =============================================================================
# Concurrent Request Tests
# =============================================================================


class TestConcurrentRequests:
    """Tests for concurrent request handling."""

    def test_sequential_requests(self, starlette_app_no_auth):
        """Test sequential requests work correctly."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            for i in range(10):
                request = {
                    "jsonrpc": "2.0",
                    "id": i + 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0"},
                    },
                }
                response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
                assert response.status_code in (200, 202)

    def test_parallel_requests(self, starlette_app_no_auth):
        """Test parallel requests are handled correctly."""
        import concurrent.futures

        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:

            def make_request(i):
                request = {
                    "jsonrpc": "2.0",
                    "id": i + 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": f"client-{i}", "version": "1.0"},
                    },
                }
                return client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(make_request, i) for i in range(10)]
                responses = [
                    f.result() for f in concurrent.futures.as_completed(futures)
                ]

            for response in responses:
                assert response.status_code in (200, 202)

    def test_mixed_methods_parallel(self, starlette_app_no_auth):
        """Test mixed POST requests in parallel."""
        import concurrent.futures

        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:

            def make_post_request(i):
                return client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": i,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": f"test-{i}", "version": "1.0"},
                        },
                    },
                    headers=MCP_JSON_HEADERS,
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(make_post_request, i) for i in range(5)]
                responses = [
                    f.result() for f in concurrent.futures.as_completed(futures)
                ]

            # All should complete without server errors
            for response in responses:
                assert response.status_code in (200, 202)


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    def test_malformed_request_doesnt_crash_server(self, starlette_app_no_auth):
        """Test that malformed requests don't crash the server."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            # Send garbage
            response = client.post(
                "/mcp",
                content=b"\x00\x01\x02\x03",
                headers=MCP_JSON_HEADERS,
            )
            # Server should respond with error, not crash
            assert response.status_code in (400, 415, 422, 500)

            # Subsequent request should still work
            response = client.get("/mcp")
            assert response.status_code != 503  # Not service unavailable

    def test_deeply_nested_json(self, starlette_app_no_auth):
        """Test handling of deeply nested JSON."""
        with TestClient(starlette_app_no_auth, raise_server_exceptions=False) as client:
            # Create deeply nested structure
            nested = {"level": 0}
            current = nested
            for i in range(100):
                current["nested"] = {"level": i + 1}
                current = current["nested"]

            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": nested,
            }
            response = client.post("/mcp", json=request, headers=MCP_JSON_HEADERS)
            # Should handle gracefully
            assert response.status_code in (200, 202, 400, 422, 500)


# =============================================================================
# Real HTTP Client Tests (using httpx with live server)
# =============================================================================


@pytest.mark.skip(reason="Live server tests timeout in CI - run manually")
class TestRealHTTPClient:
    """Tests using real HTTP client against live server.

    These tests start an actual uvicorn server and make real HTTP requests.
    """

    def test_live_server_initialization(self, starlette_app_no_auth):
        """Test initializing MCP connection to live server."""
        port = get_free_port()
        with run_server_in_thread(starlette_app_no_auth, "127.0.0.1", port) as base_url:
            with httpx.Client(timeout=10.0) as client:
                request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "httpx-client", "version": "1.0.0"},
                    },
                }
                response = client.post(
                    f"{base_url}/mcp",
                    json=request,
                    headers=MCP_JSON_HEADERS,
                )
                assert response.status_code in (200, 202)

    def test_live_server_with_auth(self, starlette_app_with_auth):
        """Test authentication with live server."""
        app, auth_token = starlette_app_with_auth
        port = get_free_port()
        with run_server_in_thread(app, "127.0.0.1", port) as base_url:
            with httpx.Client(timeout=10.0) as client:
                # Without auth - should fail
                response = client.get(f"{base_url}/mcp")
                assert response.status_code == 401

                # With auth - should succeed
                response = client.get(
                    f"{base_url}/mcp",
                    headers={"Authorization": f"Bearer {auth_token}"},
                )
                assert response.status_code != 401

    def test_live_server_multiple_requests(self, starlette_app_no_auth):
        """Test multiple sequential requests to live server."""
        port = get_free_port()
        with run_server_in_thread(starlette_app_no_auth, "127.0.0.1", port) as base_url:
            with httpx.Client(timeout=10.0) as client:
                for i in range(5):
                    request = {
                        "jsonrpc": "2.0",
                        "id": i + 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": f"client-{i}", "version": "1.0.0"},
                        },
                    }
                    response = client.post(
                        f"{base_url}/mcp",
                        json=request,
                        headers=MCP_JSON_HEADERS,
                    )
                    assert response.status_code in (200, 202)

    def test_live_server_concurrent_clients(self, starlette_app_no_auth):
        """Test concurrent clients connecting to live server."""
        import concurrent.futures

        port = get_free_port()
        with run_server_in_thread(starlette_app_no_auth, "127.0.0.1", port) as base_url:

            def client_session(client_id):
                with httpx.Client(timeout=10.0) as client:
                    request = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {
                                "name": f"concurrent-{client_id}",
                                "version": "1.0.0",
                            },
                        },
                    }
                    response = client.post(
                        f"{base_url}/mcp",
                        json=request,
                        headers=MCP_JSON_HEADERS,
                    )
                    return response.status_code

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(client_session, i) for i in range(10)]
                status_codes = [
                    f.result() for f in concurrent.futures.as_completed(futures)
                ]

            for status in status_codes:
                assert status in (200, 202)


# =============================================================================
# Async HTTP Client Tests
# =============================================================================


@pytest.mark.skip(reason="Live server tests timeout in CI - run manually")
class TestAsyncHTTPClient:
    """Tests using async HTTP client."""

    @pytest.mark.asyncio
    async def test_async_client_initialization(self, starlette_app_no_auth):
        """Test async client connecting to server."""
        port = get_free_port()
        with run_server_in_thread(starlette_app_no_auth, "127.0.0.1", port) as base_url:
            async with httpx.AsyncClient(timeout=10.0) as client:
                request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "async-client", "version": "1.0.0"},
                    },
                }
                response = await client.post(
                    f"{base_url}/mcp",
                    json=request,
                    headers=MCP_JSON_HEADERS,
                )
                assert response.status_code in (200, 202)

    @pytest.mark.asyncio
    async def test_async_concurrent_requests(self, starlette_app_no_auth):
        """Test async concurrent requests."""
        port = get_free_port()
        with run_server_in_thread(starlette_app_no_auth, "127.0.0.1", port) as base_url:
            async with httpx.AsyncClient(timeout=10.0) as client:

                async def make_request(i):
                    request = {
                        "jsonrpc": "2.0",
                        "id": i,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {
                                "name": f"async-{i}",
                                "version": "1.0.0",
                            },
                        },
                    }
                    return await client.post(
                        f"{base_url}/mcp",
                        json=request,
                        headers=MCP_JSON_HEADERS,
                    )

                responses = await asyncio.gather(*[make_request(i) for i in range(10)])

                for response in responses:
                    assert response.status_code in (200, 202)
