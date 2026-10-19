"""Safety and lifecycle tests for the opt-in hypothetical index comparison."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from db_connect_mcp.models.config import DatabaseConfig

from db_connect_mcp.core.hypopg import HypoPGComparison


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM users; DROP TABLE users",
        "WITH x AS (DELETE FROM users RETURNING *) SELECT * FROM x",
        "SELECT dangerous() FROM users",
        "SELECT * FROM users -- comment",
        "SELECT * FROM users WHERE id = $1",
        "EXPLAIN ANALYZE SELECT * FROM users",
    ],
)
def test_rejects_unsafe_query(query):
    with pytest.raises(ValueError):
        HypoPGComparison.validate_query(query)


@pytest.mark.parametrize("value", ["users;DROP", 'a"b', "a.b", "", "a b"])
def test_rejects_unsafe_identifier(value):
    with pytest.raises(ValueError):
        HypoPGComparison.validate_identifier(value)


@pytest.mark.parametrize(
    "query", ["SELECT * FROM users FOR UPDATE", "SELECT * INTO new_table FROM users"]
)
def test_rejects_forbidden_select_keywords(query):
    with pytest.raises(ValueError, match="unsupported keyword"):
        HypoPGComparison.validate_query(query)


@pytest.mark.parametrize(
    ("dialect", "read_only", "columns", "message"),
    [
        ("mysql", True, ["id"], "PostgreSQL-only"),
        ("postgresql", False, ["id"], "read-only"),
        ("postgresql", True, [], "1 to 4"),
        ("postgresql", True, ["id", "id"], "distinct"),
        ("postgresql", True, ["a", "b", "c", "d", "e"], "1 to 4"),
    ],
)
@pytest.mark.asyncio
async def test_rejects_invalid_comparison_before_checkout(
    dialect, read_only, columns, message
):
    connection = MagicMock()
    connection.dialect = dialect
    connection.config.read_only = read_only
    with pytest.raises(ValueError, match=message):
        await HypoPGComparison(connection).compare(
            "SELECT * FROM users", "public", "users", columns, opt_in=True
        )
    connection.get_connection.assert_not_called()


@pytest.mark.asyncio
async def test_no_database_access_without_opt_in():
    connection = MagicMock()
    comparison = HypoPGComparison(connection)
    with pytest.raises(ValueError, match="opt-in"):
        await comparison.compare("SELECT * FROM users", "public", "users", ["id"])
    connection.get_connection.assert_not_called()


@pytest.mark.asyncio
async def test_same_session_and_cleanup_on_explain_failure():
    connection = MagicMock()
    connection.dialect = "postgresql"
    connection.config.read_only = True
    conn = AsyncMock()
    calls = []

    async def execute(statement, params=None):
        sql = str(statement)
        calls.append((sql, params))
        if "FROM pg_catalog.pg_extension" in sql:
            result = MagicMock()
            result.fetchone.return_value = ("public",)
            return result
        if "pg_catalog.pg_class" in sql:
            result = MagicMock()
            result.fetchone.return_value = (1,)
            result.fetchall.return_value = [("id",)]
            return result
        if "hypopg_create_index" in sql:
            result = MagicMock()
            result.fetchone.return_value = (123, "index")
            return result
        if "hypopg_drop_index" in sql:
            result = MagicMock()
            result.fetchone.return_value = (True,)
            return result
        if "EXPLAIN" in sql and len([c for c in calls if "EXPLAIN" in c[0]]) == 2:
            raise RuntimeError("planner failed")
        result = MagicMock()
        result.fetchone.return_value = ([{"Plan": {"Total Cost": 15.0}}],)
        return result

    conn.execute.side_effect = execute
    connection.get_connection.return_value.__aenter__ = AsyncMock(return_value=conn)
    connection.get_connection.return_value.__aexit__ = AsyncMock(return_value=None)
    comparison = HypoPGComparison(connection)
    with pytest.raises(RuntimeError, match="planner failed"):
        await comparison.compare(
            "SELECT * FROM users WHERE id = 1", "public", "users", ["id"], opt_in=True
        )
    assert len([c for c in calls if "EXPLAIN" in c[0]]) == 2
    assert any("hypopg_drop_index" in sql for sql, _ in calls)
    assert conn.rollback.await_count == 2
    conn.invalidate.assert_not_awaited()
    connection.get_connection.assert_called_once()


@pytest.fixture
def comparison_session():
    connection = MagicMock()
    connection.dialect = "postgresql"
    connection.config = DatabaseConfig(url="postgresql+asyncpg://u:p@localhost/db")
    conn = AsyncMock()
    calls = []
    extension = ("extensions",)
    relation = (1,)
    attributes = [("id",), ("name",)]
    index = (123, "index")
    plans = [
        [{"Plan": {"Total Cost": 15.0}}],
        [{"Plan": {"Total Cost": 5.0}}],
    ]

    async def execute(statement, params=None):
        sql = str(statement)
        calls.append((sql, params))
        result = MagicMock()
        if "FROM pg_catalog.pg_extension" in sql:
            result.fetchone.return_value = extension
        elif "FROM pg_catalog.pg_class" in sql:
            result.fetchone.return_value = relation
        elif "FROM pg_catalog.pg_attribute" in sql:
            result.fetchall.return_value = attributes
        elif "hypopg_create_index" in sql:
            result.fetchone.return_value = index
        elif "hypopg_drop_index" in sql:
            result.fetchone.return_value = (True,)
        elif "EXPLAIN" in sql:
            result.fetchone.return_value = (plans.pop(0),)
        return result

    conn.execute.side_effect = execute
    connection.get_connection.return_value.__aenter__ = AsyncMock(return_value=conn)
    connection.get_connection.return_value.__aexit__ = AsyncMock(return_value=None)
    return HypoPGComparison(connection), conn, calls


@pytest.mark.asyncio
async def test_comparison_returns_both_plans_and_drops_index(comparison_session):
    comparison, conn, calls = comparison_session
    result = await comparison.compare(
        "SELECT * FROM users WHERE id = 1", "public", "users", ["id"], opt_in=True
    )
    assert result.baseline_estimated_cost == 15.0
    assert result.hypothetical_estimated_cost == 5.0
    assert result.hypothetical_index == 'CREATE INDEX ON "public"."users" ("id")'
    assert [sql for sql, _ in calls if "EXPLAIN" in sql] == [
        "EXPLAIN (FORMAT JSON) SELECT * FROM users WHERE id = 1"
    ] * 2
    assert next(params for sql, params in calls if "hypopg_create_index" in sql) == {
        "definition": result.hypothetical_index
    }
    assert next(params for sql, params in calls if "hypopg_drop_index" in sql) == {
        "oid": 123
    }
    assert conn.rollback.await_count == 2


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("missing_extension", "not installed"),
        ("missing_table", "ordinary or partitioned table"),
        ("missing_column", "columns must exist"),
        ("missing_index", "did not return"),
        ("unsafe_extension_schema", "simple PostgreSQL identifiers"),
    ],
)
@pytest.mark.asyncio
async def test_comparison_fails_closed_and_rolls_back(
    comparison_session, change, message
):
    comparison, conn, calls = comparison_session
    original_execute = conn.execute.side_effect

    async def execute(statement, params=None):
        sql = str(statement)
        if change == "missing_extension" and "FROM pg_catalog.pg_extension" in sql:
            response = MagicMock()
            response.fetchone.return_value = None
            return response
        if (
            change == "unsafe_extension_schema"
            and "FROM pg_catalog.pg_extension" in sql
        ):
            response = MagicMock()
            response.fetchone.return_value = ("bad;schema",)
            return response
        if change == "missing_table" and "FROM pg_catalog.pg_class" in sql:
            response = MagicMock()
            response.fetchone.return_value = None
            return response
        if change == "missing_column" and "FROM pg_catalog.pg_attribute" in sql:
            response = MagicMock()
            response.fetchall.return_value = []
            return response
        if change == "missing_index" and "hypopg_create_index" in sql:
            response = MagicMock()
            response.fetchone.return_value = None
            return response
        return await original_execute(statement, params)

    conn.execute.side_effect = execute
    with pytest.raises(ValueError, match=message):
        await comparison.compare(
            "SELECT * FROM users", "public", "users", ["id"], opt_in=True
        )
    assert not any("hypopg_drop_index" in sql for sql, _ in calls)
    conn.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_unconfirmed_drop_invalidates_backend(comparison_session):
    comparison, conn, _ = comparison_session
    original_execute = conn.execute.side_effect

    async def execute(statement, params=None):
        if "hypopg_drop_index" in str(statement):
            response = MagicMock()
            response.fetchone.return_value = (False,)
            return response
        return await original_execute(statement, params)

    conn.execute.side_effect = execute
    with pytest.raises(RuntimeError, match="not confirmed"):
        await comparison.compare(
            "SELECT * FROM users", "public", "users", ["id"], opt_in=True
        )
    conn.invalidate.assert_awaited_once()


@pytest.mark.asyncio
async def test_planner_empty_result_rolls_back(comparison_session):
    comparison, conn, _ = comparison_session
    original_execute = conn.execute.side_effect

    async def execute(statement, params=None):
        if "EXPLAIN" in str(statement):
            result = MagicMock()
            result.fetchone.return_value = None
            return result
        return await original_execute(statement, params)

    conn.execute.side_effect = execute
    with pytest.raises(ValueError, match="no plan"):
        await comparison.compare(
            "SELECT * FROM users", "public", "users", ["id"], opt_in=True
        )
    conn.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_explain_rolls_back_before_dropping_session_index(
    comparison_session,
):
    comparison, conn, calls = comparison_session
    original_execute = conn.execute.side_effect
    rollback_seen = False

    async def rollback():
        nonlocal rollback_seen
        rollback_seen = True

    async def execute(statement, params=None):
        if (
            "EXPLAIN" in str(statement)
            and sum("EXPLAIN" in sql for sql, _ in calls) == 1
        ):
            calls.append((str(statement), params))
            raise RuntimeError("transaction aborted")
        if "hypopg_drop_index" in str(statement):
            assert rollback_seen
        return await original_execute(statement, params)

    conn.execute.side_effect = execute
    conn.rollback.side_effect = rollback
    with pytest.raises(RuntimeError, match="transaction aborted"):
        await comparison.compare(
            "SELECT * FROM users", "public", "users", ["id"], opt_in=True
        )
    assert any("hypopg_drop_index" in sql for sql, _ in calls)
    conn.invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_index_cleanup_invalidates_pooled_backend(comparison_session):
    comparison, conn, _ = comparison_session
    original_execute = conn.execute.side_effect

    async def execute(statement, params=None):
        if "hypopg_drop_index" in str(statement):
            raise RuntimeError("cleanup failed")
        return await original_execute(statement, params)

    conn.execute.side_effect = execute
    with pytest.raises(RuntimeError, match="cleanup failed"):
        await comparison.compare(
            "SELECT * FROM users", "public", "users", ["id"], opt_in=True
        )
    conn.invalidate.assert_awaited_once()


@pytest.mark.asyncio
async def test_comparison_sets_current_transaction_read_only(comparison_session):
    comparison, _, calls = comparison_session
    await comparison.compare(
        "SELECT * FROM users", "public", "users", ["id"], opt_in=True
    )
    assert "SET TRANSACTION READ ONLY" in [sql for sql, _ in calls]
    assert [sql for sql, _ in calls].index("SET TRANSACTION READ ONLY") < next(
        i for i, (sql, _) in enumerate(calls) if "FROM pg_catalog.pg_extension" in sql
    )


@pytest.mark.asyncio
async def test_planner_json_string_is_decoded(comparison_session):
    comparison, conn, _ = comparison_session
    original_execute = conn.execute.side_effect

    async def execute(statement, params=None):
        if "EXPLAIN" in str(statement):
            response = MagicMock()
            response.fetchone.return_value = ('[{"Plan": {"Total Cost": 3.0}}]',)
            return response
        return await original_execute(statement, params)

    conn.execute.side_effect = execute
    result = await comparison.compare(
        "SELECT * FROM users", "public", "users", ["id"], opt_in=True
    )
    assert result.baseline_estimated_cost == result.hypothetical_estimated_cost == 3.0
