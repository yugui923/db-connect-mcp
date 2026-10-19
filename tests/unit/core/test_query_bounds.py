"""Query result upper-bound regressions."""

from unittest.mock import MagicMock

import pytest

from db_connect_mcp.core.executor import QueryExecutor


@pytest.mark.parametrize("limit", [None, 0, -1, 10001])
def test_query_rejects_unbounded_or_invalid_limit(limit: int | None) -> None:
    executor = QueryExecutor(MagicMock(), MagicMock())
    with pytest.raises(ValueError, match="limit"):
        executor._validate_limit(limit)


def test_query_rejects_multiple_sql_statements() -> None:
    executor = QueryExecutor(MagicMock(), MagicMock())
    with pytest.raises(ValueError, match="statement"):
        executor._validate_query("SELECT 1; SELECT 2")
