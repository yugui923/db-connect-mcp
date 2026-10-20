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
async def test_top_queries_installed_extension_reports_workload_and_opt_in_text() -> (
    None
):
    url = os.getenv("PG_STAT_INSTALLED_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PG_STAT_INSTALLED_TEST_DATABASE_URL not set")
    server = DatabaseMCPServer(DatabaseConfig(url=url, enable_pg_stat_statements=True))
    await server.initialize()
    try:
        async with server.connection.get_connection() as conn:
            await conn.execute(
                text(
                    "SELECT 918273645::bigint AS pg_stat_report_probe "
                    "FROM generate_series(1, 10000)"
                )
            )
        assert server.pg_stat_reporter is not None
        report = await server.pg_stat_reporter.get_top_queries(limit=50)
        assert report.status == "available"
        assert report.queries
        assert all(query.query is None for query in report.queries)

        opt_in = await server.pg_stat_reporter.get_top_queries(
            limit=50, include_query_text=True
        )
        assert opt_in.status == "available"
        assert any(
            query.query is not None and "pg_stat_report_probe" in query.query
            for query in opt_in.queries
        )
    finally:
        await server.cleanup()
