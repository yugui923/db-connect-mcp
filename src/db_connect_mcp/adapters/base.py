"""Base adapter abstract class for database-specific implementations."""

from abc import ABC, abstractmethod
from typing import Any, Optional, Union, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncConnection

from db_connect_mcp.models.capabilities import DatabaseCapabilities
from db_connect_mcp.models.database import SchemaInfo
from db_connect_mcp.models.profile import DatabaseProfile
from db_connect_mcp.models.statistics import ColumnStats, Distribution
from db_connect_mcp.models.table import TableInfo

if TYPE_CHECKING:
    from db_connect_mcp.core.connection import AsyncConnectionWrapper

# Type alias for connection types
ConnectionType = Union[AsyncConnection, "AsyncConnectionWrapper"]


class BaseAdapter(ABC):
    """Base adapter defining database-specific interface."""

    @property
    @abstractmethod
    def capabilities(self) -> DatabaseCapabilities:
        """Get capabilities for this database type."""
        ...

    @abstractmethod
    async def enrich_schema_info(
        self, conn: ConnectionType, schema_info: SchemaInfo
    ) -> SchemaInfo:
        """
        Enrich schema info with database-specific metadata.

        Args:
            conn: Database connection
            schema_info: Basic schema information

        Returns:
            Enriched schema information
        """
        ...

    @abstractmethod
    async def enrich_table_info(
        self, conn: ConnectionType, table_info: TableInfo
    ) -> TableInfo:
        """
        Enrich table info with database-specific metadata.

        Args:
            conn: Database connection
            table_info: Basic table information

        Returns:
            Enriched table information with sizes, row counts, etc.
        """
        ...

    @abstractmethod
    async def get_column_statistics(
        self,
        conn: ConnectionType,
        table_name: str,
        column_name: str,
        schema: Optional[str],
    ) -> ColumnStats:
        """
        Get column statistics using database-specific queries.

        Args:
            conn: Database connection
            table_name: Table name
            column_name: Column name
            schema: Schema name

        Returns:
            Column statistics
        """
        ...

    @abstractmethod
    async def get_value_distribution(
        self,
        conn: ConnectionType,
        table_name: str,
        column_name: str,
        schema: Optional[str],
        limit: int,
    ) -> Distribution:
        """
        Get value distribution for a column.

        Args:
            conn: Database connection
            table_name: Table name
            column_name: Column name
            schema: Schema name
            limit: Number of top values

        Returns:
            Value distribution
        """
        ...

    @abstractmethod
    async def get_sample_query(
        self, table_name: str, schema: Optional[str], limit: int
    ) -> str:
        """
        Generate database-specific efficient sampling query.

        Args:
            table_name: Table name
            schema: Schema name
            limit: Number of rows to sample

        Returns:
            SQL query for sampling
        """
        ...

    @abstractmethod
    async def get_explain_query(self, query: str, analyze: bool) -> str:
        """
        Generate database-specific EXPLAIN query.

        Args:
            query: Query to explain
            analyze: Whether to use EXPLAIN ANALYZE

        Returns:
            EXPLAIN query string
        """
        ...

    @abstractmethod
    async def parse_explain_plan(
        self, plan_text: str, analyzed: bool
    ) -> dict[str, Any]:
        """
        Parse EXPLAIN output into structured format.

        Args:
            plan_text: Raw EXPLAIN output
            analyzed: Whether this was EXPLAIN ANALYZE

        Returns:
            Dictionary with parsed plan information
        """
        ...

    @abstractmethod
    async def profile_database(
        self, conn: ConnectionType, database_name: str
    ) -> DatabaseProfile:
        """
        Generate comprehensive database profiling information.

        Args:
            conn: Database connection
            database_name: Name of the database

        Returns:
            Database profile with statistics
        """
        ...

    def _build_table_reference(self, table_name: str, schema: Optional[str]) -> str:
        """Build qualified table reference."""
        if schema:
            return f"{schema}.{table_name}"
        return table_name
