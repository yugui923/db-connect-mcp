"""Safe query execution with validation."""

import base64
import datetime
import json
import re
import time
from typing import TYPE_CHECKING, Any, Optional, cast

import orjson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from db_connect_mcp.core.connection import DatabaseConnection
from db_connect_mcp.models.query import ExplainPlan, QueryResult

if TYPE_CHECKING:
    from db_connect_mcp.adapters.base import BaseAdapter


def json_default(obj: Any) -> Any:
    """
    Default handler for orjson to handle database types.

    Handles timezone-aware datetime objects and other special types
    that orjson doesn't natively support.
    """
    # Handle timezone-aware datetime objects
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    elif isinstance(obj, datetime.date):
        return obj.isoformat()
    elif isinstance(obj, datetime.time):
        return obj.isoformat()
    elif isinstance(obj, datetime.timedelta):
        return obj.total_seconds()
    elif isinstance(obj, bytes):
        # Convert bytes to base64 string for JSON serialization
        import base64

        return base64.b64encode(obj).decode("utf-8")
    # Fallback to string representation
    return str(obj)


class QueryExecutor:
    """Safe query execution with validation and limits."""

    # Allowed query types (read-only operations)
    ALLOWED_QUERY_TYPES = {"SELECT", "WITH"}

    def __init__(self, connection: DatabaseConnection, adapter: "BaseAdapter"):
        """
        Initialize query executor.

        Args:
            connection: Database connection manager
            adapter: Database-specific adapter
        """
        self.connection = connection
        self.adapter = adapter

    async def execute_query(
        self,
        query: str,
        params: Optional[dict[str, Any]] = None,
        limit: Optional[int] = 1000,
        *,
        max_result_bytes: int = 100_000,
        sample_preview: bool = False,
    ) -> QueryResult:
        """
        Execute a SELECT/WITH query safely.

        Args:
            query: SQL query to execute
            params: Query parameters for parameterized queries
            limit: Maximum number of rows to return (1 to 10,000)

        Returns:
            Query result with rows and metadata

        Raises:
            ValueError: If query is not a safe read-only query
        """
        # Validate query and enforce a hard output cap even when SQL has its own LIMIT.
        self._validate_query(query)
        self._validate_limit(limit)
        assert limit is not None

        # Bound row count in the SQL sent to the database. The ClickHouse
        # synchronous DBAPI still materializes its result before fetchmany.
        # All accepted query types are SELECT/WITH (possibly prefixed by comments).
        modified_query = (
            f"SELECT * FROM ({query.strip().rstrip(';').rstrip()}\n) AS bounded_query "
            f"LIMIT {limit + 1}"
        )

        start_time = time.time()

        async with self.connection.get_connection() as conn:
            is_clickhouse = self.connection.dialect in {"clickhouse", "clickhousedb"}
            if is_clickhouse:
                result = await conn.execute(text(modified_query), params or {})
            else:
                result = await cast(AsyncConnection, conn).stream(
                    text(modified_query), params or {}
                )
            try:
                columns = list(result.keys())
                # Leave room for the response envelope (timing, count, flags, warning),
                # and account for query/column metadata before fetching any rows.
                budget = (
                    max_result_bytes
                    - len(modified_query.encode("utf-8"))
                    - len(orjson.dumps(columns))
                    - 256
                )
                if budget < 2:
                    raise ValueError(
                        f"Query result exceeds {max_result_bytes} bytes; "
                        "select fewer or smaller columns"
                    )
                rows: list[dict[str, Any]] = []
                used = 2  # JSON array brackets
                truncated = False
                preview_truncated_columns: set[str] = set()
                for index in range(limit + 1):
                    row = (
                        result.fetchone() if is_clickhouse else await result.fetchone()
                    )
                    if row is None:
                        break
                    if index == limit:
                        truncated = True
                        break
                    # A single decoded cell can already be large at this point;
                    # reject it before retaining another row or serializing the array.
                    values = dict(zip(columns, row))
                    if sample_preview:
                        # Preserve the MCP sample preview's 500-character cell
                        # limit before the byte budget rejects a large raw cell.
                        for key, value in values.items():
                            if isinstance(value, bytes):
                                # Only encode the prefix needed for the preview;
                                # do not materialize huge base64 payloads.
                                encoded_preview = base64.b64encode(value[:375]).decode(
                                    "ascii"
                                )
                                if len(value) > 375:
                                    values[key] = encoded_preview[:497] + "..."
                                    preview_truncated_columns.add(key)
                                else:
                                    values[key] = encoded_preview
                            elif isinstance(value, str) and len(value) > 500:
                                values[key] = value[:497] + "..."
                                preview_truncated_columns.add(key)
                    for key, value in values.items():
                        if (
                            isinstance(value, (datetime.datetime, datetime.time))
                            and value.tzinfo is not None
                        ):
                            values[key] = value.isoformat()
                    encoded = orjson.dumps(values, default=json_default)
                    used += len(encoded) + (1 if rows else 0)
                    if used > budget:
                        raise ValueError(
                            f"Query result exceeds {max_result_bytes} bytes; "
                            "select fewer or smaller columns"
                        )
                    rows.append(orjson.loads(encoded))
            finally:
                if is_clickhouse:
                    result.close()
                else:
                    await result.close()

            execution_time = (time.time() - start_time) * 1000
            output = QueryResult(
                query=modified_query,
                rows=rows,
                row_count=len(rows),
                columns=columns,
                execution_time_ms=execution_time,
                truncated=truncated,
                warning="Results truncated to limit" if truncated else None,
            )
            output._preview_truncated_columns = preview_truncated_columns
            return output

    async def sample_data(
        self,
        table_name: str,
        schema: Optional[str] = None,
        limit: int = 100,
    ) -> QueryResult:
        """
        Sample data from a table efficiently.

        Args:
            table_name: Table name
            schema: Schema name
            limit: Number of rows to sample

        Returns:
            Sample data query result
        """
        # Use adapter for database-specific efficient sampling
        query = await self.adapter.get_sample_query(table_name, schema, limit)

        # Existing sample_data truncates individual cells in its MCP handler.
        result = await self.execute_query(
            query, limit=limit, max_result_bytes=1_000_000, sample_preview=True
        )
        # Adapter SQL already limits rows to `limit`, so the outer limit+1
        # cannot determine whether a full sample has more rows behind it.
        if result.row_count == limit and not result.truncated:
            result.truncated = True
            result.warning = "Sample may be truncated to limit"
        return result

    async def explain_query(self, query: str, analyze: bool = False) -> ExplainPlan:
        """
        Get query execution plan.

        Args:
            query: SQL query to explain
            analyze: Whether to actually execute the query (EXPLAIN ANALYZE)

        Returns:
            Execution plan information

        Raises:
            ValueError: If query is not safe or EXPLAIN not supported
        """
        if not self.adapter.capabilities.explain_plans:
            raise ValueError(
                f"EXPLAIN not supported for {self.connection.dialect} database"
            )

        # Validate query is safe
        self._validate_query(query)

        # Get database-specific EXPLAIN syntax
        explain_query = await self.adapter.get_explain_query(query, analyze)

        async with self.connection.get_connection() as conn:
            result = await conn.execute(text(explain_query))
            rows = result.fetchall()

            # Get raw plan output
            # PostgreSQL EXPLAIN (FORMAT JSON) returns JSON as string
            # Other databases may return multiple rows of text
            if len(rows) == 1 and isinstance(rows[0][0], (dict, list)):
                # Some drivers decode EXPLAIN JSON before returning it.
                plan_text = json.dumps(rows[0][0])
            elif len(rows) == 1 and isinstance(rows[0][0], str):
                plan_text = rows[0][0]
            else:
                # Multiple rows - join as text
                plan_lines = []
                for row in rows:
                    plan_lines.append(str(row[0]))
                plan_text = "\n".join(plan_lines)

            # Parse plan (adapter-specific)
            plan_info = await self.adapter.parse_explain_plan(plan_text, analyze)

            # Use human-readable plan if provided, otherwise use raw plan_text
            human_readable_plan = plan_info.get("plan_text", plan_text)

            return ExplainPlan(
                query=query,
                plan=human_readable_plan,
                plan_json=plan_info.get("json"),
                estimated_cost=plan_info.get("estimated_cost"),
                estimated_rows=plan_info.get("estimated_rows"),
                actual_time_ms=plan_info.get("actual_time_ms"),
                actual_rows=plan_info.get("actual_rows"),
                warnings=plan_info.get("warnings", []),
                recommendations=plan_info.get("recommendations", []),
                warnings_omitted=plan_info.get("warnings_omitted", 0),
                recommendations_omitted=plan_info.get("recommendations_omitted", 0),
            )

    @staticmethod
    def _validate_limit(limit: int | None) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 10000
        ):
            raise ValueError("Query limit must be an integer between 1 and 10000")

    def _validate_query(self, query: str) -> None:
        """
        Validate that query is safe (read-only).

        Args:
            query: SQL query to validate

        Raises:
            ValueError: If query is not allowed
        """
        # Ignore SQL strings, quoted identifiers and comments while checking syntax.
        # Unrecognized quoting is rejected rather than risking stacked statements.
        tokens = re.compile(
            r"--[^\n]*|/\*.*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|"
            r"\$(?P<tag>[A-Za-z_][A-Za-z_0-9]*)?\$.*?\$(?P=tag)\$",
            re.DOTALL,
        )
        sanitized = tokens.sub(lambda match: " " * len(match.group()), query)
        # Do not silently accept malformed quoting.
        if (
            "'" in sanitized
            or '"' in sanitized
            or "/*" in sanitized
            or "$" in sanitized
        ):
            raise ValueError("Unterminated SQL quote or comment")
        statement = sanitized.strip()
        if ";" in statement.rstrip().rstrip(";"):
            raise ValueError("Only one SQL statement is allowed")
        normalized = statement.upper()
        first_keyword = normalized.split()[0] if normalized.split() else ""
        if first_keyword not in self.ALLOWED_QUERY_TYPES:
            raise ValueError(
                f"Only SELECT or WITH queries are allowed. Got: {first_keyword}"
            )

        # Check for dangerous keywords outside strings and comments
        dangerous_keywords = {
            "DROP",
            "DELETE",
            "INSERT",
            "UPDATE",
            "TRUNCATE",
            "ALTER",
            "CREATE",
            "GRANT",
            "REVOKE",
        }

        for keyword in dangerous_keywords:
            # Use word boundaries to avoid false positives (e.g., "DESCRIBE")
            if re.search(rf"\b{keyword}\b", normalized):
                raise ValueError(
                    f"Query contains dangerous keyword: {keyword}. "
                    f"Only read-only queries are allowed."
                )

    def _has_limit(self, query: str) -> bool:
        """Check if query already has a LIMIT clause."""
        normalized = query.strip().upper()
        return bool(re.search(r"\bLIMIT\s+\d+", normalized))

    def _add_limit(self, query: str, limit: int) -> str:
        """Add LIMIT clause to query if not present."""
        # Remove trailing semicolon if present
        query = query.rstrip().rstrip(";")

        # Add LIMIT
        return f"{query} LIMIT {limit}"

    async def test_query_syntax(self, query: str) -> tuple[bool, Optional[str]]:
        """
        Test if query has valid syntax without executing it.

        Args:
            query: SQL query to test

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            self._validate_query(query)

            # Try to prepare the query (this checks syntax without executing)
            async with self.connection.get_connection() as conn:
                await conn.execute(text(f"EXPLAIN {query}"))

            return (True, None)
        except Exception as e:
            return (False, str(e))
