"""Opt-in, bounded access to pg_stat_statements."""

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from db_connect_mcp.core.connection import DatabaseConnection
from db_connect_mcp.models.pg_stat import TopQueriesReport, TopQuery


class PgStatReporter:
    """Read top aggregated queries only when the extension is accessible."""

    def __init__(self, connection: DatabaseConnection):
        self.connection = connection

    async def get_top_queries(
        self,
        limit: int = 10,
        include_query_text: bool = False,
        query_text_limit: int = 200,
    ) -> TopQueriesReport:
        if not 1 <= limit <= 50 or not 1 <= query_text_limit <= 2000:
            raise ValueError(
                "limit and query_text_limit must be within the documented bounds"
            )
        async with self.connection.get_connection() as conn:
            # Resolve the installed extension schema without relying on search_path.
            result = await conn.execute(
                text("""
                SELECT n.nspname FROM pg_catalog.pg_extension e
                JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace
                WHERE e.extname = 'pg_stat_statements'
            """)
            )
            row = result.fetchone()
            if row is None:
                return TopQueriesReport(status="extension_not_installed", queries=[])
            schema = str(row[0]).replace('"', '""')
            try:
                # PG 13+ exposes total_exec_time; older releases use total_time.
                columns = await conn.execute(
                    text("""
                    SELECT a.attname FROM pg_catalog.pg_attribute a
                    JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = :schema AND c.relname = 'pg_stat_statements'
                      AND a.attnum > 0 AND NOT a.attisdropped
                """),
                    {"schema": row[0]},
                )
                names = {str(value[0]) for value in columns.fetchall()}
                if not {"queryid", "calls", "rows", "query", "dbid", "userid"}.issubset(
                    names
                ):
                    return TopQueriesReport(status="unsupported_version", queries=[])
                metric = (
                    "total_exec_time" if "total_exec_time" in names else "total_time"
                )
                if metric not in names:
                    return TopQueriesReport(status="unsupported_version", queries=[])
                # Only rows for current database; no cross-user query text by default.
                rows = await conn.execute(
                    text(f"""
                    SELECT queryid, calls, {metric}, {metric} / NULLIF(calls, 0), rows,
                           CASE WHEN :include_text THEN LEFT(query, :text_limit) ELSE NULL END
                    FROM "{schema}"."pg_stat_statements"
                    WHERE dbid = (SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database())
                      AND userid = (SELECT usesysid FROM pg_catalog.pg_user WHERE usename = current_user)
                    ORDER BY {metric} DESC NULLS LAST, queryid
                    LIMIT :limit
                """),
                    {
                        "include_text": include_query_text,
                        "text_limit": query_text_limit,
                        "limit": limit,
                    },
                )
                return TopQueriesReport(
                    status="available",
                    queries=[
                        TopQuery(
                            query_id=r[0],
                            calls=r[1],
                            total_exec_time_ms=r[2],
                            mean_exec_time_ms=r[3] or 0,
                            rows=r[4],
                            query=r[5],
                        )
                        for r in rows.fetchall()
                    ],
                )
            except DBAPIError as exc:
                # SQLSTATE is provided by asyncpg underneath SQLAlchemy.
                state = getattr(
                    getattr(exc.orig, "__cause__", None), "sqlstate", None
                ) or getattr(exc.orig, "sqlstate", None)
                if state == "42501":
                    return TopQueriesReport(status="permission_denied", queries=[])
                if state in {"55000", "58P01"}:
                    return TopQueriesReport(status="extension_not_loaded", queries=[])
                raise
