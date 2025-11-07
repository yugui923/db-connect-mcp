"""PostgreSQL adapter with full feature support."""

import json
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from db_connect_mcp.adapters.base import BaseAdapter
from db_connect_mcp.models.capabilities import DatabaseCapabilities
from db_connect_mcp.models.database import SchemaInfo
from db_connect_mcp.models.profile import DatabaseProfile, SchemaProfile, TableProfile
from db_connect_mcp.models.statistics import ColumnStats, Distribution
from db_connect_mcp.models.table import TableInfo


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
        # Build schema-qualified table name for regclass casting
        # Must use format string, not parameter binding, for regclass
        schema_name = table_info.schema or "public"
        table_ident = f'"{schema_name}"."{table_info.name}"'

        # Use format string for regclass casting (parameter binding doesn't work with ::regclass)
        query = text(f"""
            SELECT
                pg_total_relation_size('{table_ident}'::regclass)::bigint as total_size,
                pg_relation_size('{table_ident}'::regclass)::bigint as table_size,
                pg_indexes_size('{table_ident}'::regclass)::bigint as indexes_size,
                (SELECT reltuples::bigint FROM pg_class WHERE oid = '{table_ident}'::regclass::oid) as row_count,
                obj_description('{table_ident}'::regclass, 'pg_class') as comment
        """)

        try:
            result = await conn.execute(query)
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

        except Exception as e:
            # Log the error for debugging but don't fail completely
            import logging

            logging.getLogger(__name__).warning(
                f"Failed to enrich table info for {table_info.schema}.{table_info.name}: {e}"
            )

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

        # First, get the column data type to determine what statistics to compute
        type_query = text(f"""
            SELECT pg_typeof("{column_name}")::text as data_type
            FROM {table_ref}
            WHERE "{column_name}" IS NOT NULL
            LIMIT 1
        """)

        try:
            type_result = await conn.execute(type_query)
            type_row = type_result.fetchone()
            data_type = type_row[0] if type_row else "unknown"
        except Exception:
            data_type = "unknown"

        # Determine if this is a numeric type
        numeric_types = {
            "integer",
            "bigint",
            "smallint",
            "numeric",
            "decimal",
            "real",
            "double precision",
            "float",
            "float4",
            "float8",
            "int",
            "int2",
            "int4",
            "int8",
            "money",
        }
        is_numeric = any(nt in data_type.lower() for nt in numeric_types)

        # Build query based on data type
        if is_numeric:
            # Full numeric statistics with percentiles
            query = text(f"""
                SELECT
                    COUNT(*) as total_rows,
                    COUNT(*) - COUNT("{column_name}") as null_count,
                    COUNT(DISTINCT "{column_name}") as distinct_count,
                    MIN("{column_name}") as min_val,
                    MAX("{column_name}") as max_val,
                    '{data_type}' as data_type,
                    AVG("{column_name}")::float as avg_val,
                    STDDEV("{column_name}")::float as stddev_val,
                    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY "{column_name}") as p25,
                    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY "{column_name}") as p50,
                    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY "{column_name}") as p75,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY "{column_name}") as p95,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY "{column_name}") as p99
                FROM {table_ref}
            """)
        else:
            # Basic statistics for non-numeric types
            query = text(f"""
                SELECT
                    COUNT(*) as total_rows,
                    COUNT(*) - COUNT("{column_name}") as null_count,
                    COUNT(DISTINCT "{column_name}") as distinct_count,
                    MIN("{column_name}")::text as min_val,
                    MAX("{column_name}")::text as max_val,
                    '{data_type}' as data_type,
                    NULL::float as avg_val,
                    NULL::float as stddev_val,
                    NULL as p25,
                    NULL as p50,
                    NULL as p75,
                    NULL as p95,
                    NULL as p99
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

            # Get most common values (convert to text for consistency)
            mcv_query = text(f"""
                SELECT "{column_name}"::text as value, COUNT(*) as count
                FROM {table_ref}
                WHERE "{column_name}" IS NOT NULL
                GROUP BY "{column_name}"
                ORDER BY count DESC
                LIMIT 10
            """)

            mcv_result = await conn.execute(mcv_query)
            mcv_rows = mcv_result.fetchall()
            most_common = [{"value": str(r[0]), "count": int(r[1])} for r in mcv_rows]

            # Convert values to JSON-safe formats
            from db_connect_mcp.utils import convert_value_to_json_safe

            return ColumnStats(
                column=column_name,
                data_type=str(row[5]),
                total_rows=int(row[0]),
                null_count=int(row[1]),
                distinct_count=int(row[2]) if row[2] else None,
                min_value=convert_value_to_json_safe(row[3]),
                max_value=convert_value_to_json_safe(row[4]),
                avg_value=float(row[6]) if row[6] is not None else None,
                stddev_value=float(row[7]) if row[7] is not None else None,
                percentile_25=convert_value_to_json_safe(row[8]),
                median_value=convert_value_to_json_safe(row[9]),
                percentile_75=convert_value_to_json_safe(row[10]),
                percentile_95=convert_value_to_json_safe(row[11]),
                percentile_99=convert_value_to_json_safe(row[12]),
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
            # Parse the JSON plan
            plan_data = json.loads(plan_text)

            if isinstance(plan_data, list) and len(plan_data) > 0:
                # Get the full plan structure
                plan_obj = plan_data[0]
                plan = plan_obj.get("Plan", {})

                # Generate human-readable text from JSON plan
                plan_text_readable = self._format_plan_text(plan, indent=0)

                result: dict[str, Any] = {
                    "json": plan_data,  # Return full plan including metadata
                    "plan_text": plan_text_readable,  # Human-readable format
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

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # If JSON parsing fails, treat as text format
            return {
                "json": None,
                "plan_text": plan_text,
                "warnings": [f"Could not parse EXPLAIN output as JSON: {e}"],
                "recommendations": [],
            }

        # Fallback for non-JSON format
        return {
            "json": None,
            "plan_text": plan_text,
            "warnings": [],
            "recommendations": [],
        }

    def _format_plan_text(self, plan: dict[str, Any], indent: int = 0) -> str:
        """Format JSON plan as human-readable text."""
        lines = []
        prefix = "  " * indent

        # Node type and operation
        node_type = plan.get("Node Type", "Unknown")
        lines.append(f"{prefix}{node_type}")

        # Add key information
        if "Relation Name" in plan:
            lines[-1] += f" on {plan['Relation Name']}"
        if "Alias" in plan and plan["Alias"] != plan.get("Relation Name"):
            lines[-1] += f" (alias: {plan['Alias']})"

        # Cost and rows
        startup_cost = plan.get("Startup Cost", 0)
        total_cost = plan.get("Total Cost", 0)
        rows = plan.get("Plan Rows", 0)
        width = plan.get("Plan Width", 0)
        cost_info = f"{prefix}  (cost={startup_cost:.2f}..{total_cost:.2f} rows={rows} width={width})"
        lines.append(cost_info)

        # Actual statistics if available
        if "Actual Total Time" in plan:
            actual_time = plan["Actual Total Time"]
            actual_rows = plan.get("Actual Rows", 0)
            actual_loops = plan.get("Actual Loops", 1)
            lines.append(
                f"{prefix}  (actual time={actual_time:.3f} rows={actual_rows} loops={actual_loops})"
            )

        # Filter conditions
        if "Filter" in plan:
            lines.append(f"{prefix}  Filter: {plan['Filter']}")
        if "Index Cond" in plan:
            lines.append(f"{prefix}  Index Cond: {plan['Index Cond']}")

        # Child plans
        if "Plans" in plan:
            for child_plan in plan["Plans"]:
                lines.append("")  # Blank line before child
                lines.append(self._format_plan_text(child_plan, indent + 1))

        return "\n".join(lines)

    async def profile_database(
        self, conn: AsyncConnection, database_name: str
    ) -> DatabaseProfile:
        """Generate comprehensive PostgreSQL database profile."""
        # Get database version
        version_query = text("SELECT version()")
        version_result = await conn.execute(version_query)
        version_row = version_result.fetchone()
        version = version_row[0] if version_row else "Unknown"

        # Get total database size
        size_query = text("SELECT pg_database_size(current_database())::bigint")
        size_result = await conn.execute(size_query)
        size_row = size_result.fetchone()
        total_size = int(size_row[0]) if size_row and size_row[0] else None

        # Get schema statistics (excluding system schemas)
        schema_query = text("""
            SELECT
                n.nspname as schema_name,
                COUNT(DISTINCT c.relname) FILTER (WHERE c.relkind = 'r') as table_count,
                COUNT(DISTINCT c.relname) FILTER (WHERE c.relkind = 'v') as view_count,
                COALESCE(SUM(pg_total_relation_size(c.oid)) FILTER (WHERE c.relkind = 'r'), 0)::bigint as total_size,
                COALESCE(SUM(c.reltuples) FILTER (WHERE c.relkind = 'r'), 0)::bigint as total_rows
            FROM pg_namespace n
            LEFT JOIN pg_class c ON n.oid = c.relnamespace
            WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            GROUP BY n.nspname
            ORDER BY total_size DESC
        """)

        schema_result = await conn.execute(schema_query)
        schema_rows = schema_result.fetchall()

        schemas = []
        total_tables = 0
        total_views = 0
        for row in schema_rows:
            schema_profile = SchemaProfile(
                name=row[0],
                table_count=int(row[1]) if row[1] else 0,
                view_count=int(row[2]) if row[2] else 0,
                total_size_bytes=int(row[3]) if row[3] else 0,
                total_rows=int(row[4]) if row[4] else 0,
            )
            schemas.append(schema_profile)
            total_tables += schema_profile.table_count
            total_views += schema_profile.view_count or 0

        # Get largest tables (top 20)
        tables_query = text("""
            SELECT
                n.nspname as schema_name,
                c.relname as table_name,
                CASE
                    WHEN c.relkind = 'r' THEN 'BASE TABLE'
                    WHEN c.relkind = 'v' THEN 'VIEW'
                    WHEN c.relkind = 'm' THEN 'MATERIALIZED VIEW'
                    ELSE 'OTHER'
                END as table_type,
                pg_total_relation_size(c.oid)::bigint as total_size,
                pg_indexes_size(c.oid)::bigint as index_size,
                c.reltuples::bigint as row_count
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'v', 'm')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY total_size DESC
            LIMIT 20
        """)

        tables_result = await conn.execute(tables_query)
        tables_rows = tables_result.fetchall()

        largest_tables = []
        for row in tables_rows:
            table_profile = TableProfile(
                schema=row[0],
                name=row[1],
                table_type=row[2],
                size_bytes=int(row[3]) if row[3] else 0,
                index_size_bytes=int(row[4]) if row[4] else 0,
                row_count=int(row[5]) if row[5] else 0,
            )
            largest_tables.append(table_profile)

        # Get total index size
        index_query = text("""
            SELECT
                COALESCE(SUM(pg_indexes_size(c.oid)), 0)::bigint as total_index_size,
                COALESCE(SUM(pg_relation_size(c.oid)), 0)::bigint as total_table_size
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
              AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        """)

        index_result = await conn.execute(index_query)
        index_row = index_result.fetchone()
        total_index_size = int(index_row[0]) if index_row and index_row[0] else 0
        total_table_size = int(index_row[1]) if index_row and index_row[1] else 0

        index_ratio = None
        if total_table_size > 0:
            index_ratio = total_index_size / total_table_size

        # Get total number of indexes
        index_count_query = text("""
            SELECT COUNT(*)::bigint
            FROM pg_indexes
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        """)

        index_count_result = await conn.execute(index_count_query)
        index_count_row = index_count_result.fetchone()
        total_indexes = int(index_count_row[0]) if index_count_row else 0

        return DatabaseProfile(
            database_name=database_name,
            version=version,
            total_size_bytes=total_size,
            total_schemas=len(schemas),
            total_tables=total_tables,
            total_views=total_views,
            total_indexes=total_indexes,
            schemas=schemas,
            largest_tables=largest_tables,
            total_index_size_bytes=total_index_size,
            index_to_table_ratio=index_ratio,
        )
