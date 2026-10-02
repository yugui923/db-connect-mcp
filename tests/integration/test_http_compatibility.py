"""Compatibility tests against the production HTTP app and MCP clients."""

import json
import threading
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import patch

import httpx
import pytest
import uvicorn
from mcp import Client
from mcp.server.auth.provider import AccessToken

from db_connect_mcp.models.config import DatabaseConfig
from db_connect_mcp.server import DatabaseMCPServer, _create_streamable_http_app


def _modern_request() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "server/discover",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        },
    }


MODERN_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2026-07-28",
    "Mcp-Method": "server/discover",
}


class _SyntheticVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        if token != "valid-token":
            return None
        return AccessToken(token=token, client_id="test", scopes=["read:database"])


@contextmanager
def _serve(app: object) -> Iterator[str]:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            threading.Event().wait(0.05)
        assert server.started
        sockets = server.servers[0].sockets
        yield f"http://127.0.0.1:{sockets[0].getsockname()[1]}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_production_http_serves_legacy_and_modern_clients(
    pg_database_url: str, mode: str
) -> None:
    server = DatabaseMCPServer(DatabaseConfig(url=pg_database_url))
    await server.initialize()
    try:
        with _serve(_create_streamable_http_app(server)) as url:
            async with Client(url, mode=mode) as client:
                assert client.protocol_version == (
                    "2026-07-28" if mode == "auto" else "2025-11-25"
                )
                tools = await client.list_tools()
                assert "execute_query" in {tool.name for tool in tools.tools}
                if mode == "auto":
                    assert tools.cache_scope == "private"
                result = await client.call_tool(
                    "execute_query", {"query": "SELECT 1 AS answer"}
                )
                assert not result.is_error
                assert result.structured_content["rows"][0]["answer"] == 1
                assert '"answer": 1' in result.content[0].text
                schemas = await client.call_tool("list_schemas", {})
                assert not schemas.is_error
                assert isinstance(json.loads(schemas.content[0].text), list)
                assert "items" in schemas.structured_content
                rejected = await client.call_tool(
                    "execute_query", {"query": "DROP TABLE products"}
                )
                assert rejected.is_error
                resources = await client.list_resources()
                assert "db-connect://database" in {
                    item.uri for item in resources.resources
                }
                if mode == "auto":
                    assert resources.cache_scope == "private"
                read = await client.read_resource("db-connect://database")
                assert read.contents[0].mime_type == "application/json"
                again = await client.call_tool(
                    "execute_query", {"query": "SELECT 2 AS answer"}
                )
                assert again.structured_content["rows"][0]["answer"] == 2
    finally:
        await server.cleanup()


@pytest.mark.asyncio
async def test_production_http_authenticates_before_dispatch(
    pg_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = DatabaseMCPServer(DatabaseConfig(url=pg_database_url))
    await server.initialize()
    try:
        monkeypatch.setenv("MCP_AUTH_TOKEN", "valid-token")
        with _serve(_create_streamable_http_app(server)) as url:
            async with httpx.AsyncClient() as client:
                denied = await client.post(
                    url, headers=MODERN_HEADERS, json=_modern_request()
                )
                assert denied.status_code == 401
                allowed = await client.post(
                    url,
                    headers={**MODERN_HEADERS, "Authorization": "Bearer valid-token"},
                    json=_modern_request(),
                )
                assert allowed.status_code == 200
                assert "Mcp-Session-Id" not in allowed.headers
    finally:
        await server.cleanup()


@pytest.mark.asyncio
async def test_production_http_oauth_scopes_apply_to_modern_requests(
    pg_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = DatabaseMCPServer(DatabaseConfig(url=pg_database_url))
    await server.initialize()
    try:
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        with patch(
            "db_connect_mcp.auth.JWTTokenVerifier", return_value=_SyntheticVerifier()
        ):
            app = _create_streamable_http_app(
                server,
                oauth_issuer="https://issuer.example",
                oauth_audience="database",
                oauth_scopes=["read:database", "admin:database"],
            )
        with _serve(app) as url:
            async with httpx.AsyncClient() as client:
                missing = await client.post(
                    url, headers=MODERN_HEADERS, json=_modern_request()
                )
                assert missing.status_code == 401
                forbidden = await client.post(
                    url,
                    headers={**MODERN_HEADERS, "Authorization": "Bearer valid-token"},
                    json=_modern_request(),
                )
                assert forbidden.status_code == 403
                assert forbidden.json()["error"] == "insufficient_scope"
    finally:
        await server.cleanup()


@pytest.mark.asyncio
async def test_production_http_rejects_bad_origin_and_large_body(
    pg_database_url: str,
) -> None:
    server = DatabaseMCPServer(DatabaseConfig(url=pg_database_url))
    await server.initialize()
    try:
        with _serve(_create_streamable_http_app(server)) as url:
            async with httpx.AsyncClient() as client:
                origin = await client.post(
                    url,
                    headers={**MODERN_HEADERS, "Origin": "https://attacker.example"},
                    json=_modern_request(),
                )
                assert origin.status_code == 403
                oversized = await client.post(
                    url,
                    headers=MODERN_HEADERS,
                    content=b" " * (4 * 1024 * 1024 + 1),
                )
                assert oversized.status_code == 413
    finally:
        await server.cleanup()


@pytest.mark.asyncio
async def test_production_http_allows_configured_proxy_host(
    pg_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = DatabaseMCPServer(DatabaseConfig(url=pg_database_url))
    await server.initialize()
    try:
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp.example.com")
        monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://mcp.example.com")
        with _serve(_create_streamable_http_app(server)) as url:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        **MODERN_HEADERS,
                        "Host": "mcp.example.com",
                        "Origin": "https://mcp.example.com",
                    },
                    json=_modern_request(),
                )
                assert response.status_code == 200
                assert response.json()["result"]["supportedVersions"]
    finally:
        await server.cleanup()


@pytest.mark.asyncio
async def test_production_http_rejects_mismatched_modern_headers(
    pg_database_url: str,
) -> None:
    server = DatabaseMCPServer(DatabaseConfig(url=pg_database_url))
    await server.initialize()
    try:
        with _serve(_create_streamable_http_app(server)) as url:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                        "MCP-Protocol-Version": "2026-07-28",
                        "Mcp-Method": "tools/list",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "resources/list",
                        "params": {
                            "_meta": {
                                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                "io.modelcontextprotocol/clientCapabilities": {},
                            }
                        },
                    },
                )
                assert response.status_code == 400
                assert response.json()["error"]["code"] == -32020
                response = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                        "MCP-Protocol-Version": "2026-07-28",
                        "Mcp-Method": "tools/list",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {
                            "_meta": {
                                "io.modelcontextprotocol/protocolVersion": "2025-11-25",
                                "io.modelcontextprotocol/clientCapabilities": {},
                            }
                        },
                    },
                )
                assert response.status_code == 400
                assert response.json()["error"]["code"] == -32020
    finally:
        await server.cleanup()
