"""Live PostgreSQL health snapshot and MCP contract."""

import json

import pytest

from db_connect_mcp.models.config import DatabaseConfig
from db_connect_mcp.server import DatabaseMCPServer


@pytest.mark.asyncio
async def test_pg_health_live_contract(pg_database_url: str) -> None:
    server = DatabaseMCPServer(DatabaseConfig(url=pg_database_url))
    await server.initialize()
    try:
        names = {tool.name for tool in server._available_tools()}
        assert "postgres_health" in names
        result = await server.handle_postgres_health({})
        payload = json.loads(result[0].text)
        assert payload["findings"]
        findings = {finding["check"]: finding for finding in payload["findings"]}
        assert findings["xid_age"]["observed_value"] >= 0
        assert findings["connection_utilization"]["state"] == "observed"
        assert all(f["observed_at"] for f in payload["findings"])
    finally:
        await server.connection.dispose()
