"""Base adapter abstract class for database-specific implementations."""

import re
from abc import ABC, abstractmethod
from typing import Any, Optional, Union, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncConnection

from db_connect_mcp.models.capabilities import DatabaseCapabilities
from db_connect_mcp.models.database import SchemaInfo
from db_connect_mcp.models.statistics import ColumnStats, Distribution
from db_connect_mcp.models.table import ColumnInfo, TableInfo

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

    async def enrich_column_comments(
        self,
        conn: ConnectionType,
        table_name: str,
        schema: Optional[str],
        columns: list[ColumnInfo],
    ) -> list[ColumnInfo]:
        """
        Enrich column info with database-specific comments.

        This method fetches column comments directly from the database's
        metadata tables, providing more reliable comment retrieval than
        relying solely on SQLAlchemy reflection.

        Args:
            conn: Database connection
            table_name: Table name
            schema: Schema name
            columns: List of column info objects to enrich

        Returns:
            List of columns with comments populated
        """
        # Default implementation does nothing - override in subclasses
        return columns

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

    # Pattern for valid SQL identifiers: letters, digits, underscores
    _VALID_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    @staticmethod
    def _validate_identifier(name: str, kind: str = "identifier") -> None:
        """Validate that a name is a safe SQL identifier.

        Args:
            name: The identifier to validate.
            kind: Description for error messages (e.g. "table", "column", "schema").

        Raises:
            ValueError: If the identifier contains unsafe characters.
        """
        if not BaseAdapter._VALID_IDENTIFIER_RE.match(name):
            raise ValueError(
                f"Invalid {kind} name: {name!r}. "
                f"Only letters, digits, and underscores are allowed."
            )

    def _quote_identifier(self, name: str) -> str:
        """Quote an identifier using the database-appropriate quoting style.

        Default uses double quotes (ANSI SQL / PostgreSQL).
        Override in subclasses for different quoting (e.g. backticks for MySQL/ClickHouse).
        """
        return f'"{name}"'

    def _build_table_reference(self, table_name: str, schema: Optional[str]) -> str:
        """Build qualified table reference with validation and quoting."""
        self._validate_identifier(table_name, "table")
        if schema:
            self._validate_identifier(schema, "schema")
            return (
                f"{self._quote_identifier(schema)}.{self._quote_identifier(table_name)}"
            )
        return self._quote_identifier(table_name)
