"""Opt-in, session-local PostgreSQL hypothetical-index plan comparison."""

import json
import re
from typing import Any, cast

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from db_connect_mcp.core.connection import DatabaseConnection


class HypoPGResult(BaseModel):
    """Planner estimates, not runtime measurements or a real index."""

    baseline_plan: dict[str, Any]
    hypothetical_plan: dict[str, Any]
    baseline_estimated_cost: float
    hypothetical_estimated_cost: float
    hypothetical_index: str
    hypothetical_index_used: bool
    plans_truncated: bool = Field(
        default=False,
        description="True when either plan exceeded the response limits and was reduced to its root cost.",
    )
    note: str = Field(
        default="Planner estimates only; no query executed, no persistent index created."
    )


class HypoPGComparison:
    """Compare two EXPLAIN plans on one connection with a temporary HypoPG index."""

    MAX_RAW_PLAN_BYTES = 64_000
    MAX_PLAN_NODES = 64
    MAX_PLAN_BYTES = 16_384

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
        async with self.connection.get_connection() as connection:
            # PostgreSQL uses an async SQLAlchemy connection, never the ClickHouse wrapper.
            conn = cast(AsyncConnection, connection)
            oid: int | None = None
            create_attempted = False
            extension_schema: str | None = None
            try:
                # The connection setup uses SET SESSION CHARACTERISTICS, which does
                # not change a transaction that has already begun during checkout.
                await conn.execute(text("SET TRANSACTION READ ONLY"))
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
                # HypoPG keeps hypothetical and hidden indexes across transactions on
                # pooled sessions. Do not reset another borrower's session state.
                for function in ("hypopg", "hypopg_hidden_indexes"):
                    state = await conn.execute(
                        text(
                            f'SELECT EXISTS (SELECT 1 FROM "{extension_schema}".{function}())'
                        )
                    )
                    state_row = state.fetchone()
                    if state_row is None or state_row[0] is None:
                        raise ValueError("Could not verify session-local HypoPG state")
                    if state_row[0]:
                        # Closing this backend on pool return prevents reuse, but
                        # does not mutate another borrower's session-local state.
                        await conn.invalidate()
                        raise ValueError(
                            "Cannot compare with existing session-local HypoPG state"
                        )
                relation = await conn.execute(
                    text(
                        "SELECT c.oid, pg_catalog.has_table_privilege(c.oid, 'SELECT') "
                        "AND pg_catalog.has_schema_privilege(n.oid, 'USAGE') "
                        "FROM pg_catalog.pg_class c "
                        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = :schema AND c.relname = :table AND c.relkind IN ('r', 'p')"
                    ),
                    {"schema": schema, "table": table},
                )
                relation_row = relation.fetchone()
                if relation_row is None:
                    raise ValueError(
                        "Candidate must name an ordinary or partitioned table"
                    )
                if not relation_row[1]:
                    raise ValueError(
                        "Candidate table requires schema USAGE and table SELECT privilege"
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
                create_attempted = True
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
                index_name = str(index_row[1])
                hypothetical = await self._explain(conn, safe_query)
                used = self._uses_index(hypothetical["Plan"], index_name)
                baseline_output, baseline_truncated = self._bounded_plan(baseline)
                hypothetical_output, hypothetical_truncated = self._bounded_plan(
                    hypothetical
                )
                return HypoPGResult(
                    baseline_plan=baseline_output,
                    hypothetical_plan=hypothetical_output,
                    baseline_estimated_cost=float(baseline["Plan"]["Total Cost"]),
                    hypothetical_estimated_cost=float(
                        hypothetical["Plan"]["Total Cost"]
                    ),
                    hypothetical_index=index_sql,
                    hypothetical_index_used=used,
                    plans_truncated=baseline_truncated or hypothetical_truncated,
                )
            finally:
                # A failed statement aborts the transaction, but HypoPG's indexes
                # are session-local and survive rollback. Roll back first, then drop
                # on this very connection. Never return an unverified backend to pool.
                try:
                    await conn.rollback()
                    if oid is not None and extension_schema is not None:
                        dropped = await conn.execute(
                            text(
                                f'SELECT "{extension_schema}".hypopg_drop_index(:oid)'
                            ),
                            {"oid": oid},
                        )
                        row = dropped.fetchone()
                        if row is None or row[0] is not True:
                            raise RuntimeError("HypoPG index cleanup was not confirmed")
                        await conn.rollback()
                    elif create_attempted:
                        # A lost create response can hide a session-local index.
                        await conn.invalidate()
                except BaseException:
                    await conn.invalidate()
                    raise

    @staticmethod
    def _uses_index(plan: dict[str, Any], index_name: str) -> bool:
        pending = [plan]
        while pending:
            node = pending.pop()
            if node.get("Index Name") == index_name:
                return True
            pending.extend(node.get("Plans", []))
        return False

    @classmethod
    def _bounded_plan(cls, plan: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        # Size is tested before copying/serializing an unbounded nested plan.
        pending: list[Any] = [plan]
        plan_nodes = [plan["Plan"]]
        nodes = 0
        while plan_nodes and nodes <= cls.MAX_PLAN_NODES:
            node = plan_nodes.pop()
            nodes += 1
            if isinstance(node, dict):
                plan_nodes.extend(node.get("Plans", []))
        if nodes > cls.MAX_PLAN_NODES:
            return {"Plan": {"Total Cost": plan["Plan"]["Total Cost"]}}, True
        items = 0
        raw_bytes = 0
        while pending:
            value = pending.pop()
            items += 1
            if items > cls.MAX_PLAN_NODES * 32:
                break
            if isinstance(value, dict):
                pending.extend(value.values())
                pending.extend(value.keys())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str):
                if len(value) > cls.MAX_PLAN_BYTES:
                    raw_bytes = cls.MAX_PLAN_BYTES + 1
                    break
                raw_bytes += len(value.encode("utf-8"))
            else:
                raw_bytes += 32  # Numbers and booleans in the planner's JSON.
            if raw_bytes > cls.MAX_PLAN_BYTES:
                break
        if items > cls.MAX_PLAN_NODES * 32 or raw_bytes > cls.MAX_PLAN_BYTES:
            return {"Plan": {"Total Cost": plan["Plan"]["Total Cost"]}}, True
        if (
            len(json.dumps(plan, ensure_ascii=False).encode("utf-8"))
            > cls.MAX_PLAN_BYTES
        ):
            return {"Plan": {"Total Cost": plan["Plan"]["Total Cost"]}}, True
        return plan, False

    @staticmethod
    async def _explain(conn: Any, query: str) -> dict[str, Any]:
        result = await conn.execute(text(f"EXPLAIN (FORMAT JSON) {query}"))
        row = result.fetchone()
        if row is None:
            raise ValueError("Planner returned no plan")
        plan = row[0]
        if isinstance(plan, str):
            if (
                len(plan) > HypoPGComparison.MAX_RAW_PLAN_BYTES
                or len(plan.encode("utf-8")) > HypoPGComparison.MAX_RAW_PLAN_BYTES
            ):
                raise ValueError("Planner output exceeds raw JSON size limit")
            plan = json.loads(plan)
        if not isinstance(plan, list) or not plan or not isinstance(plan[0], dict):
            raise ValueError("Planner returned an invalid plan")
        return plan[0]
