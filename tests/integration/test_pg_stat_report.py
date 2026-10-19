"""PostgreSQL pg_stat_statements reporting without extension installation."""

import os

import pytest
from sqlalchemy import text

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


@pytest.mark.asyncio
async def test_top_queries_real_extension_omits_text_by_default() -> None:
    url = os.getenv("PG_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PG_TEST_DATABASE_URL not set")
    server = DatabaseMCPServer(DatabaseConfig(url=url, enable_pg_stat_statements=True))
    await server.initialize()
    try:
        async with server.connection.get_connection() as conn:
            installed = await conn.execute(
                text(
                    "SELECT 1 FROM pg_catalog.pg_extension WHERE extname = 'pg_stat_statements'"
                )
            )
            if installed.fetchone() is None:
                pytest.skip("pg_stat_statements is not installed on test database")
        report = await server.pg_stat_reporter.get_top_queries()
        assert report.status in {
            "available",
            "extension_not_loaded",
            "permission_denied",
            "unsupported_version",
        }
        if report.status == "available":
            assert all(query.query is None for query in report.queries)
            opt_in = await server.pg_stat_reporter.get_top_queries(
                include_query_text=True
            )
            assert opt_in.status == "available"
    finally:
        await server.cleanup()
