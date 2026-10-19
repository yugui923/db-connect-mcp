"""Opt-in, session-local PostgreSQL hypothetical-index plan comparison."""

import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text

from db_connect_mcp.core.connection import DatabaseConnection


class HypoPGResult(BaseModel):
    """Planner estimates, not runtime measurements or a real index."""

    baseline_plan: dict[str, Any]
    hypothetical_plan: dict[str, Any]
    baseline_estimated_cost: float
    hypothetical_estimated_cost: float
    hypothetical_index: str
    note: str = Field(
        default="Planner estimates only; no query executed, no persistent index created."
    )


class HypoPGComparison:
    """Compare two EXPLAIN plans on one connection with a temporary HypoPG index."""

    def __init__(self, connection: DatabaseConnection):
        self.connection = connection

    @staticmethod
    def validate_identifier(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,62}", value):
            raise ValueError(
                "Only simple PostgreSQL identifiers (up to 63 characters) are supported"
            )
        return value

    @staticmethod
    def validate_query(query: str) -> str:
        # Fail closed: do not reuse the permissive general query executor validator.
        # No comments, string literals, placeholders, calls, semicolons or CTEs.
        if len(query) > 8192 or not re.match(r"^\s*SELECT\s", query, re.IGNORECASE):
            raise ValueError("Only a single bounded SELECT is supported")
        if not re.fullmatch(r"[A-Za-z_0-9\s.,*=<>!+-]+", query):
            raise ValueError("Unsupported SQL characters")
        if re.search(r"(;|--|/\*|\*/|\$|'|\"|\(|\)|\\)", query):
            raise ValueError(
                "Comments, literals, functions and multiple statements are not supported"
            )
        if re.search(
            r"\b(WITH|INTO|FOR|UPDATE|INSERT|DELETE|DROP|CREATE|ALTER|EXPLAIN|ANALYZE|LOCK|COPY|EXECUTE|DO|CALL|SET|RESET|GRANT|REVOKE)\b",
            query,
            re.IGNORECASE,
        ):
            raise ValueError("Query contains an unsupported keyword")
        return query.strip()

    async def compare(
        self,
        query: str,
        schema: str,
        table: str,
        columns: list[str],
        *,
        opt_in: bool = False,
    ) -> HypoPGResult:
        """Compare bounded planner estimates; never install HypoPG or create a real index."""
        if not opt_in:
            raise ValueError("HypoPG comparison requires explicit opt-in")
        if self.connection.dialect != "postgresql":
            raise ValueError("HypoPG comparison is PostgreSQL-only")
        if not self.connection.config.read_only:
            raise ValueError(
                "HypoPG comparison requires a read-only database connection"
            )
        safe_query = self.validate_query(query)
        schema = self.validate_identifier(schema)
        table = self.validate_identifier(table)
        if not 1 <= len(columns) <= 4 or len(set(columns)) != len(columns):
            raise ValueError("Specify 1 to 4 distinct index columns")
        columns = [self.validate_identifier(column) for column in columns]
        quoted_columns = ", ".join('"' + column + '"' for column in columns)
        index_sql = f'CREATE INDEX ON "{schema}"."{table}" ({quoted_columns})'
        async with self.connection.get_connection() as conn:
            try:
                await conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
                await conn.execute(text("SET LOCAL lock_timeout = '1000ms'"))
                extension = await conn.execute(
                    text(
                        "SELECT n.nspname FROM pg_catalog.pg_extension e "
                        "JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace "
                        "WHERE e.extname = 'hypopg'"
                    )
                )
                row = extension.fetchone()
                if row is None:
                    raise ValueError(
                        "HypoPG is not installed; ask a database administrator to provision it"
                    )
                extension_schema = self.validate_identifier(row[0])
                relation = await conn.execute(
                    text(
                        "SELECT c.oid FROM pg_catalog.pg_class c "
                        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = :schema AND c.relname = :table AND c.relkind IN ('r', 'p')"
                    ),
                    {"schema": schema, "table": table},
                )
                if relation.fetchone() is None:
                    raise ValueError(
                        "Candidate must name an accessible ordinary or partitioned table"
                    )
                available = await conn.execute(
                    text(
                        "SELECT a.attname FROM pg_catalog.pg_attribute a "
                        "JOIN pg_catalog.pg_class c ON c.oid = a.attrelid "
                        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = :schema AND c.relname = :table "
                        "AND a.attnum > 0 AND NOT a.attisdropped"
                    ),
                    {"schema": schema, "table": table},
                )
                if not set(columns).issubset({r[0] for r in available.fetchall()}):
                    raise ValueError("Candidate columns must exist on the named table")
                baseline = await self._explain(conn, safe_query)
                created = await conn.execute(
                    text(
                        f'SELECT * FROM "{extension_schema}".hypopg_create_index(:definition)'
                    ),
                    {"definition": index_sql},
                )
                index_row = created.fetchone()
                if index_row is None:
                    raise ValueError("HypoPG did not return a hypothetical index")
                oid = int(index_row[0])
                try:
                    hypothetical = await self._explain(conn, safe_query)
                finally:
                    await conn.execute(
                        text(f'SELECT "{extension_schema}".hypopg_drop_index(:oid)'),
                        {"oid": oid},
                    )
                return HypoPGResult(
                    baseline_plan=baseline,
                    hypothetical_plan=hypothetical,
                    baseline_estimated_cost=float(baseline["Plan"]["Total Cost"]),
                    hypothetical_estimated_cost=float(
                        hypothetical["Plan"]["Total Cost"]
                    ),
                    hypothetical_index=index_sql,
                )
            finally:
                # Transactional cleanup even if detection, creation or EXPLAIN fails.
                await conn.rollback()

    @staticmethod
    async def _explain(conn: Any, query: str) -> dict[str, Any]:
        result = await conn.execute(text(f"EXPLAIN (FORMAT JSON) {query}"))
        row = result.fetchone()
        if row is None:
            raise ValueError("Planner returned no plan")
        plan = row[0]
        if isinstance(plan, str):
            import json

            plan = json.loads(plan)
        return plan[0]
