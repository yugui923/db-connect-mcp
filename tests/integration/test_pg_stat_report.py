"""PostgreSQL pg_stat_statements reporting without extension installation."""

import os

import pytest

from db_connect_mcp.models.config import DatabaseConfig
from db_connect_mcp.server import DatabaseMCPServer


@pytest.mark.asyncio
async def test_top_queries_reports_absent_extension_without_installing() -> None:
    url = os.getenv("PG_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PG_TEST_DATABASE_URL not set")
    server = DatabaseMCPServer(DatabaseConfig(url=url, enable_pg_stat_statements=True))
    await server.initialize()
    try:
        assert server.pg_stat_reporter is not None
        report = await server.pg_stat_reporter.get_top_queries()
        assert report.status in {
            "available",
            "extension_not_installed",
            "extension_not_loaded",
            "permission_denied",
        }
        assert len(report.queries) <= 10
        assert all(query.query is None for query in report.queries)
    finally:
        await server.cleanup()
