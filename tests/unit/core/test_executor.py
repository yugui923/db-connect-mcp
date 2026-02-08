"""Unit tests for QueryExecutor."""

import base64
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from db_connect_mcp.core.executor import QueryExecutor, json_default


class TestJsonDefault:
    """Tests for json_default fallback handler."""

    def test_datetime_with_timezone(self):
        """Test serializing timezone-aware datetime."""
        from zoneinfo import ZoneInfo

        dt = datetime.datetime(2024, 1, 15, 10, 30, 45, tzinfo=ZoneInfo("UTC"))
        result = json_default(dt)
        assert result == "2024-01-15T10:30:45+00:00"

    def test_datetime_without_timezone(self):
        """Test serializing naive datetime."""
        dt = datetime.datetime(2024, 1, 15, 10, 30, 45)
        result = json_default(dt)
        assert result == "2024-01-15T10:30:45"

    def test_date(self):
        """Test serializing date."""
        d = datetime.date(2024, 1, 15)
        result = json_default(d)
        assert result == "2024-01-15"

    def test_time(self):
        """Test serializing time."""
        t = datetime.time(10, 30, 45)
        result = json_default(t)
        assert result == "10:30:45"

    def test_timedelta(self):
        """Test serializing timedelta."""
        td = datetime.timedelta(hours=2, minutes=30)
        result = json_default(td)
        assert result == 9000.0  # 2.5 hours in seconds

    def test_bytes(self):
        """Test serializing bytes."""
        data = b"hello world"
        result = json_default(data)
        expected = base64.b64encode(data).decode("utf-8")
        assert result == expected

    def test_unknown_type_str_fallback(self):
        """Test that unknown types fall back to string representation."""

        class CustomClass:
            def __str__(self):
                return "custom-string"

        obj = CustomClass()
        result = json_default(obj)
        assert result == "custom-string"


class TestQueryValidation:
    """Tests for query validation."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = MagicMock()
        conn.dialect = "postgresql"
        return conn

    @pytest.fixture
    def mock_adapter(self):
        """Create mock adapter."""
        adapter = MagicMock()
        adapter.capabilities.explain_plans = True
        return adapter

    def test_validate_select_allowed(self, mock_connection, mock_adapter):
        """Test SELECT queries are allowed."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        # Should not raise
        executor._validate_query("SELECT * FROM users")

    def test_validate_with_allowed(self, mock_connection, mock_adapter):
        """Test WITH (CTE) queries are allowed."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        executor._validate_query("WITH cte AS (SELECT 1) SELECT * FROM cte")

    def test_validate_show_allowed(self, mock_connection, mock_adapter):
        """Test SHOW queries are allowed."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        executor._validate_query("SHOW TABLES")

    def test_validate_describe_allowed(self, mock_connection, mock_adapter):
        """Test DESCRIBE queries are allowed."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        executor._validate_query("DESCRIBE users")

    def test_validate_explain_allowed(self, mock_connection, mock_adapter):
        """Test EXPLAIN queries are allowed."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        executor._validate_query("EXPLAIN SELECT * FROM users")

    def test_validate_insert_rejected(self, mock_connection, mock_adapter):
        """Test INSERT queries are rejected."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        with pytest.raises(ValueError, match="INSERT"):
            executor._validate_query("INSERT INTO users (name) VALUES ('test')")

    def test_validate_update_rejected(self, mock_connection, mock_adapter):
        """Test UPDATE queries are rejected."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        with pytest.raises(ValueError, match="UPDATE"):
            executor._validate_query("UPDATE users SET name = 'test'")

    def test_validate_delete_rejected(self, mock_connection, mock_adapter):
        """Test DELETE queries are rejected."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        with pytest.raises(ValueError, match="DELETE"):
            executor._validate_query("DELETE FROM users")

    def test_validate_drop_rejected(self, mock_connection, mock_adapter):
        """Test DROP queries are rejected."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        with pytest.raises(ValueError, match="DROP"):
            executor._validate_query("DROP TABLE users")

    def test_validate_truncate_rejected(self, mock_connection, mock_adapter):
        """Test TRUNCATE queries are rejected."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        with pytest.raises(ValueError, match="TRUNCATE"):
            executor._validate_query("TRUNCATE TABLE users")

    def test_validate_alter_rejected(self, mock_connection, mock_adapter):
        """Test ALTER queries are rejected."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        with pytest.raises(ValueError, match="ALTER"):
            executor._validate_query("ALTER TABLE users ADD COLUMN test TEXT")

    def test_validate_create_rejected(self, mock_connection, mock_adapter):
        """Test CREATE queries are rejected."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        with pytest.raises(ValueError, match="CREATE"):
            executor._validate_query("CREATE TABLE test (id INT)")

    def test_validate_grant_rejected(self, mock_connection, mock_adapter):
        """Test GRANT queries are rejected."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        with pytest.raises(ValueError, match="GRANT"):
            executor._validate_query("GRANT SELECT ON users TO public")

    def test_validate_revoke_rejected(self, mock_connection, mock_adapter):
        """Test REVOKE queries are rejected."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        with pytest.raises(ValueError, match="REVOKE"):
            executor._validate_query("REVOKE SELECT ON users FROM public")

    def test_validate_dangerous_in_subquery(self, mock_connection, mock_adapter):
        """Test dangerous keywords in subqueries are rejected."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        # Tries to sneak in DELETE in a CTE
        with pytest.raises(ValueError, match="DELETE"):
            executor._validate_query(
                "WITH t AS (DELETE FROM users RETURNING *) SELECT * FROM t"
            )

    def test_validate_removes_comments(self, mock_connection, mock_adapter):
        """Test that SQL comments are removed before validation."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        # Query with comments
        query = """
        -- This is a comment
        SELECT * FROM users
        /* This is a block comment */
        """
        executor._validate_query(query)  # Should not raise

    def test_validate_empty_query_rejected(self, mock_connection, mock_adapter):
        """Test empty query is rejected."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        with pytest.raises(ValueError):
            executor._validate_query("")

    def test_validate_whitespace_only_rejected(self, mock_connection, mock_adapter):
        """Test whitespace-only query is rejected."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        with pytest.raises((ValueError, IndexError)):
            executor._validate_query("   \n   \t   ")


class TestLimitHandling:
    """Tests for LIMIT clause handling."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = MagicMock()
        conn.dialect = "postgresql"
        return conn

    @pytest.fixture
    def mock_adapter(self):
        """Create mock adapter."""
        adapter = MagicMock()
        return adapter

    def test_has_limit_true(self, mock_connection, mock_adapter):
        """Test detecting existing LIMIT clause."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        assert executor._has_limit("SELECT * FROM users LIMIT 10") is True

    def test_has_limit_false(self, mock_connection, mock_adapter):
        """Test when LIMIT clause is absent."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        assert executor._has_limit("SELECT * FROM users") is False

    def test_has_limit_case_insensitive(self, mock_connection, mock_adapter):
        """Test LIMIT detection is case insensitive."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        assert executor._has_limit("SELECT * FROM users limit 10") is True

    def test_add_limit(self, mock_connection, mock_adapter):
        """Test adding LIMIT clause."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        result = executor._add_limit("SELECT * FROM users", 100)
        assert result == "SELECT * FROM users LIMIT 100"

    def test_add_limit_removes_trailing_semicolon(self, mock_connection, mock_adapter):
        """Test that trailing semicolon is removed when adding LIMIT."""
        executor = QueryExecutor(mock_connection, mock_adapter)
        result = executor._add_limit("SELECT * FROM users;", 100)
        assert result == "SELECT * FROM users LIMIT 100"
        assert ";" not in result


class TestExplainQuery:
    """Tests for explain_query method."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection with async context manager."""
        mock_conn = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_cm.__aexit__.return_value = None

        connection = MagicMock()
        connection.get_connection.return_value = mock_cm
        connection.dialect = "postgresql"
        return connection, mock_conn

    @pytest.fixture
    def mock_adapter(self):
        """Create mock adapter."""
        adapter = MagicMock()
        adapter.capabilities = MagicMock()
        adapter.capabilities.explain_plans = True
        adapter.get_explain_query = AsyncMock(
            return_value="EXPLAIN (FORMAT JSON) SELECT 1"
        )
        adapter.parse_explain_plan = AsyncMock(
            return_value={
                "json": [{"Plan": {"Node Type": "Result"}}],
                "plan_text": "Result (cost=0.00..0.01)",
                "estimated_cost": 0.01,
                "estimated_rows": 1,
                "warnings": [],
                "recommendations": [],
            }
        )
        return adapter

    @pytest.mark.asyncio
    async def test_explain_not_supported_raises_error(self, mock_connection):
        """Test that explain raises error when not supported."""
        connection, _ = mock_connection
        adapter = MagicMock()
        adapter.capabilities = MagicMock()
        adapter.capabilities.explain_plans = False

        executor = QueryExecutor(connection, adapter)

        with pytest.raises(ValueError, match="EXPLAIN not supported"):
            await executor.explain_query("SELECT 1")


class TestTestQuerySyntax:
    """Tests for test_query_syntax method."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection with async context manager."""
        mock_conn = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_conn
        mock_cm.__aexit__.return_value = None

        connection = MagicMock()
        connection.get_connection.return_value = mock_cm
        connection.dialect = "postgresql"
        return connection, mock_conn

    @pytest.fixture
    def mock_adapter(self):
        """Create mock adapter."""
        adapter = MagicMock()
        return adapter

    @pytest.mark.asyncio
    async def test_valid_query_returns_true(self, mock_connection, mock_adapter):
        """Test valid query returns (True, None)."""
        connection, mock_conn = mock_connection
        mock_conn.execute = AsyncMock()

        executor = QueryExecutor(connection, mock_adapter)
        is_valid, error = await executor.test_query_syntax("SELECT 1")

        assert is_valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_invalid_query_type_returns_error(
        self, mock_connection, mock_adapter
    ):
        """Test invalid query type returns (False, error)."""
        connection, _ = mock_connection

        executor = QueryExecutor(connection, mock_adapter)
        is_valid, error = await executor.test_query_syntax("INSERT INTO t VALUES (1)")

        assert is_valid is False
        assert error is not None
        assert "INSERT" in error

    @pytest.mark.asyncio
    async def test_syntax_error_returns_error(self, mock_connection, mock_adapter):
        """Test query with syntax error returns (False, error)."""
        connection, mock_conn = mock_connection
        mock_conn.execute = AsyncMock(side_effect=Exception("syntax error"))

        executor = QueryExecutor(connection, mock_adapter)
        is_valid, error = await executor.test_query_syntax("SELECT * FORM users")

        assert is_valid is False
        assert error is not None
