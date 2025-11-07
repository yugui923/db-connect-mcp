"""Safe query execution with validation."""

import re
import time
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import text

from db_connect_mcp.core.connection import DatabaseConnection
from db_connect_mcp.models.query import ExplainPlan, QueryResult
from db_connect_mcp.utils import convert_rows_to_json_safe

if TYPE_CHECKING:
    from db_connect_mcp.adapters.base import BaseAdapter


class QueryExecutor:
    """Safe query execution with validation and limits."""

    # Allowed query types (read-only operations)
    ALLOWED_QUERY_TYPES = {"SELECT", "WITH", "SHOW", "DESCRIBE", "EXPLAIN"}

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
    ) -> QueryResult:
        """
        Execute a SELECT/WITH query safely.

        Args:
            query: SQL query to execute
            params: Query parameters for parameterized queries
            limit: Maximum number of rows to return (None for no limit)

        Returns:
            Query result with rows and metadata

        Raises:
            ValueError: If query is not a safe read-only query
        """
        # Validate query is safe
        self._validate_query(query)

        # Add LIMIT if not present and limit is specified
        modified_query = query
        if limit is not None and not self._has_limit(query):
            modified_query = self._add_limit(query, limit)

        start_time = time.time()

        async with self.connection.get_connection() as conn:
            result = await conn.execute(text(modified_query), params or {})
            rows_data = result.fetchall()

            # Convert to list of dicts
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in rows_data]

            # Convert special types to JSON-serializable formats
            rows = convert_rows_to_json_safe(rows)

            execution_time = (time.time() - start_time) * 1000  # Convert to ms

            # Check if results were truncated
            truncated = limit is not None and len(rows) == limit

            return QueryResult(
                query=modified_query,
                rows=rows,
                row_count=len(rows),
                columns=columns,
                execution_time_ms=execution_time,
                truncated=truncated,
                warning="Results truncated to limit" if truncated else None,
            )

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

        return await self.execute_query(query, limit=limit)

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
            if len(rows) == 1 and isinstance(rows[0][0], str):
                # Single row - might be JSON or text
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
            )

    def _validate_query(self, query: str) -> None:
        """
        Validate that query is safe (read-only).

        Args:
            query: SQL query to validate

        Raises:
            ValueError: If query is not allowed
        """
        # Normalize query
        normalized = query.strip().upper()

        # Remove comments
        normalized = re.sub(r"--[^\n]*", "", normalized)
        normalized = re.sub(r"/\*.*?\*/", "", normalized, flags=re.DOTALL)

        # Get first keyword
        first_keyword = normalized.split()[0] if normalized.split() else ""

        if first_keyword not in self.ALLOWED_QUERY_TYPES:
            raise ValueError(
                f"Only {', '.join(self.ALLOWED_QUERY_TYPES)} queries are allowed. "
                f"Got: {first_keyword}"
            )

        # Check for dangerous keywords anywhere in query
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
