"""Extension-backed HypoPG lifecycle checks in an explicitly configured test DB."""

import os
from typing import cast
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from db_connect_mcp.core.connection import DatabaseConnection
from db_connect_mcp.core.hypopg import HypoPGComparison
from db_connect_mcp.models.config import DatabaseConfig

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_hypopg_index_does_not_leak_after_planner_failure() -> None:
    url = os.getenv("HYPOPG_TEST_DATABASE_URL")
    if not url:
        pytest.skip("HYPOPG_TEST_DATABASE_URL not set (requires provisioned HypoPG)")

    connection = DatabaseConnection(
        DatabaseConfig(url=url, pool_size=1, max_overflow=0)
    )
    await connection.initialize()
    comparison = HypoPGComparison(connection)
    query = "SELECT * FROM products WHERE category_id = 1"
    args = (query, "public", "products", ["category_id"])
    try:
        async with connection.get_connection() as conn:
            installed = await cast(AsyncConnection, conn).scalar(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_extension WHERE extname = 'hypopg'"
                )
            )
            assert installed == 1, "Test DB must have HypoPG installed"
        baseline = await comparison.compare(*args, opt_in=True)
        assert isinstance(baseline.hypothetical_index_used, bool)

        original_explain = comparison._explain
        explain_calls = 0

        async def fail_second_explain(
            conn: AsyncConnection, statement: str
        ) -> dict[str, object]:
            nonlocal explain_calls
            explain_calls += 1
            if explain_calls == 2:
                await conn.execute(text("SELECT 1/0"))
            return await original_explain(conn, statement)

        with patch.object(comparison, "_explain", side_effect=fail_second_explain):
            with pytest.raises(Exception, match="division by zero"):
                await comparison.compare(*args, opt_in=True)

        async with connection.get_connection() as conn:
            remaining = await cast(AsyncConnection, conn).scalar(
                text("SELECT count(*) FROM hypopg()")
            )
            assert remaining == 0
        repeated = await comparison.compare(*args, opt_in=True)
        assert repeated.baseline_plan == baseline.baseline_plan
    finally:
        await connection.dispose()
