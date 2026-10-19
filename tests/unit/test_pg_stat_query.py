"""Boundary behavior for pg_stat_statements SQL and returned query text."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from db_connect_mcp.core.pg_stat import PgStatReporter


@pytest.mark.asyncio
async def test_report_uses_bounded_schema_qualified_sql_and_opt_in_text() -> None:
    connection = MagicMock()
    conn = MagicMock()
    responses = [
        ('weird"schema',),
        [
            (name,)
            for name in (
                "queryid",
                "calls",
                "rows",
                "query",
                "total_exec_time",
                "dbid",
                "userid",
            )
        ],
        [(23, 5, 12.5, 2.5, 42, "SELECT sensitive")],
    ]
    queries: list[tuple[str, dict[str, object]]] = []

    async def execute(
        statement: object, parameters: dict[str, object] | None = None
    ) -> MagicMock:
        queries.append((str(statement), parameters or {}))
        result = MagicMock()
        value = responses.pop(0)
        result.fetchone.return_value = value
        result.fetchall.return_value = value
        return result

    conn.execute = AsyncMock(side_effect=execute)

    @asynccontextmanager
    async def get_connection():
        yield conn

    connection.get_connection = get_connection
    reporter = PgStatReporter(connection)
    report = await reporter.get_top_queries(
        limit=3, include_query_text=True, query_text_limit=80
    )
    assert report.status == "available"
    assert report.queries[0].query == "SELECT sensitive"
    sql, parameters = queries[2]
    assert '"weird""schema"."pg_stat_statements"' in sql
    assert "LIMIT :limit" in sql
    assert "current_database()" in sql
    assert "current_user" in sql
    assert parameters == {"limit": 3, "include_text": True, "text_limit": 80}
