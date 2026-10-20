"""Database connection management with SQLAlchemy."""

import asyncio
import logging
import threading
from concurrent.futures import Future
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncGenerator, Optional, Union

from sqlalchemy import text, create_engine, Engine, Connection
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from db_connect_mcp.models.config import DatabaseConfig

if TYPE_CHECKING:
    from db_connect_mcp.core.tunnel import SSHTunnelManager

logger = logging.getLogger(__name__)


class SyncConnectionWrapper:
    """Wrapper for sync connections to handle text() wrapping."""

    def __init__(self, sync_conn: Connection):
        """Initialize with a sync connection."""
        self.sync_conn = sync_conn
        # Copy important attributes for SQLAlchemy inspection
        self.dialect = sync_conn.dialect
        self.engine = sync_conn.engine
        self.connection = (
            sync_conn.connection if hasattr(sync_conn, "connection") else sync_conn
        )
        self.info = sync_conn.info if hasattr(sync_conn, "info") else {}

    def execute(self, statement, parameters=None):
        """Execute statement, wrapping strings in text()."""
        from sqlalchemy import text

        # Wrap string statements in text() for proper execution
        if isinstance(statement, str):
            statement = text(statement)

        if parameters:
            return self.sync_conn.execute(statement, parameters)
        else:
            return self.sync_conn.execute(statement)

    def __getattr__(self, name):
        """Forward other attributes to the wrapped connection."""
        return getattr(self.sync_conn, name)


class AsyncConnectionWrapper:
    """Wrapper to make sync connections work in async context."""

    def __init__(self, sync_conn: Connection):
        """Initialize with a sync connection."""
        self.sync_conn = sync_conn
        self._executor = None

    async def execute(self, statement, parameters=None):
        """Execute statement in thread pool."""
        from sqlalchemy import text

        # Wrap string statements in text() for proper execution
        if isinstance(statement, str):
            statement = text(statement)

        loop = asyncio.get_event_loop()
        if parameters:
            result = await loop.run_in_executor(
                self._executor, self.sync_conn.execute, statement, parameters
            )
        else:
            result = await loop.run_in_executor(
                self._executor, self.sync_conn.execute, statement
            )
        return result

    async def run_sync(self, fn, *args, **kwargs):
        """Run a synchronous function in thread pool.

        This mimics the SQLAlchemy AsyncConnection.run_sync method.
        """
        loop = asyncio.get_event_loop()
        # For inspection operations, pass the raw connection
        # For execute operations, use the wrapper
        # Check if this is likely an inspection call

        fn_name = fn.__name__ if hasattr(fn, "__name__") else str(fn)

        # If it's a function that needs inspection, pass the raw connection
        if (
            "inspect" in fn_name.lower()
            or "get_schema" in fn_name.lower()
            or "get_table" in fn_name.lower()
            or "describe" in fn_name.lower()
        ):
            result = await loop.run_in_executor(
                self._executor, fn, self.sync_conn, *args, **kwargs
            )
        else:
            # For other operations, use the wrapper
            wrapped_conn = SyncConnectionWrapper(self.sync_conn)
            result = await loop.run_in_executor(
                self._executor, fn, wrapped_conn, *args, **kwargs
            )
        return result

    async def commit(self):
        """Commit transaction in thread pool."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self.sync_conn.commit)

    async def rollback(self):
        """Rollback transaction in thread pool."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self.sync_conn.rollback)

    def close(self):
        """Close the sync connection."""
        self.sync_conn.close()


class DatabaseConnection:
    """Manages SQLAlchemy connections and their checkout lifecycle."""

    def __init__(self, config: DatabaseConfig):
        """
        Initialize database connection.

        Args:
            config: Database configuration with connection URL and pool settings
        """
        self.config = config
        self._original_url = config.url  # Store original URL for reference
        self.engine: Optional[AsyncEngine] = None
        self.sync_engine: Optional[Engine] = None
        self._dialect = config.dialect
        self._driver = config.driver
        # Check if this is ClickHouse (sync only)
        # clickhouse-connect uses 'clickhousedb' as the dialect name in SQLAlchemy
        self._is_sync_only = (
            self._dialect == "clickhouse"
            or self._dialect == "clickhousedb"
            or (self._dialect == "clickhouse" and self._driver == "connect")
        )

        # SSH tunnel support
        self._tunnel_manager: Optional["SSHTunnelManager"] = None
        self._tunneled_url: Optional[str] = None
        self._checkout_limit: threading.BoundedSemaphore | None = None
        self._lifecycle_lock = threading.Lock()
        self._active_checkouts = 0
        self._checkout_idle: Future[None] | None = None
        self._disposed: Future[bool] | None = None
        self._initializing: Future[None] | None = None
        self._disposing = False

    async def initialize(self) -> None:
        """Initialize the async or sync engine based on driver requirements."""
        with self._lifecycle_lock:
            if self._disposing:
                raise RuntimeError("DatabaseConnection is disposing")
            if self.engine is not None or self.sync_engine is not None:
                return  # Already initialized
            if self._initializing is not None:
                raise RuntimeError("DatabaseConnection is initializing")
            initializing: Future[None] = Future()
            self._initializing = initializing
        try:
            await self._initialize_engine()
            with self._lifecycle_lock:
                if self._disposing:
                    raise RuntimeError("DatabaseConnection is disposing")
        except BaseException:
            # A failed or cancelled startup must not strand an SSH listener.
            # A concurrent dispose owns the cleanup when already in progress.
            with self._lifecycle_lock:
                disposing = self._disposing
            if not disposing and self._tunnel_manager is not None:
                self._tunnel_manager.stop()
                self._tunnel_manager = None
                self._tunneled_url = None
            raise
        finally:
            with self._lifecycle_lock:
                initializing.set_result(None)
                self._initializing = None

    async def _initialize_engine(self) -> None:
        # Start SSH tunnel if configured
        if self.config.ssh_tunnel:
            await self._start_tunnel()

        # Use tunneled URL if tunnel is active, otherwise original
        effective_url = self._tunneled_url or self.config.url

        # Handle ClickHouse with sync-only driver
        if self._is_sync_only:
            # Create synchronous engine for ClickHouse
            with self._lifecycle_lock:
                if self._disposing:
                    raise RuntimeError("DatabaseConnection is disposing")
                self.sync_engine = create_engine(
                    effective_url,
                    pool_size=self.config.pool_size,
                    max_overflow=self.config.max_overflow,
                    pool_timeout=self.config.pool_timeout,
                    pool_pre_ping=True,
                    echo=self.config.echo_sql,
                )
            return

        # Extract SSL configuration from URL for asyncpg
        connect_args = {}
        if self._dialect == "postgresql" and self._driver == "asyncpg":
            from sqlalchemy.engine.url import make_url

            url_obj = make_url(effective_url)

            # Check for SSL-related query parameters
            if url_obj.query:
                # asyncpg expects 'ssl' parameter in connect_args, not in URL
                if "sslmode" in url_obj.query:
                    sslmode = url_obj.query["sslmode"]
                    # Map sslmode to asyncpg's ssl parameter
                    if sslmode in ["require", "prefer", "allow"]:
                        connect_args["ssl"] = sslmode
                    elif sslmode == "disable":
                        connect_args["ssl"] = False
                    # Remove sslmode from URL query to avoid "unexpected keyword" error
                    url_obj = url_obj.difference_update_query(["sslmode"])
                    effective_url = url_obj.render_as_string(hide_password=False)
                elif "ssl" in url_obj.query:
                    ssl_value = url_obj.query["ssl"]
                    if ssl_value in ["require", "true", "1"]:
                        connect_args["ssl"] = "require"
                    elif ssl_value in ["false", "0", "disable"]:
                        connect_args["ssl"] = False
                    # Remove ssl from URL query
                    url_obj = url_obj.difference_update_query(["ssl"])
                    effective_url = url_obj.render_as_string(hide_password=False)

        # PostgreSQL advisory locks and MySQL named locks survive rollback.
        # Never reuse a database session across read-only MCP checkouts.
        isolated_sessions = (
            self._dialect in {"postgresql", "mysql"} and self.config.read_only
        )
        pool_options = (
            {"poolclass": NullPool}
            if isolated_sessions
            else {
                "pool_size": self.config.pool_size,
                "max_overflow": self.config.max_overflow,
                "pool_timeout": self.config.pool_timeout,
            }
        )
        with self._lifecycle_lock:
            if self._disposing:
                raise RuntimeError("DatabaseConnection is disposing")
            self.engine = create_async_engine(
                effective_url,
                **pool_options,
                pool_pre_ping=True,  # Verify connections before using
                echo=self.config.echo_sql,
                connect_args=connect_args if connect_args else {},
            )
            # NullPool closes every session on return, but offers no QueuePool-style
            # concurrency bound. Limit open checkouts to the configured pool budget.
            if isolated_sessions:
                self._checkout_limit = threading.BoundedSemaphore(
                    self.config.pool_size + self.config.max_overflow
                )

    async def _start_tunnel(self) -> None:
        """Start SSH tunnel and rewrite database URL."""
        from db_connect_mcp.core.tunnel import (
            SSHTunnelError,
            SSHTunnelManager as TunnelManager,
            rewrite_database_url,
        )
        from db_connect_mcp.models.config import SSHTunnelConfig
        from sqlalchemy.engine.url import make_url

        ssh_tunnel_config = self.config.ssh_tunnel
        if ssh_tunnel_config is None:
            return

        # Copy config to avoid mutating the caller's object
        tunnel_kwargs = ssh_tunnel_config.model_dump()

        # Auto-derive remote_host/remote_port from DATABASE_URL if not set
        if tunnel_kwargs["remote_host"] is None or tunnel_kwargs["remote_port"] is None:
            url_obj = make_url(self.config.url)
            if tunnel_kwargs["remote_host"] is None:
                tunnel_kwargs["remote_host"] = url_obj.host or "127.0.0.1"
                logger.info(
                    f"SSH tunnel remote_host derived from DATABASE_URL: {tunnel_kwargs['remote_host']}"
                )
            if tunnel_kwargs["remote_port"] is None:
                default_ports = {
                    "postgresql": 5432,
                    "mysql": 3306,
                    "clickhouse": 9000,
                }
                fallback_port = default_ports.get(self._dialect, 5432)
                tunnel_kwargs["remote_port"] = url_obj.port or fallback_port
                logger.info(
                    f"SSH tunnel remote_port derived from DATABASE_URL: {tunnel_kwargs['remote_port']}"
                )

        effective_config = SSHTunnelConfig(**tunnel_kwargs)

        try:
            self._tunnel_manager = TunnelManager(effective_config)
            start = asyncio.create_task(asyncio.to_thread(self._tunnel_manager.start))
            try:
                local_port = await asyncio.shield(start)
            except asyncio.CancelledError:
                # Cancelling to_thread does not stop the worker. Keep disposal
                # behind initialization until the tunnel has actually started.
                try:
                    await asyncio.shield(start)
                except Exception:
                    pass  # The original cancellation still wins.
                raise

            # Rewrite URL to use tunnel
            self._tunneled_url = rewrite_database_url(
                self.config.url,
                effective_config.local_host,
                local_port,
            )

            logger.info(f"Database connection will use SSH tunnel on port {local_port}")

        except SSHTunnelError as e:
            logger.error(f"SSH tunnel failed: {e}")
            raise

    async def dispose(self) -> None:
        """Wait for active checkouts before closing the engine and SSH tunnel."""
        while True:
            with self._lifecycle_lock:
                disposed = self._disposed
                if disposed is None:
                    self._disposing = True
                    disposed = Future()
                    self._disposed = disposed
                    initializing = self._initializing
                    break
            # A cancelled or failed owner must not make waiters report success.
            if await asyncio.shield(asyncio.wrap_future(disposed)):
                return
        completed = False
        try:
            if initializing is not None:
                await asyncio.shield(asyncio.wrap_future(initializing))
            with self._lifecycle_lock:
                idle = self._checkout_idle
            if idle is not None:
                # Thread-safe futures can be awaited from another event loop.
                await asyncio.shield(asyncio.wrap_future(idle))
            try:
                if self.engine is not None:
                    await self.engine.dispose()
                    self.engine = None
                if self.sync_engine is not None:
                    self.sync_engine.dispose()
                    self.sync_engine = None
            finally:
                # An interrupted engine disposal leaves the engine for a retry.
                if self._tunnel_manager is not None:
                    self._tunnel_manager.stop()
                    self._tunnel_manager = None
                    self._tunneled_url = None
            completed = True
        finally:
            with self._lifecycle_lock:
                self._disposing = False
                disposed.set_result(completed)
                self._disposed = None

    @asynccontextmanager
    async def get_connection(
        self,
    ) -> AsyncGenerator[Union[AsyncConnection, AsyncConnectionWrapper], None]:
        """
        Get a connection from the pool as an async context manager.

        Yields:
            AsyncConnection or AsyncConnectionWrapper for executing queries

        Raises:
            RuntimeError: If engine not initialized
        """
        # Handle sync engine for ClickHouse
        if self._is_sync_only:
            if self.sync_engine is None or self._disposing:
                raise RuntimeError(
                    "DatabaseConnection not initialized. Call initialize() first."
                )

            self._begin_checkout(self.sync_engine)
            try:
                # A sync checkout cannot yield to disposal while connect() runs.
                sync_conn = self.sync_engine.connect()
                # Monkey-patch execute to handle raw SQL strings.
                original_execute = sync_conn.execute

                def patched_execute(statement, *args, **kwargs):
                    from sqlalchemy import text

                    if isinstance(statement, str):
                        statement = text(statement)
                    return original_execute(statement, *args, **kwargs)

                sync_conn.execute = patched_execute
                wrapper = AsyncConnectionWrapper(sync_conn)
                try:
                    if self.config.read_only:
                        await self._set_readonly_wrapper(wrapper)
                    if self.config.statement_timeout:
                        await self._set_timeout_wrapper(
                            wrapper, self.config.statement_timeout
                        )
                    yield wrapper
                finally:
                    wrapper.close()
            finally:
                self._end_checkout()
        else:
            # Handle async engine for PostgreSQL and MySQL
            if self.engine is None or self._disposing:
                raise RuntimeError(
                    "DatabaseConnection not initialized. Call initialize() first."
                )

            # Only NullPool checkouts need our own budget; QueuePool enforces
            # its own size and timeout. Hold the permit through connection close.
            engine = self.engine
            limit = self._checkout_limit
            if limit is not None:
                # Use short nonblocking attempts so cancellation never leaves a
                # thread that acquires a permit after its checkout is gone.
                deadline = asyncio.get_running_loop().time() + self.config.pool_timeout
                while not limit.acquire(blocking=False):
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise PoolTimeoutError(
                            f"Database checkout timed out after {self.config.pool_timeout}s"
                        )
                    await asyncio.sleep(min(0.01, remaining))
            try:
                self._begin_checkout(engine)
                try:
                    async with engine.connect() as conn:
                        # Set read-only mode if configured
                        if self.config.read_only:
                            await self._set_readonly(conn)

                        # Set statement timeout if configured
                        if self.config.statement_timeout:
                            await self._set_timeout(conn, self.config.statement_timeout)

                        yield conn
                finally:
                    self._end_checkout()
            finally:
                if limit is not None:
                    limit.release()

    def _begin_checkout(self, engine: AsyncEngine | Engine) -> None:
        with self._lifecycle_lock:
            if self._disposing or engine is not (self.sync_engine or self.engine):
                raise RuntimeError(
                    "DatabaseConnection not initialized. Call initialize() first."
                )
            if self._active_checkouts == 0:
                self._checkout_idle = Future()
            self._active_checkouts += 1

    def _end_checkout(self) -> None:
        with self._lifecycle_lock:
            self._active_checkouts -= 1
            if self._active_checkouts == 0 and self._checkout_idle is not None:
                self._checkout_idle.set_result(None)
                self._checkout_idle = None

    async def _set_readonly(self, conn: AsyncConnection) -> None:
        """Set connection to read-only mode based on database dialect."""
        if self._dialect == "postgresql":
            await conn.execute(
                text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            )
            # The command above changes only future transactions. SQLAlchemy has
            # already autobegun this transaction for the SET, so protect it too.
            await conn.execute(text("SET TRANSACTION READ ONLY"))
        elif self._dialect == "mysql":
            await conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
        elif self._dialect == "clickhouse":
            # ClickHouse doesn't have traditional read-only mode
            # Read-only is enforced at user/permission level
            pass

    async def _set_readonly_wrapper(self, wrapper: AsyncConnectionWrapper) -> None:
        """Set connection to read-only mode for wrapped sync connections."""
        if self._dialect == "clickhouse":
            # ClickHouse doesn't have traditional read-only mode
            pass

    async def _set_timeout(self, conn: AsyncConnection, timeout: int) -> None:
        """Set statement timeout based on database dialect."""
        timeout_ms = timeout * 1000

        if self._dialect == "postgresql":
            await conn.execute(text(f"SET statement_timeout = {timeout_ms}"))
        elif self._dialect == "mysql":
            await conn.execute(text(f"SET SESSION max_execution_time = {timeout_ms}"))
        elif self._dialect == "clickhouse":
            await conn.execute(text(f"SET max_execution_time = {timeout}"))

    async def _set_timeout_wrapper(
        self, wrapper: AsyncConnectionWrapper, timeout: int
    ) -> None:
        """Set statement timeout for wrapped sync connections."""
        if self._dialect == "clickhouse":
            await wrapper.execute(text(f"SET max_execution_time = {timeout}"))

    @property
    def dialect(self) -> str:
        """Get database dialect name."""
        return self._dialect

    @property
    def driver(self) -> str:
        """Get database driver name."""
        return self._driver

    @property
    def is_initialized(self) -> bool:
        """Check if engine is initialized."""
        return self.engine is not None or self.sync_engine is not None

    @property
    def is_tunneled(self) -> bool:
        """Check if connection uses SSH tunnel."""
        return self._tunnel_manager is not None and self._tunnel_manager.is_active

    async def test_connection(self) -> bool:
        """
        Test database connectivity.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            async with self.get_connection() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def get_version(self) -> str:
        """
        Get database version string.

        Returns:
            Database version string
        """
        version_query = {
            "postgresql": "SELECT version()",
            "mysql": "SELECT VERSION()",
            "clickhouse": "SELECT version()",
        }

        query = version_query.get(self._dialect, "SELECT version()")

        async with self.get_connection() as conn:
            result = await conn.execute(text(query))
            row = result.fetchone()
            return str(row[0]) if row else "Unknown"

    async def __aenter__(self) -> "DatabaseConnection":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.dispose()
