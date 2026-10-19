"""Boundary behavior for pg_stat_statements SQL and returned query text."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import DBAPIError

from db_connect_mcp.core.pg_stat import PgStatReporter


@pytest.fixture
def reporter_factory():
    def make_reporter(responses):
        connection = MagicMock()
        conn = MagicMock()
        queries: list[tuple[str, dict[str, object]]] = []

        async def execute(statement: object, parameters=None) -> MagicMock:
            queries.append((str(statement), parameters or {}))
            if str(statement).startswith("SET LOCAL statement_timeout"):
                assert str(statement) == "SET LOCAL statement_timeout = '5s'"
                return MagicMock()
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            result = MagicMock()
            result.fetchone.return_value = value
            result.fetchall.return_value = value
            return result

        conn.execute = AsyncMock(side_effect=execute)

        @asynccontextmanager
        async def get_connection():
            yield conn

        connection.get_connection = get_connection
        return PgStatReporter(connection), queries

    return make_reporter


def columns(*names: str) -> list[tuple[str]]:
    return [(name,) for name in names]


BASE_COLUMNS = ("queryid", "calls", "rows", "query", "dbid", "userid")


def db_error(state: str | None, *, nested: bool = False) -> DBAPIError:
    cause = Exception("database error")
    cause.sqlstate = state  # type: ignore[attr-defined]
    original = Exception("driver error")
    if nested:
        original.__cause__ = cause
    else:
        original.sqlstate = state  # type: ignore[attr-defined]
    return DBAPIError("SELECT", {}, original)


@pytest.mark.asyncio
async def test_report_uses_bounded_schema_qualified_sql_and_opt_in_text(
    reporter_factory,
) -> None:
    reporter, queries = reporter_factory(
        [
            ('weird"schema',),
            columns(*BASE_COLUMNS, "total_exec_time"),
            [(23, 5, 12.5, 2.5, 42, "SELECT sensitive")],
        ]
    )
    report = await reporter.get_top_queries(
        limit=3, include_query_text=True, query_text_limit=80
    )
    assert report.status == "available"
    assert report.queries[0].query == "SELECT sensitive"
    sql, parameters = queries[3]
    assert '"weird""schema"."pg_stat_statements"' in sql
    assert queries[2][0].strip() == "SET LOCAL statement_timeout = '5s'"
    assert "LIMIT :limit" in sql
    assert "current_database()" in sql
    assert "current_user" in sql
    assert "pg_catalog.pg_roles" in sql
    assert parameters == {"limit": 3, "include_text": True, "text_limit": 80}


@pytest.mark.asyncio
async def test_report_absent_extension_returns_empty_without_querying_view(
    reporter_factory,
) -> None:
    reporter, queries = reporter_factory([None])
    report = await reporter.get_top_queries()
    assert report.status == "extension_not_installed"
    assert report.queries == []
    assert len(queries) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "layout",
    [columns("queryid", "calls"), columns(*BASE_COLUMNS)],
)
async def test_report_unsupported_columns_do_not_query_view(
    reporter_factory, layout
) -> None:
    reporter, queries = reporter_factory([("public",), layout])
    report = await reporter.get_top_queries()
    assert report.status == "unsupported_version"
    assert report.queries == []
    assert len(queries) == 2


@pytest.mark.asyncio
async def test_report_legacy_total_time_returns_metrics(reporter_factory) -> None:
    reporter, queries = reporter_factory(
        [
            ("public",),
            columns(*BASE_COLUMNS, "total_time"),
            [(42, 0, 7.5, None, 0, None)],
        ]
    )
    report = await reporter.get_top_queries()
    assert report.status == "available"
    assert report.queries[0].total_exec_time_ms == 7.5
    assert report.queries[0].mean_exec_time_ms == 0
    assert report.queries[0].query is None
    assert "total_time / NULLIF(calls, 0)" in queries[3][0]
    assert queries[3][1]["include_text"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_report_permission_denied_at_initial_lookup(
    reporter_factory, nested
) -> None:
    reporter, queries = reporter_factory([db_error("42501", nested=nested)])
    report = await reporter.get_top_queries()
    assert report.status == "permission_denied"
    assert report.queries == []
    assert len(queries) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["55000", "58P01"])
async def test_report_extension_not_loaded_returns_status(
    reporter_factory, state
) -> None:
    reporter, queries = reporter_factory(
        [("public",), columns(*BASE_COLUMNS, "total_exec_time"), db_error(state)]
    )
    report = await reporter.get_top_queries()
    assert report.status == "extension_not_loaded"
    assert report.queries == []
    assert len(queries) == 4


@pytest.mark.asyncio
async def test_report_query_timeout_propagates_as_error(reporter_factory) -> None:
    reporter, _ = reporter_factory(
        [("public",), columns(*BASE_COLUMNS, "total_exec_time"), db_error("57014")]
    )
    with pytest.raises(DBAPIError):
        await reporter.get_top_queries()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["08006", "57014"])
async def test_report_unexpected_database_error_propagates(
    reporter_factory, state
) -> None:
    error = db_error(state)
    reporter, _ = reporter_factory([error])
    with pytest.raises(DBAPIError) as caught:
        await reporter.get_top_queries()
    assert caught.value is error


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,text_limit", [(0, 200), (51, 200), (10, 0), (10, 2001)])
async def test_report_rejects_out_of_bounds_without_database_access(
    reporter_factory, limit, text_limit
) -> None:
    reporter, queries = reporter_factory([])
    with pytest.raises(ValueError):
        await reporter.get_top_queries(limit=limit, query_text_limit=text_limit)
    assert queries == []
