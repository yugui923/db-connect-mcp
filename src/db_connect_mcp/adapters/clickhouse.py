"""ClickHouse adapter optimized for analytics workloads."""

from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.adapters.base import BaseAdapter
from src.models.capabilities import DatabaseCapabilities
from src.models.database import SchemaInfo
from src.models.statistics import ColumnStats, Distribution
from src.models.table import TableInfo


class ClickHouseAdapter(BaseAdapter):
    """ClickHouse adapter optimized for analytical queries."""

    @property
    def capabilities(self) -> DatabaseCapabilities:
        """ClickHouse analytics-focused capabilities."""
        return DatabaseCapabilities(
            foreign_keys=False,  # ClickHouse doesn't enforce FK constraints
            indexes=True,  # Has specialized indexes
            views=True,
            materialized_views=True,
            partitions=True,  # Advanced partitioning
            advanced_stats=True,  # Excellent columnar statistics
            explain_plans=True,
            profiling=True,
            comments=True,
            schemas=True,  # Called databases in ClickHouse
            transactions=False,  # No traditional transactions
            stored_procedures=False,
            triggers=False,
        )

    async def enrich_schema_info(
        self, conn: AsyncConnection, schema_info: SchemaInfo
    ) -> SchemaInfo:
        """Add ClickHouse-specific schema metadata."""
        try:
            query = text("""
                SELECT
                    sum(bytes) as size_bytes
                FROM system.parts
                WHERE database = :schema_name
                  AND active = 1
            """)

            result = await conn.execute(query, {"schema_name": schema_info.name})
            row = result.fetchone()

            if row and row[0]:
                schema_info.size_bytes = int(row[0])
        except Exception:
            # Permission denied or table not available
            # This is common for readonly users, just skip enrichment
            pass

        return schema_info

    async def enrich_table_info(
        self, conn: AsyncConnection, table_info: TableInfo
    ) -> TableInfo:
        """Add ClickHouse-specific table metadata."""
        # Get table engine and metadata
        query = text("""
            SELECT
                engine,
                total_rows,
                total_bytes,
                partition_key,
                sorting_key,
                primary_key,
                sampling_key
            FROM system.tables
            WHERE database = currentDatabase()
              AND name = :table_name
        """)

        result = await conn.execute(query, {"table_name": table_info.name})
        row = result.fetchone()

        if row:
            table_info.row_count = int(row[1]) if row[1] else None
            table_info.size_bytes = int(row[2]) if row[2] else None

            # ClickHouse-specific metadata
            table_info.extra_info["engine"] = row[0]
            table_info.extra_info["partition_key"] = row[3]
            table_info.extra_info["sorting_key"] = row[4]
            table_info.extra_info["primary_key"] = row[5]
            table_info.extra_info["sampling_key"] = row[6]

        # Get compression info (may fail due to permissions)
        try:
            compression_query = text("""
                SELECT
                    sum(data_compressed_bytes) as compressed,
                    sum(data_uncompressed_bytes) as uncompressed
                FROM system.parts
                WHERE database = currentDatabase()
                  AND table = :table_name
                  AND active = 1
            """)

            result = await conn.execute(
                compression_query, {"table_name": table_info.name}
            )
            row = result.fetchone()

            if row and row[0]:
                table_info.extra_info["compressed_bytes"] = int(row[0])
                table_info.extra_info["uncompressed_bytes"] = int(row[1])
                if row[1] and row[1] > 0:
                    ratio = float(row[0]) / float(row[1])
                    table_info.extra_info["compression_ratio"] = round(ratio, 2)
        except Exception:
            # Permission denied or table not available
            # This is common for readonly users, just skip compression info
            pass

        return table_info

    async def get_column_statistics(
        self,
        conn: AsyncConnection,
        table_name: str,
        column_name: str,
        schema: Optional[str],
    ) -> ColumnStats:
        """Get ClickHouse column statistics with columnar optimizations."""
        table_ref = self._build_table_reference(table_name, schema)

        # ClickHouse has excellent support for quantiles
        query = text(f"""
            SELECT
                count() as total_rows,
                countIf(`{column_name}` IS NULL) as null_count,
                uniq(`{column_name}`) as distinct_count,
                min(`{column_name}`) as min_val,
                max(`{column_name}`) as max_val,
                avg(`{column_name}`) as avg_val,
                stddevPop(`{column_name}`) as stddev_val,
                quantile(0.25)(`{column_name}`) as p25,
                quantile(0.50)(`{column_name}`) as p50,
                quantile(0.75)(`{column_name}`) as p75,
                quantile(0.95)(`{column_name}`) as p95,
                quantile(0.99)(`{column_name}`) as p99,
                toTypeName(`{column_name}`) as data_type
            FROM {table_ref}
        """)

        try:
            result = await conn.execute(query)
            row = result.fetchone()

            if not row:
                return ColumnStats(
                    column=column_name,
                    data_type="unknown",
                    total_rows=0,
                    null_count=0,
                    sample_size=0,
                    warning="No data found",
                )

            # Get most common values
            mcv_query = text(f"""
                SELECT `{column_name}` as value, count() as count
                FROM {table_ref}
                WHERE `{column_name}` IS NOT NULL
                GROUP BY `{column_name}`
                ORDER BY count DESC
                LIMIT 10
            """)

            mcv_result = await conn.execute(mcv_query)
            mcv_rows = mcv_result.fetchall()
            most_common = [{"value": str(r[0]), "count": int(r[1])} for r in mcv_rows]

            return ColumnStats(
                column=column_name,
                data_type=str(row[12]),
                total_rows=int(row[0]),
                null_count=int(row[1]),
                distinct_count=int(row[2]) if row[2] else None,
                min_value=row[3],
                max_value=row[4],
                avg_value=float(row[5]) if row[5] is not None else None,
                stddev_value=float(row[6]) if row[6] is not None else None,
                percentile_25=row[7],
                median_value=row[8],
                percentile_75=row[9],
                percentile_95=row[10],
                percentile_99=row[11],
                most_common_values=most_common,
                sample_size=int(row[0]),
            )

        except Exception as e:
            return ColumnStats(
                column=column_name,
                data_type="unknown",
                total_rows=0,
                null_count=0,
                sample_size=0,
                warning=f"Statistics unavailable: {str(e)}",
            )

    async def get_value_distribution(
        self,
        conn: AsyncConnection,
        table_name: str,
        column_name: str,
        schema: Optional[str],
        limit: int,
    ) -> Distribution:
        """Get value distribution for ClickHouse."""
        table_ref = self._build_table_reference(table_name, schema)

        stats_query = text(f"""
            SELECT
                count() as total_rows,
                uniq(`{column_name}`) as unique_values,
                countIf(`{column_name}` IS NULL) as null_count
            FROM {table_ref}
        """)

        stats_result = await conn.execute(stats_query)
        stats_row = stats_result.fetchone()

        top_query = text(f"""
            SELECT `{column_name}` as value, count() as count
            FROM {table_ref}
            WHERE `{column_name}` IS NOT NULL
            GROUP BY `{column_name}`
            ORDER BY count DESC
            LIMIT :limit
        """)

        top_result = await conn.execute(top_query, {"limit": limit})
        top_rows = top_result.fetchall()

        top_values = [{"value": str(r[0]), "count": int(r[1])} for r in top_rows]

        if not stats_row:
            return Distribution(
                column=column_name,
                total_rows=0,
                unique_values=0,
                null_count=0,
                top_values=[],
                sample_size=0,
            )

        return Distribution(
            column=column_name,
            total_rows=int(stats_row[0]),
            unique_values=int(stats_row[1]),
            null_count=int(stats_row[2]),
            top_values=top_values,
            sample_size=int(stats_row[0]),
        )

    async def get_sample_query(
        self, table_name: str, schema: Optional[str], limit: int
    ) -> str:
        """Generate ClickHouse sampling query with SAMPLE clause."""
        table_ref = self._build_table_reference(table_name, schema)
        # ClickHouse SAMPLE clause for efficient sampling on large datasets
        return f"SELECT * FROM {table_ref} SAMPLE 0.01 LIMIT {limit}"

    async def get_explain_query(self, query: str, analyze: bool) -> str:
        """Generate ClickHouse EXPLAIN query."""
        if analyze:
            return f"EXPLAIN PIPELINE {query}"
        return f"EXPLAIN {query}"

    async def parse_explain_plan(
        self, plan_text: str, analyzed: bool
    ) -> dict[str, Any]:
        """Parse ClickHouse EXPLAIN output."""
        result: dict[str, Any] = {
            "json": None,
            "warnings": [],
            "recommendations": [],
        }

        # ClickHouse EXPLAIN is text-based
        # Look for common patterns
        if "FULL" in plan_text.upper() and "SCAN" in plan_text.upper():
            result["warnings"].append("Full table scan detected")
            result["recommendations"].append(
                "Consider using appropriate indexes or sampling"
            )

        return result
