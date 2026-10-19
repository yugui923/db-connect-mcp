"""Safety and lifecycle tests for the opt-in hypothetical index comparison."""

from unittest.mock import AsyncMock, MagicMock

import pytest

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
    conn.rollback.assert_awaited()
    connection.get_connection.assert_called_once()
