"""Database connection management with SQLAlchemy."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, Union

from sqlalchemy import text, create_engine, Engine, Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from db_connect_mcp.models.config import DatabaseConfig


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
    """Manages SQLAlchemy async engine and connection pool."""

    def __init__(self, config: DatabaseConfig):
        """
        Initialize database connection.

        Args:
            config: Database configuration with connection URL and pool settings
        """
        self.config = config
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

    async def initialize(self) -> None:
        """Initialize the async or sync engine based on driver requirements."""
        if self.engine is not None or self.sync_engine is not None:
            return  # Already initialized

        # Handle ClickHouse with sync-only driver
        if self._is_sync_only:
            # Create synchronous engine for ClickHouse
            self.sync_engine = create_engine(
                self.config.url,
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

            url_obj = make_url(self.config.url)

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
                    self.config.url = url_obj.render_as_string(hide_password=False)
                elif "ssl" in url_obj.query:
                    ssl_value = url_obj.query["ssl"]
                    if ssl_value in ["require", "true", "1"]:
                        connect_args["ssl"] = "require"
                    elif ssl_value in ["false", "0", "disable"]:
                        connect_args["ssl"] = False
                    # Remove ssl from URL query
                    url_obj = url_obj.difference_update_query(["ssl"])
                    self.config.url = url_obj.render_as_string(hide_password=False)

        # Create async engine for PostgreSQL and MySQL
        self.engine = create_async_engine(
            self.config.url,
            pool_size=self.config.pool_size,
            max_overflow=self.config.max_overflow,
            pool_timeout=self.config.pool_timeout,
            pool_pre_ping=True,  # Verify connections before using
            echo=self.config.echo_sql,
            connect_args=connect_args if connect_args else {},
        )

    async def dispose(self) -> None:
        """Dispose of the connection pool and cleanup resources."""
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None
        if self.sync_engine is not None:
            self.sync_engine.dispose()
            self.sync_engine = None

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
            if self.sync_engine is None:
                raise RuntimeError(
                    "DatabaseConnection not initialized. Call initialize() first."
                )

            # Get sync connection
            sync_conn = self.sync_engine.connect()

            # Monkey-patch the execute method to handle raw SQL strings
            original_execute = sync_conn.execute

            def patched_execute(statement, *args, **kwargs):
                from sqlalchemy import text

                if isinstance(statement, str):
                    statement = text(statement)
                return original_execute(statement, *args, **kwargs)

            sync_conn.execute = patched_execute

            # Wrap it for async
            wrapper = AsyncConnectionWrapper(sync_conn)

            try:
                # Set read-only mode if configured (sync)
                if self.config.read_only:
                    await self._set_readonly_wrapper(wrapper)

                # Set statement timeout if configured (sync)
                if self.config.statement_timeout:
                    await self._set_timeout_wrapper(
                        wrapper, self.config.statement_timeout
                    )

                yield wrapper
            finally:
                wrapper.close()
        else:
            # Handle async engine for PostgreSQL and MySQL
            if self.engine is None:
                raise RuntimeError(
                    "DatabaseConnection not initialized. Call initialize() first."
                )

            async with self.engine.connect() as conn:
                # Set read-only mode if configured
                if self.config.read_only:
                    await self._set_readonly(conn)

                # Set statement timeout if configured
                if self.config.statement_timeout:
                    await self._set_timeout(conn, self.config.statement_timeout)

                yield conn

    async def _set_readonly(self, conn: AsyncConnection) -> None:
        """Set connection to read-only mode based on database dialect."""
        if self._dialect == "postgresql":
            await conn.execute(
                text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            )
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
