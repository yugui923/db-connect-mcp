"""Database connection management with SQLAlchemy."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from src.models.config import DatabaseConfig


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
        self._dialect = config.dialect
        self._driver = config.driver

    async def initialize(self) -> None:
        """Initialize the async engine and connection pool."""
        if self.engine is not None:
            return  # Already initialized

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

        self.engine = create_async_engine(
            self.config.url,
            pool_size=self.config.pool_size,
            max_overflow=self.config.max_overflow,
            pool_timeout=self.config.pool_timeout,
            pool_pre_ping=True,  # Verify connections before using
            echo=self.config.echo_sql,
            connect_args=connect_args if connect_args else None,
        )

    async def dispose(self) -> None:
        """Dispose of the connection pool and cleanup resources."""
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[AsyncConnection, None]:
        """
        Get a connection from the pool as an async context manager.

        Yields:
            AsyncConnection for executing queries

        Raises:
            RuntimeError: If engine not initialized
        """
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

    async def _set_timeout(self, conn: AsyncConnection, timeout: int) -> None:
        """Set statement timeout based on database dialect."""
        timeout_ms = timeout * 1000

        if self._dialect == "postgresql":
            await conn.execute(text(f"SET statement_timeout = {timeout_ms}"))
        elif self._dialect == "mysql":
            await conn.execute(text(f"SET SESSION max_execution_time = {timeout_ms}"))
        elif self._dialect == "clickhouse":
            await conn.execute(text(f"SET max_execution_time = {timeout}"))

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
        return self.engine is not None

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
