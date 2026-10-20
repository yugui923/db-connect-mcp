"""Unit tests for DatabaseConnection and connection wrappers."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

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


@pytest.mark.asyncio
async def test_mysql_read_only_engine_does_not_reuse_sessions() -> None:
    connection = DatabaseConnection(DatabaseConfig(url="mysql://user:pass@host/db"))
    with patch("db_connect_mcp.core.connection.create_async_engine") as create_engine:
        await connection.initialize()
    assert create_engine.call_args.kwargs["poolclass"].__name__ == "NullPool"
    assert "pool_size" not in create_engine.call_args.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("dialect", ["postgresql", "mysql"])
async def test_read_only_null_pool_limits_parallel_checkouts(dialect: str) -> None:
    config = DatabaseConfig(
        url=f"{dialect}://user:pass@host/db",
        pool_size=1,
        max_overflow=1,
        pool_timeout=1,
    )
    connection = DatabaseConnection(config)
    active = 0
    peak = 0

    @asynccontextmanager
    async def connect():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            yield AsyncMock()
        finally:
            active -= 1

    with patch("db_connect_mcp.core.connection.create_async_engine") as create_engine:
        create_engine.return_value.connect.side_effect = connect
        await connection.initialize()
    with patch.object(connection, "_set_readonly", new_callable=AsyncMock):
        entered = [asyncio.Event() for _ in range(2)]
        release = asyncio.Event()

        async def checkout(index: int) -> None:
            async with connection.get_connection():
                if index < 2:
                    entered[index].set()
                await release.wait()

        first, second = (asyncio.create_task(checkout(i)) for i in range(2))
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), 2)
        third = asyncio.create_task(checkout(2))
        await asyncio.sleep(0.05)
        assert peak == 2
        assert not third.done()
        assert active == 2
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second, third), 2)
        assert peak == 2
        assert active == 0


@pytest.mark.asyncio
async def test_null_pool_checkout_timeout_and_cancellation_release_permits() -> None:
    config = DatabaseConfig(
        url="postgresql://user:pass@host/db",
        pool_size=1,
        max_overflow=0,
        pool_timeout=1,
    )
    connection = DatabaseConnection(config)
    active = 0

    @asynccontextmanager
    async def connect():
        nonlocal active
        active += 1
        try:
            yield AsyncMock()
        finally:
            active -= 1

    with patch("db_connect_mcp.core.connection.create_async_engine") as create_engine:
        create_engine.return_value.connect.side_effect = connect
        await connection.initialize()
    with patch.object(connection, "_set_readonly", new_callable=AsyncMock):
        entered = asyncio.Event()
        holder = asyncio.create_task(_hold_checkout(connection, entered))
        await asyncio.wait_for(entered.wait(), 2)
        try:
            with pytest.raises(PoolTimeoutError, match="timed out"):
                async with connection.get_connection():
                    pass
            pending = asyncio.create_task(_hold_checkout(connection, asyncio.Event()))
            await asyncio.sleep(0.05)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert active == 1
        finally:
            holder.cancel()
            with pytest.raises(asyncio.CancelledError):
                await holder
        assert active == 0
        async with connection.get_connection():
            assert active == 1
        assert active == 0


@pytest.mark.asyncio
async def test_waiting_checkout_does_not_reopen_disposed_engine() -> None:
    config = DatabaseConfig(
        url="postgresql://user:pass@host/db", pool_size=1, max_overflow=0
    )
    connection = DatabaseConnection(config)
    with patch("db_connect_mcp.core.connection.create_async_engine") as create_engine:
        create_engine.return_value.dispose = AsyncMock()
        await connection.initialize()
    with patch.object(connection, "_set_readonly", new_callable=AsyncMock):
        entered = asyncio.Event()
        holder = asyncio.create_task(_hold_checkout(connection, entered))
        await asyncio.wait_for(entered.wait(), 2)
        pending = asyncio.create_task(_checkout_once(connection))
        await asyncio.sleep(0.05)
        disposal = asyncio.create_task(connection.dispose())
        await asyncio.sleep(0)
        assert not disposal.done()
        holder.cancel()
        with pytest.raises(asyncio.CancelledError):
            await holder
        await asyncio.wait_for(disposal, 2)
        with pytest.raises(RuntimeError, match="not initialized"):
            await asyncio.wait_for(pending, 2)
    assert create_engine.return_value.connect.call_count == 1


@pytest.mark.asyncio
async def test_dispose_waits_for_checkout_opening_before_stopping_tunnel() -> None:
    connection = DatabaseConnection(
        DatabaseConfig(url="postgresql://user:pass@host/db")
    )
    opening = asyncio.Event()
    allow_open = asyncio.Event()

    @asynccontextmanager
    async def connect():
        opening.set()
        await allow_open.wait()
        yield AsyncMock()

    with patch("db_connect_mcp.core.connection.create_async_engine") as create_engine:
        create_engine.return_value.connect.side_effect = connect
        create_engine.return_value.dispose = AsyncMock()
        await connection.initialize()
    tunnel = MagicMock()
    connection._tunnel_manager = tunnel
    with patch.object(connection, "_set_readonly", new_callable=AsyncMock):
        checkout = asyncio.create_task(_checkout_once(connection))
        await asyncio.wait_for(opening.wait(), 2)
        disposal = asyncio.create_task(connection.dispose())
        await asyncio.sleep(0)
        assert not disposal.done()
        tunnel.stop.assert_not_called()
        allow_open.set()
        await asyncio.wait_for(checkout, 2)
        await asyncio.wait_for(disposal, 2)
    tunnel.stop.assert_called_once()
    create_engine.return_value.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_dispose_does_not_stop_live_checkout_tunnel() -> None:
    connection = DatabaseConnection(
        DatabaseConfig(url="postgresql://user:pass@host/db")
    )
    with patch("db_connect_mcp.core.connection.create_async_engine") as create_engine:
        create_engine.return_value.dispose = AsyncMock()
        await connection.initialize()
    tunnel = MagicMock()
    connection._tunnel_manager = tunnel
    entered = asyncio.Event()
    with patch.object(connection, "_set_readonly", new_callable=AsyncMock):
        holder = asyncio.create_task(_hold_checkout(connection, entered))
        await entered.wait()
        disposal = asyncio.create_task(connection.dispose())
        await asyncio.sleep(0)
        disposal.cancel()
        with pytest.raises(asyncio.CancelledError):
            await disposal
        tunnel.stop.assert_not_called()
        holder.cancel()
        with pytest.raises(asyncio.CancelledError):
            await holder
        await connection.dispose()
    tunnel.stop.assert_called_once()


@pytest.mark.asyncio
async def test_dispose_waits_for_tunnel_start_without_publishing_engine() -> None:
    from db_connect_mcp.models.config import SSHTunnelConfig

    connection = DatabaseConnection(
        DatabaseConfig(
            url="postgresql://user:pass@host/db",
            ssh_tunnel=SSHTunnelConfig(
                ssh_host="bastion", ssh_username="user", ssh_password="password"
            ),
        )
    )
    started = asyncio.Event()
    resume = asyncio.Event()
    tunnel = MagicMock()

    async def start_tunnel() -> None:
        connection._tunnel_manager = tunnel
        started.set()
        await resume.wait()

    with (
        patch.object(connection, "_start_tunnel", side_effect=start_tunnel),
        patch("db_connect_mcp.core.connection.create_async_engine") as create_engine,
    ):
        initialization = asyncio.create_task(connection.initialize())
        await started.wait()
        disposal = asyncio.create_task(connection.dispose())
        await asyncio.sleep(0)
        assert not disposal.done()
        resume.set()
        with pytest.raises(RuntimeError, match="disposing"):
            await asyncio.wait_for(initialization, 2)
        await asyncio.wait_for(disposal, 2)
    create_engine.assert_not_called()
    tunnel.stop.assert_called_once()
    assert not connection.is_initialized


@pytest.mark.asyncio
async def test_cancelled_tunnel_start_does_not_leave_running_tunnel() -> None:
    import threading

    from db_connect_mcp.models.config import SSHTunnelConfig

    connection = DatabaseConnection(
        DatabaseConfig(
            url="postgresql://user:pass@host/db",
            ssh_tunnel=SSHTunnelConfig(
                ssh_host="bastion", ssh_username="user", ssh_password="password"
            ),
        )
    )
    started = threading.Event()
    resume = threading.Event()
    tunnel = MagicMock()

    def start() -> int:
        started.set()
        assert resume.wait(timeout=2)
        return 12345

    tunnel.start.side_effect = start
    with (
        patch("db_connect_mcp.core.tunnel.SSHTunnelManager", return_value=tunnel),
        patch("db_connect_mcp.core.connection.create_async_engine") as create_engine,
    ):
        initialization = asyncio.create_task(connection.initialize())
        assert await asyncio.to_thread(started.wait, 2)
        initialization.cancel()
        disposal = asyncio.create_task(connection.dispose())
        await asyncio.sleep(0)
        assert not disposal.done()
        resume.set()
        with pytest.raises(asyncio.CancelledError):
            await initialization
        await asyncio.wait_for(disposal, 2)
    create_engine.assert_not_called()
    tunnel.stop.assert_called_once()
    assert not connection.is_initialized


@pytest.mark.asyncio
async def test_cancelled_tunnel_start_without_dispose_stops_tunnel() -> None:
    import threading

    from db_connect_mcp.models.config import SSHTunnelConfig

    connection = DatabaseConnection(
        DatabaseConfig(
            url="postgresql://user:pass@host/db",
            ssh_tunnel=SSHTunnelConfig(
                ssh_host="bastion", ssh_username="user", ssh_password="password"
            ),
        )
    )
    started = threading.Event()
    resume = threading.Event()
    tunnel = MagicMock()

    def start() -> int:
        started.set()
        assert resume.wait(timeout=2)
        return 12345

    tunnel.start.side_effect = start
    with patch("db_connect_mcp.core.tunnel.SSHTunnelManager", return_value=tunnel):
        initialization = asyncio.create_task(connection.initialize())
        assert await asyncio.to_thread(started.wait, 2)
        initialization.cancel()
        resume.set()
        with pytest.raises(asyncio.CancelledError):
            await initialization
    tunnel.stop.assert_called_once()
    assert not connection.is_initialized


@pytest.mark.asyncio
async def test_failed_tunnel_start_stops_tunnel_without_external_dispose() -> None:
    from db_connect_mcp.models.config import SSHTunnelConfig
    from db_connect_mcp.core.tunnel import SSHTunnelError

    connection = DatabaseConnection(
        DatabaseConfig(
            url="postgresql://user:pass@host/db",
            ssh_tunnel=SSHTunnelConfig(
                ssh_host="bastion", ssh_username="user", ssh_password="password"
            ),
        )
    )
    tunnel = MagicMock()
    tunnel.start.side_effect = SSHTunnelError("synthetic startup failure")
    with patch("db_connect_mcp.core.tunnel.SSHTunnelManager", return_value=tunnel):
        with pytest.raises(SSHTunnelError, match="synthetic startup failure"):
            await connection.initialize()
    tunnel.stop.assert_called_once()
    assert not connection.is_initialized


@pytest.mark.asyncio
async def test_concurrent_dispose_retries_when_first_cancelled_while_waiting() -> None:
    connection = DatabaseConnection(
        DatabaseConfig(url="postgresql://user:pass@host/db")
    )
    with patch("db_connect_mcp.core.connection.create_async_engine") as create_engine:
        create_engine.return_value.dispose = AsyncMock()
        await connection.initialize()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold() -> None:
        async with connection.get_connection():
            entered.set()
            await release.wait()

    with patch.object(connection, "_set_readonly", new_callable=AsyncMock):
        holder = asyncio.create_task(hold())
        await entered.wait()
        first = asyncio.create_task(connection.dispose())
        await asyncio.sleep(0)
        second = asyncio.create_task(connection.dispose())
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not second.done()
        release.set()
        await holder
        await asyncio.wait_for(second, 2)
    create_engine.return_value.dispose.assert_awaited_once()
    assert not connection.is_initialized


@pytest.mark.asyncio
async def test_concurrent_dispose_retries_cancelled_engine_dispose() -> None:
    connection = DatabaseConnection(
        DatabaseConfig(url="postgresql://user:pass@host/db")
    )
    entered = asyncio.Event()
    resume = asyncio.Event()

    async def dispose_engine() -> None:
        entered.set()
        await resume.wait()

    with patch("db_connect_mcp.core.connection.create_async_engine") as create_engine:
        create_engine.return_value.dispose = AsyncMock(side_effect=dispose_engine)
        await connection.initialize()
    first = asyncio.create_task(connection.dispose())
    await entered.wait()
    second = asyncio.create_task(connection.dispose())
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not second.done()
    resume.set()
    await asyncio.wait_for(second, 2)
    assert create_engine.return_value.dispose.await_count == 2
    assert not connection.is_initialized


@pytest.mark.asyncio
async def test_concurrent_dispose_calls_stop_tunnel_once() -> None:
    connection = DatabaseConnection(
        DatabaseConfig(url="postgresql://user:pass@host/db")
    )
    disposing = asyncio.Event()
    continue_dispose = asyncio.Event()

    async def dispose_engine() -> None:
        disposing.set()
        await continue_dispose.wait()

    with patch("db_connect_mcp.core.connection.create_async_engine") as create_engine:
        create_engine.return_value.dispose = AsyncMock(side_effect=dispose_engine)
        await connection.initialize()
    tunnel = MagicMock()
    connection._tunnel_manager = tunnel
    first = asyncio.create_task(connection.dispose())
    await disposing.wait()
    second = asyncio.create_task(connection.dispose())
    await asyncio.sleep(0)
    assert not second.done()
    continue_dispose.set()
    await asyncio.gather(first, second)
    tunnel.stop.assert_called_once()
    create_engine.return_value.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_engine_disposal_still_stops_tunnel_and_allows_retry() -> None:
    connection = DatabaseConnection(
        DatabaseConfig(url="postgresql://user:pass@host/db")
    )
    with patch("db_connect_mcp.core.connection.create_async_engine") as create_engine:
        create_engine.return_value.dispose = AsyncMock(
            side_effect=[RuntimeError("dispose failed"), None]
        )
        await connection.initialize()
    tunnel = MagicMock()
    connection._tunnel_manager = tunnel
    with pytest.raises(RuntimeError, match="dispose failed"):
        await connection.dispose()
    tunnel.stop.assert_called_once()
    await connection.dispose()
    create_engine.return_value.dispose.assert_awaited()


@pytest.mark.asyncio
async def test_read_only_checkouts_allow_switching_event_loops() -> None:
    connection = DatabaseConnection(
        DatabaseConfig(url="postgresql://user:pass@host/db")
    )
    with patch("db_connect_mcp.core.connection.create_async_engine") as create_engine:
        create_engine.return_value.dispose = AsyncMock()
        await connection.initialize()
    with patch.object(connection, "_set_readonly", new_callable=AsyncMock):
        await _checkout_once(connection)

        def checkout_from_thread() -> None:
            asyncio.run(_checkout_once(connection))

        await asyncio.to_thread(checkout_from_thread)
    assert create_engine.return_value.connect.call_count == 2
    await connection.dispose()


@pytest.mark.asyncio
async def test_clickhouse_dispose_waits_for_active_checkout() -> None:
    connection = DatabaseConnection(
        DatabaseConfig(url="clickhouse://user:pass@host/db")
    )
    with patch("db_connect_mcp.core.connection.create_engine") as create_engine:
        await connection.initialize()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold() -> None:
        async with connection.get_connection():
            entered.set()
            await release.wait()

    with (
        patch.object(connection, "_set_readonly_wrapper", new_callable=AsyncMock),
        patch.object(connection, "_set_timeout_wrapper", new_callable=AsyncMock),
    ):
        checkout = asyncio.create_task(hold())
        await entered.wait()
        disposal = asyncio.create_task(connection.dispose())
        await asyncio.sleep(0)
        assert not disposal.done()
        create_engine.return_value.dispose.assert_not_called()
        release.set()
        await checkout
        await disposal
    create_engine.return_value.dispose.assert_called_once()


async def _checkout_once(connection: DatabaseConnection) -> None:
    async with connection.get_connection():
        pass


async def _hold_checkout(
    connection: DatabaseConnection, entered: asyncio.Event
) -> None:
    async with connection.get_connection():
        entered.set()
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_postgres_marks_current_transaction_read_only() -> None:
    connection = DatabaseConnection(
        DatabaseConfig(url="postgresql://user:pass@host/db")
    )
    conn = AsyncMock()
    await connection._set_readonly(conn)
    statements = [str(call.args[0]) for call in conn.execute.await_args_list]
    assert "SET TRANSACTION READ ONLY" in statements
    assert "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY" in statements


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
