"""Column statistics and distribution analysis."""

from typing import TYPE_CHECKING, Optional


from db_connect_mcp.core.connection import DatabaseConnection
from db_connect_mcp.models.statistics import ColumnStats, Distribution

if TYPE_CHECKING:
    from db_connect_mcp.adapters.base import BaseAdapter


class StatisticsAnalyzer:
    """Column statistics and value distribution analysis."""

    def __init__(self, connection: DatabaseConnection, adapter: "BaseAdapter"):
        """
        Initialize statistics analyzer.

        Args:
            connection: Database connection manager
            adapter: Database-specific adapter for statistics queries
        """
        self.connection = connection
        self.adapter = adapter

    async def analyze_column(
        self,
        table_name: str,
        column_name: str,
        schema: Optional[str] = None,
    ) -> ColumnStats:
        """
        Perform comprehensive column statistical analysis.

        Args:
            table_name: Table name
            column_name: Column name
            schema: Schema name

        Returns:
            Column statistics with all available metrics
        """
        async with self.connection.get_connection() as conn:
            # Delegate to adapter for database-specific statistics
            stats = await self.adapter.get_column_statistics(
                conn, table_name, column_name, schema
            )

            return stats

    async def get_value_distribution(
        self,
        table_name: str,
        column_name: str,
        schema: Optional[str] = None,
        limit: int = 20,
    ) -> Distribution:
        """
        Get value distribution (top N most frequent values).

        Args:
            table_name: Table name
            column_name: Column name
            schema: Schema name
            limit: Number of top values to return

        Returns:
            Value distribution with frequencies
        """
        async with self.connection.get_connection() as conn:
            # Delegate to adapter for database-specific distribution query
            distribution = await self.adapter.get_value_distribution(
                conn, table_name, column_name, schema, limit
            )

            return distribution

    async def analyze_multiple_columns(
        self,
        table_name: str,
        column_names: list[str],
        schema: Optional[str] = None,
    ) -> list[ColumnStats]:
        """
        Analyze multiple columns efficiently (batch operation).

        Args:
            table_name: Table name
            column_names: List of column names
            schema: Schema name

        Returns:
            List of column statistics
        """
        results = []

        for column_name in column_names:
            try:
                stats = await self.analyze_column(table_name, column_name, schema)
                results.append(stats)
            except Exception as e:
                # Create stats with error message
                stats = ColumnStats(
                    column=column_name,
                    data_type="unknown",
                    total_rows=0,
                    null_count=0,
                    sample_size=0,
                    warning=f"Failed to analyze: {str(e)}",
                )
                results.append(stats)

        return results
