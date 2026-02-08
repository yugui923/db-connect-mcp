"""Unit tests for DatabaseConnection and connection wrappers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db_connect_mcp.core.connection import (
    AsyncConnectionWrapper,
    DatabaseConnection,
    SyncConnectionWrapper,
)
from db_connect_mcp.models.config import DatabaseConfig


class TestSyncConnectionWrapper:
    """Tests for SyncConnectionWrapper class."""

    def test_initialization(self):
        """Test wrapper initialization stores sync connection attributes."""
        mock_sync_conn = MagicMock()
        mock_sync_conn.dialect = "postgresql"
        mock_sync_conn.engine = MagicMock()
        mock_sync_conn.connection = MagicMock()
        mock_sync_conn.info = {"key": "value"}

        wrapper = SyncConnectionWrapper(mock_sync_conn)

        assert wrapper.sync_conn is mock_sync_conn
        assert wrapper.dialect == "postgresql"
        assert wrapper.engine is mock_sync_conn.engine
        assert wrapper.info == {"key": "value"}

    def test_initialization_without_optional_attrs(self):
        """Test wrapper handles missing optional attributes."""
        mock_sync_conn = MagicMock(spec=["dialect", "engine", "execute"])
        mock_sync_conn.dialect = "mysql"
        mock_sync_conn.engine = MagicMock()

        wrapper = SyncConnectionWrapper(mock_sync_conn)

        assert wrapper.sync_conn is mock_sync_conn
        assert wrapper.info == {}

    def test_execute_string_statement(self):
        """Test execute wraps string statements in text()."""
        mock_sync_conn = MagicMock()
        mock_result = MagicMock()
        mock_sync_conn.execute.return_value = mock_result

        wrapper = SyncConnectionWrapper(mock_sync_conn)
        result = wrapper.execute("SELECT 1")

        assert result is mock_result
        # Verify the statement was wrapped in text()
        call_args = mock_sync_conn.execute.call_args
        executed_stmt = call_args[0][0]
        assert str(executed_stmt) == "SELECT 1"

    def test_execute_string_statement_with_parameters(self):
        """Test execute with string statement and parameters."""
        mock_sync_conn = MagicMock()
        mock_result = MagicMock()
        mock_sync_conn.execute.return_value = mock_result

        wrapper = SyncConnectionWrapper(mock_sync_conn)
        result = wrapper.execute("SELECT * FROM users WHERE id = :id", {"id": 1})

        assert result is mock_result
        mock_sync_conn.execute.assert_called_once()

    def test_execute_non_string_statement(self):
        """Test execute passes through non-string statements."""
        mock_sync_conn = MagicMock()
        mock_result = MagicMock()
        mock_sync_conn.execute.return_value = mock_result

        from sqlalchemy import text

        stmt = text("SELECT 1")

        wrapper = SyncConnectionWrapper(mock_sync_conn)
        result = wrapper.execute(stmt)

        assert result is mock_result
        mock_sync_conn.execute.assert_called_once_with(stmt)

    def test_getattr_forwards_to_sync_conn(self):
        """Test that unknown attributes are forwarded to sync connection."""
        mock_sync_conn = MagicMock()
        mock_sync_conn.commit = MagicMock()
        mock_sync_conn.rollback = MagicMock()

        wrapper = SyncConnectionWrapper(mock_sync_conn)

        wrapper.commit()
        mock_sync_conn.commit.assert_called_once()

        wrapper.rollback()
        mock_sync_conn.rollback.assert_called_once()


class TestAsyncConnectionWrapper:
    """Tests for AsyncConnectionWrapper class."""

    def test_initialization(self):
        """Test wrapper initialization."""
        mock_sync_conn = MagicMock()
        wrapper = AsyncConnectionWrapper(mock_sync_conn)

        assert wrapper.sync_conn is mock_sync_conn
        assert wrapper._executor is None

    @pytest.mark.asyncio
    async def test_execute_string_statement(self):
        """Test async execute wraps string statements in text()."""
        mock_sync_conn = MagicMock()
        mock_result = MagicMock()
        mock_sync_conn.execute.return_value = mock_result

        wrapper = AsyncConnectionWrapper(mock_sync_conn)

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            async def mock_run_in_executor(executor, func, *args):
                return func(*args)

            mock_loop.run_in_executor = AsyncMock(side_effect=mock_run_in_executor)

            result = await wrapper.execute("SELECT 1")

            assert result is mock_result

    @pytest.mark.asyncio
    async def test_execute_with_parameters(self):
        """Test async execute with parameters."""
        mock_sync_conn = MagicMock()
        mock_result = MagicMock()
        mock_sync_conn.execute.return_value = mock_result

        wrapper = AsyncConnectionWrapper(mock_sync_conn)

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            async def mock_run_in_executor(executor, func, *args):
                return func(*args)

            mock_loop.run_in_executor = AsyncMock(side_effect=mock_run_in_executor)

            result = await wrapper.execute(
                "SELECT * FROM users WHERE id = :id", {"id": 1}
            )

            assert result is mock_result

    @pytest.mark.asyncio
    async def test_run_sync_inspection_function(self):
        """Test run_sync with inspection function passes raw connection."""
        mock_sync_conn = MagicMock()
        mock_result = {"schema": "public"}

        wrapper = AsyncConnectionWrapper(mock_sync_conn)

        def inspect_func(conn):
            return mock_result

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            async def mock_run_in_executor(executor, func, *args):
                return func(*args)

            mock_loop.run_in_executor = AsyncMock(side_effect=mock_run_in_executor)

            # Function with 'inspect' in name should pass raw connection
            inspect_func.__name__ = "get_schema_names"
            result = await wrapper.run_sync(inspect_func)

            assert result == mock_result

    @pytest.mark.asyncio
    async def test_run_sync_non_inspection_function(self):
        """Test run_sync with non-inspection function passes wrapped connection."""
        mock_sync_conn = MagicMock()
        mock_sync_conn.dialect = "postgresql"
        mock_sync_conn.engine = MagicMock()
        mock_result = "executed"

        wrapper = AsyncConnectionWrapper(mock_sync_conn)

        def regular_func(conn):
            return mock_result

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            async def mock_run_in_executor(executor, func, *args):
                return func(*args)

            mock_loop.run_in_executor = AsyncMock(side_effect=mock_run_in_executor)

            regular_func.__name__ = "execute_query"
            result = await wrapper.run_sync(regular_func)

            assert result == mock_result

    @pytest.mark.asyncio
    async def test_commit(self):
        """Test async commit delegates to sync connection."""
        mock_sync_conn = MagicMock()
        wrapper = AsyncConnectionWrapper(mock_sync_conn)

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            async def mock_run_in_executor(executor, func):
                return func()

            mock_loop.run_in_executor = AsyncMock(side_effect=mock_run_in_executor)

            await wrapper.commit()

            mock_sync_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback(self):
        """Test async rollback delegates to sync connection."""
        mock_sync_conn = MagicMock()
        wrapper = AsyncConnectionWrapper(mock_sync_conn)

        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            async def mock_run_in_executor(executor, func):
                return func()

            mock_loop.run_in_executor = AsyncMock(side_effect=mock_run_in_executor)

            await wrapper.rollback()

            mock_sync_conn.rollback.assert_called_once()

    def test_close(self):
        """Test close calls sync connection close."""
        mock_sync_conn = MagicMock()
        wrapper = AsyncConnectionWrapper(mock_sync_conn)

        wrapper.close()

        mock_sync_conn.close.assert_called_once()


class TestDatabaseConnectionProperties:
    """Tests for DatabaseConnection properties."""

    def test_dialect_property(self):
        """Test dialect property returns configured dialect."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")
        conn = DatabaseConnection(config)
        assert conn.dialect == "postgresql"

    def test_driver_property(self):
        """Test driver property returns configured driver."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")
        conn = DatabaseConnection(config)
        assert conn.driver == "asyncpg"

    def test_is_initialized_false_initially(self):
        """Test is_initialized returns False before initialization."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")
        conn = DatabaseConnection(config)
        assert conn.is_initialized is False

    def test_is_tunneled_false_without_tunnel(self):
        """Test is_tunneled returns False without tunnel."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")
        conn = DatabaseConnection(config)
        assert conn.is_tunneled is False

    def test_sync_only_detection_clickhouse(self):
        """Test ClickHouse is detected as sync-only."""
        config = DatabaseConfig(url="clickhouse://user:pass@host:8123/db")
        conn = DatabaseConnection(config)
        assert conn._is_sync_only is True

    def test_sync_only_detection_postgresql(self):
        """Test PostgreSQL is not sync-only."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")
        conn = DatabaseConnection(config)
        assert conn._is_sync_only is False

    def test_sync_only_detection_mysql(self):
        """Test MySQL is not sync-only."""
        config = DatabaseConfig(url="mysql://user:pass@host:3306/db")
        conn = DatabaseConnection(config)
        assert conn._is_sync_only is False


class TestDatabaseConnectionGetConnectionErrors:
    """Tests for get_connection error handling."""

    @pytest.mark.asyncio
    async def test_get_connection_not_initialized_async(self):
        """Test get_connection raises error when async engine not initialized."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")
        conn = DatabaseConnection(config)
        # Don't initialize

        with pytest.raises(RuntimeError, match="not initialized"):
            async with conn.get_connection():
                pass

    @pytest.mark.asyncio
    async def test_get_connection_not_initialized_sync(self):
        """Test get_connection raises error when sync engine not initialized."""
        config = DatabaseConfig(url="clickhouse://user:pass@host:8123/db")
        conn = DatabaseConnection(config)
        # Don't initialize

        with pytest.raises(RuntimeError, match="not initialized"):
            async with conn.get_connection():
                pass


class TestDatabaseConnectionContextManager:
    """Tests for async context manager protocol."""

    @pytest.mark.asyncio
    async def test_aenter_initializes_connection(self):
        """Test __aenter__ initializes the connection."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")

        with patch.object(
            DatabaseConnection, "initialize", new_callable=AsyncMock
        ) as mock_init:
            async with DatabaseConnection(config) as conn:
                mock_init.assert_called_once()
                assert isinstance(conn, DatabaseConnection)

    @pytest.mark.asyncio
    async def test_aexit_disposes_connection(self):
        """Test __aexit__ disposes the connection."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")

        with (
            patch.object(DatabaseConnection, "initialize", new_callable=AsyncMock),
            patch.object(
                DatabaseConnection, "dispose", new_callable=AsyncMock
            ) as mock_dispose,
        ):
            async with DatabaseConnection(config):
                pass
            mock_dispose.assert_called_once()


class TestDatabaseConnectionTestConnection:
    """Tests for test_connection method."""

    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        """Test test_connection returns True on success."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")
        conn = DatabaseConnection(config)

        mock_async_conn = AsyncMock()
        mock_async_conn.execute = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_async_conn
        mock_cm.__aexit__.return_value = None

        with patch.object(conn, "get_connection", return_value=mock_cm):
            result = await conn.test_connection()
            assert result is True

    @pytest.mark.asyncio
    async def test_test_connection_failure(self):
        """Test test_connection returns False on failure."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")
        conn = DatabaseConnection(config)

        mock_async_conn = AsyncMock()
        mock_async_conn.execute = AsyncMock(side_effect=Exception("Connection failed"))

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_async_conn
        mock_cm.__aexit__.return_value = None

        with patch.object(conn, "get_connection", return_value=mock_cm):
            result = await conn.test_connection()
            assert result is False


class TestDatabaseConnectionGetVersion:
    """Tests for get_version method."""

    @pytest.mark.asyncio
    async def test_get_version_postgresql(self):
        """Test get_version for PostgreSQL."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")
        conn = DatabaseConnection(config)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("PostgreSQL 15.2",)

        mock_async_conn = AsyncMock()
        mock_async_conn.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_async_conn
        mock_cm.__aexit__.return_value = None

        with patch.object(conn, "get_connection", return_value=mock_cm):
            version = await conn.get_version()
            assert version == "PostgreSQL 15.2"

    @pytest.mark.asyncio
    async def test_get_version_mysql(self):
        """Test get_version for MySQL."""
        config = DatabaseConfig(url="mysql://user:pass@host:3306/db")
        conn = DatabaseConnection(config)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("8.0.32",)

        mock_async_conn = AsyncMock()
        mock_async_conn.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_async_conn
        mock_cm.__aexit__.return_value = None

        with patch.object(conn, "get_connection", return_value=mock_cm):
            version = await conn.get_version()
            assert version == "8.0.32"

    @pytest.mark.asyncio
    async def test_get_version_no_result(self):
        """Test get_version returns Unknown when no result."""
        config = DatabaseConfig(url="postgresql://user:pass@host:5432/db")
        conn = DatabaseConnection(config)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None

        mock_async_conn = AsyncMock()
        mock_async_conn.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_async_conn
        mock_cm.__aexit__.return_value = None

        with patch.object(conn, "get_connection", return_value=mock_cm):
            version = await conn.get_version()
            assert version == "Unknown"
