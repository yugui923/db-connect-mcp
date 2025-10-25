"""MySQL adapter with good feature support."""

import json
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from db_mcp.adapters.base import BaseAdapter
from db_mcp.models.capabilities import DatabaseCapabilities
from db_mcp.models.database import SchemaInfo
from db_mcp.models.statistics import ColumnStats, Distribution
from db_mcp.models.table import TableInfo


class MySQLAdapter(BaseAdapter):
    """MySQL adapter with good feature support."""

    @property
    def capabilities(self) -> DatabaseCapabilities:
        """MySQL has good but not comprehensive support."""
        return DatabaseCapabilities(
            foreign_keys=True,
            indexes=True,
            views=True,
            materialized_views=False,  # MySQL doesn't have native materialized views
            partitions=True,
            advanced_stats=False,  # No percentile functions in MySQL
            explain_plans=True,
            profiling=False,  # Basic profiling only
            comments=True,
            schemas=True,  # MySQL calls them databases
            transactions=True,
            stored_procedures=True,
            triggers=True,
        )

    async def enrich_schema_info(
        self, conn: AsyncConnection, schema_info: SchemaInfo
    ) -> SchemaInfo:
        """Add MySQL-specific schema metadata."""
        query = text("""
            SELECT
                SUM(data_length + index_length) as size_bytes
            FROM information_schema.TABLES
            WHERE table_schema = :schema_name
        """)

        result = await conn.execute(query, {"schema_name": schema_info.name})
        row = result.fetchone()

        if row and row[0]:
            schema_info.size_bytes = int(row[0])

        return schema_info

    async def enrich_table_info(
        self, conn: AsyncConnection, table_info: TableInfo
    ) -> TableInfo:
        """Add MySQL-specific table metadata."""
        query = text("""
            SELECT
                engine,
                table_rows,
                data_length,
                index_length,
                table_comment,
                create_time,
                update_time
            FROM information_schema.TABLES
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
        """)

        result = await conn.execute(query, {"table_name": table_info.name})
        row = result.fetchone()

        if row:
            table_info.row_count = int(row[1]) if row[1] else None
            table_info.size_bytes = int(row[2]) if row[2] else None
            table_info.index_size_bytes = int(row[3]) if row[3] else None
            table_info.comment = row[4] if row[4] else None
            table_info.created_at = str(row[5]) if row[5] else None
            table_info.updated_at = str(row[6]) if row[6] else None

            # MySQL-specific: storage engine
            table_info.extra_info["engine"] = row[0]

        return table_info

    async def get_column_statistics(
        self,
        conn: AsyncConnection,
        table_name: str,
        column_name: str,
        schema: Optional[str],
    ) -> ColumnStats:
        """Get MySQL column statistics (basic stats only)."""
        table_ref = self._build_table_reference(table_name, schema)

        # MySQL doesn't support percentile functions, so we get basic stats only
        query = text(f"""
            SELECT
                COUNT(*) as total_rows,
                COUNT(*) - COUNT(`{column_name}`) as null_count,
                COUNT(DISTINCT `{column_name}`) as distinct_count,
                MIN(`{column_name}`) as min_val,
                MAX(`{column_name}`) as max_val,
                AVG(`{column_name}`) as avg_val,
                STD(`{column_name}`) as stddev_val
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
                SELECT `{column_name}` as value, COUNT(*) as count
                FROM {table_ref}
                WHERE `{column_name}` IS NOT NULL
                GROUP BY `{column_name}`
                ORDER BY count DESC
                LIMIT 10
            """)

            mcv_result = await conn.execute(mcv_query)
            mcv_rows = mcv_result.fetchall()
            most_common = [{"value": str(r[0]), "count": int(r[1])} for r in mcv_rows]

            # Get data type from information_schema
            type_query = text("""
                SELECT data_type
                FROM information_schema.COLUMNS
                WHERE table_schema = DATABASE()
                  AND table_name = :table_name
                  AND column_name = :column_name
            """)

            type_result = await conn.execute(
                type_query, {"table_name": table_name, "column_name": column_name}
            )
            type_row = type_result.fetchone()
            data_type = type_row[0] if type_row else "unknown"

            return ColumnStats(
                column=column_name,
                data_type=data_type,
                total_rows=int(row[0]),
                null_count=int(row[1]),
                distinct_count=int(row[2]) if row[2] else None,
                min_value=row[3],
                max_value=row[4],
                avg_value=float(row[5]) if row[5] is not None else None,
                stddev_value=float(row[6]) if row[6] is not None else None,
                most_common_values=most_common,
                sample_size=int(row[0]),
                warning="Advanced statistics (percentiles) not available in MySQL",
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
        """Get value distribution for MySQL."""
        table_ref = self._build_table_reference(table_name, schema)

        stats_query = text(f"""
            SELECT
                COUNT(*) as total_rows,
                COUNT(DISTINCT `{column_name}`) as unique_values,
                COUNT(*) - COUNT(`{column_name}`) as null_count
            FROM {table_ref}
        """)

        stats_result = await conn.execute(stats_query)
        stats_row = stats_result.fetchone()

        top_query = text(f"""
            SELECT `{column_name}` as value, COUNT(*) as count
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
        """Generate MySQL sampling query."""
        table_ref = self._build_table_reference(table_name, schema)
        return f"SELECT * FROM {table_ref} LIMIT {limit}"

    async def get_explain_query(self, query: str, analyze: bool) -> str:
        """Generate MySQL EXPLAIN query."""
        if analyze:
            return f"EXPLAIN ANALYZE {query}"
        return f"EXPLAIN FORMAT=JSON {query}"

    async def parse_explain_plan(
        self, plan_text: str, analyzed: bool
    ) -> dict[str, Any]:
        """Parse MySQL EXPLAIN output."""
        try:
            plan_data = json.loads(plan_text)

            result: dict[str, Any] = {
                "json": plan_data,
                "warnings": [],
                "recommendations": [],
            }

            # MySQL EXPLAIN has different structure
            if "query_block" in plan_data:
                query_block = plan_data["query_block"]

                # Extract cost if available
                if "cost_info" in query_block:
                    cost_info = query_block["cost_info"]
                    result["estimated_cost"] = float(cost_info.get("query_cost", 0))

                # Check for table scans
                if "table" in query_block:
                    table = query_block["table"]
                    if table.get("access_type") == "ALL":
                        result["warnings"].append("Full table scan detected")
                        result["recommendations"].append("Consider adding indexes")

            return result

        except (json.JSONDecodeError, KeyError):
            pass

        return {
            "json": None,
            "warnings": [],
            "recommendations": [],
        }
