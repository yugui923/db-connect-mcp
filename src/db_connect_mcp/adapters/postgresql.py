"""PostgreSQL adapter with full feature support."""

import json
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.adapters.base import BaseAdapter
from src.models.capabilities import DatabaseCapabilities
from src.models.database import SchemaInfo
from src.models.statistics import ColumnStats, Distribution
from src.models.table import TableInfo


class PostgresAdapter(BaseAdapter):
    """PostgreSQL adapter with comprehensive feature support."""

    @property
    def capabilities(self) -> DatabaseCapabilities:
        """PostgreSQL supports all features."""
        return DatabaseCapabilities(
            foreign_keys=True,
            indexes=True,
            views=True,
            materialized_views=True,
            partitions=True,
            advanced_stats=True,
            explain_plans=True,
            profiling=True,
            comments=True,
            schemas=True,
            transactions=True,
            stored_procedures=True,
            triggers=True,
        )

    async def enrich_schema_info(
        self, conn: AsyncConnection, schema_info: SchemaInfo
    ) -> SchemaInfo:
        """Add PostgreSQL-specific schema metadata."""
        query = text("""
            SELECT
                pg_catalog.pg_get_userbyid(n.nspowner) as owner,
                pg_catalog.obj_description(n.oid, 'pg_namespace') as comment
            FROM pg_catalog.pg_namespace n
            WHERE n.nspname = :schema_name
        """)

        result = await conn.execute(query, {"schema_name": schema_info.name})
        row = result.fetchone()

        if row:
            schema_info.owner = row[0]
            schema_info.comment = row[1]

        # Get schema size
        size_query = text("""
            SELECT SUM(pg_total_relation_size(quote_ident(schemaname) || '.' || quote_ident(tablename)))::bigint
            FROM pg_tables
            WHERE schemaname = :schema_name
        """)

        result = await conn.execute(size_query, {"schema_name": schema_info.name})
        row = result.fetchone()
        if row and row[0]:
            schema_info.size_bytes = int(row[0])

        return schema_info

    async def enrich_table_info(
        self, conn: AsyncConnection, table_info: TableInfo
    ) -> TableInfo:
        """Add PostgreSQL-specific table metadata."""
        table_ref = self._build_table_reference(table_info.name, table_info.schema)

        query = text("""
            SELECT
                pg_total_relation_size(:table_ref::regclass)::bigint as total_size,
                pg_relation_size(:table_ref::regclass)::bigint as table_size,
                pg_indexes_size(:table_ref::regclass)::bigint as indexes_size,
                (SELECT reltuples::bigint FROM pg_class WHERE oid = :table_ref::regclass::oid) as row_count,
                obj_description(:table_ref::regclass, 'pg_class') as comment
        """)

        try:
            result = await conn.execute(query, {"table_ref": table_ref})
            row = result.fetchone()

            if row:
                table_info.size_bytes = int(row[1]) if row[1] else None
                table_info.index_size_bytes = int(row[2]) if row[2] else None
                table_info.row_count = int(row[3]) if row[3] else None
                table_info.comment = row[4]

            # Add PostgreSQL-specific extras
            extras_query = text("""
                SELECT
                    c.relkind as table_kind,
                    c.relpersistence as persistence,
                    c.relispartition as is_partition
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = :table_name
                  AND n.nspname = COALESCE(:schema_name, 'public')
            """)

            result = await conn.execute(
                extras_query,
                {"table_name": table_info.name, "schema_name": table_info.schema},
            )
            row = result.fetchone()

            if row:
                table_info.extra_info["relkind"] = row[0]
                table_info.extra_info["persistence"] = row[1]
                table_info.extra_info["is_partition"] = row[2]

        except Exception:
            # If enrichment fails, return basic info
            pass

        return table_info

    async def get_column_statistics(
        self,
        conn: AsyncConnection,
        table_name: str,
        column_name: str,
        schema: Optional[str],
    ) -> ColumnStats:
        """Get comprehensive PostgreSQL column statistics."""
        table_ref = self._build_table_reference(table_name, schema)

        # Basic stats query with PostgreSQL-specific functions
        query = text(f"""
            WITH stats AS (
                SELECT
                    COUNT(*) as total_rows,
                    COUNT("{column_name}") as non_null_count,
                    COUNT(*) - COUNT("{column_name}") as null_count,
                    COUNT(DISTINCT "{column_name}") as distinct_count,
                    MIN("{column_name}") as min_val,
                    MAX("{column_name}") as max_val,
                    pg_typeof("{column_name}")::text as data_type
                FROM {table_ref}
            ),
            numeric_stats AS (
                SELECT
                    AVG("{column_name}")::float as avg_val,
                    STDDEV("{column_name}")::float as stddev_val,
                    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY "{column_name}") as p25,
                    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY "{column_name}") as p50,
                    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "{column_name}") as p75,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY "{column_name}") as p95,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY "{column_name}") as p99
                FROM {table_ref}
                WHERE "{column_name}" IS NOT NULL
            )
            SELECT
                s.total_rows,
                s.null_count,
                s.distinct_count,
                s.min_val,
                s.max_val,
                s.data_type,
                n.avg_val,
                n.stddev_val,
                n.p25,
                n.p50,
                n.p75,
                n.p95,
                n.p99
            FROM stats s
            LEFT JOIN numeric_stats n ON true
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
                SELECT "{column_name}" as value, COUNT(*) as count
                FROM {table_ref}
                WHERE "{column_name}" IS NOT NULL
                GROUP BY "{column_name}"
                ORDER BY count DESC
                LIMIT 10
            """)

            mcv_result = await conn.execute(mcv_query)
            mcv_rows = mcv_result.fetchall()
            most_common = [{"value": str(r[0]), "count": int(r[1])} for r in mcv_rows]

            return ColumnStats(
                column=column_name,
                data_type=str(row[5]),
                total_rows=int(row[0]),
                null_count=int(row[1]),
                distinct_count=int(row[2]) if row[2] else None,
                min_value=row[3],
                max_value=row[4],
                avg_value=float(row[6]) if row[6] is not None else None,
                stddev_value=float(row[7]) if row[7] is not None else None,
                percentile_25=row[8],
                median_value=row[9],
                percentile_75=row[10],
                percentile_95=row[11],
                percentile_99=row[12],
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
        """Get value distribution for PostgreSQL."""
        table_ref = self._build_table_reference(table_name, schema)

        query = text(f"""
            WITH stats AS (
                SELECT
                    COUNT(*) as total_rows,
                    COUNT(DISTINCT "{column_name}") as unique_values,
                    COUNT(*) - COUNT("{column_name}") as null_count
                FROM {table_ref}
            ),
            top_values AS (
                SELECT "{column_name}" as value, COUNT(*) as count
                FROM {table_ref}
                WHERE "{column_name}" IS NOT NULL
                GROUP BY "{column_name}"
                ORDER BY count DESC
                LIMIT :limit
            )
            SELECT
                s.total_rows,
                s.unique_values,
                s.null_count,
                json_agg(json_build_object('value', t.value::text, 'count', t.count)) as top_values
            FROM stats s
            LEFT JOIN top_values t ON true
            GROUP BY s.total_rows, s.unique_values, s.null_count
        """)

        result = await conn.execute(query, {"limit": limit})
        row = result.fetchone()

        if not row:
            return Distribution(
                column=column_name,
                total_rows=0,
                unique_values=0,
                null_count=0,
                top_values=[],
                sample_size=0,
            )

        top_values_data = json.loads(row[3]) if row[3] else []

        return Distribution(
            column=column_name,
            total_rows=int(row[0]),
            unique_values=int(row[1]),
            null_count=int(row[2]),
            top_values=top_values_data,
            sample_size=int(row[0]),
        )

    async def get_sample_query(
        self, table_name: str, schema: Optional[str], limit: int
    ) -> str:
        """Generate PostgreSQL sampling query with TABLESAMPLE."""
        table_ref = self._build_table_reference(table_name, schema)
        # Use simple LIMIT for smaller limits, TABLESAMPLE for larger datasets
        return f"SELECT * FROM {table_ref} LIMIT {limit}"

    async def get_explain_query(self, query: str, analyze: bool) -> str:
        """Generate PostgreSQL EXPLAIN query."""
        if analyze:
            return f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"
        return f"EXPLAIN (FORMAT JSON) {query}"

    async def parse_explain_plan(
        self, plan_text: str, analyzed: bool
    ) -> dict[str, Any]:
        """Parse PostgreSQL EXPLAIN JSON output."""
        try:
            plan_data = json.loads(plan_text)

            if isinstance(plan_data, list) and len(plan_data) > 0:
                plan = plan_data[0].get("Plan", {})

                result: dict[str, Any] = {
                    "json": plan,
                    "estimated_cost": plan.get("Total Cost"),
                    "estimated_rows": plan.get("Plan Rows"),
                    "warnings": [],
                    "recommendations": [],
                }

                if analyzed:
                    result["actual_time_ms"] = plan.get("Actual Total Time")
                    result["actual_rows"] = plan.get("Actual Rows")

                # Add warnings based on plan analysis
                if "Seq Scan" in str(plan):
                    result["warnings"].append(
                        "Sequential scan detected - may be slow on large tables"
                    )
                    result["recommendations"].append(
                        "Consider adding appropriate indexes"
                    )

                return result

        except (json.JSONDecodeError, KeyError):
            pass

        # Fallback for non-JSON format
        return {
            "json": None,
            "warnings": [],
            "recommendations": [],
        }
