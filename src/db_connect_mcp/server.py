"""Multi-database MCP Server

A Model Context Protocol (MCP) server providing database analysis and querying
capabilities for PostgreSQL, MySQL, and ClickHouse databases.
"""

import argparse
import asyncio
import json
import logging
import os
from typing import Any, Optional, cast

from dotenv import load_dotenv
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ContentBlock,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolAnnotations,
)
from pydantic import BaseModel

from db_connect_mcp import __version__
from db_connect_mcp.adapters import create_adapter
from db_connect_mcp.core import (
    DatabaseConnection,
    MetadataInspector,
    ObjectSearcher,
    QueryExecutor,
    StatisticsAnalyzer,
)
from db_connect_mcp.models.config import DatabaseConfig, SSHTunnelConfig
from db_connect_mcp.models.database import DatabaseInfo, SchemaInfo
from db_connect_mcp.models.query import ExplainPlan, QueryResult
from db_connect_mcp.models.search import (
    SearchDetailLevel,
    SearchObjectType,
    SearchResults,
)
from db_connect_mcp.models.statistics import ColumnStats
from db_connect_mcp.models.table import RelationshipInfo, TableInfo

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Response size limits (in characters) for MCP tool responses
# These limits prevent context window exhaustion while preserving useful information
# Set high enough to avoid truncation in most cases - can be adjusted based on needs
MAX_RESPONSE_DATABASE_INFO = 50000  # Basic database metadata
MAX_RESPONSE_LIST_SCHEMAS = 100000  # Schema listings
MAX_RESPONSE_GET_RELATIONSHIPS = 100000  # Foreign key relationships
MAX_RESPONSE_SAMPLE_DATA = 100000  # Table data preview
MAX_RESPONSE_LIST_TABLES = 100000  # Table listings with metadata
MAX_RESPONSE_ANALYZE_COLUMN = 50000  # Column statistics
MAX_RESPONSE_DESCRIBE_TABLE = 100000  # Detailed table structure
MAX_RESPONSE_EXPLAIN_QUERY = 100000  # Query execution plans
MAX_RESPONSE_EXECUTE_QUERY = 100000  # Query results (up to 1000 rows)
MAX_RESPONSE_SEARCH_OBJECTS = 100000  # Cross-cutting object search results

LIST_RESULT_TOOLS = {
    "get_table_relationships",
    "list_schemas",
    "list_tables",
}

READ_ONLY_TOOL_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def _truncation_info_schema() -> dict[str, Any]:
    """Return the shared schema for optional response truncation metadata."""
    return {
        "type": "object",
        "properties": {
            "truncated": {"type": "boolean"},
            "truncated_fields": {
                "type": "array",
                "items": {"type": "string"},
            },
            "message": {"type": "string"},
        },
        "required": ["truncated", "truncated_fields", "message"],
        "additionalProperties": False,
    }


def _model_output_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Build an object-rooted output schema with truncation metadata support."""
    schema = model.model_json_schema()
    properties = cast(dict[str, Any], schema.setdefault("properties", {}))
    properties["_truncation_info"] = _truncation_info_schema()
    return schema


def _list_output_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Build a legacy-compatible object envelope for a list of models."""
    item_schema = model.model_json_schema()
    definitions = item_schema.pop("$defs", None)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": item_schema},
            "_truncation_info": _truncation_info_schema(),
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    if definitions is not None:
        schema["$defs"] = definitions
    return schema


def _read_only_tool(
    *,
    name: str,
    title: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
) -> Tool:
    """Create a fully described read-only database tool."""
    return Tool(
        name=name,
        title=title,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema,
        annotations=READ_ONLY_TOOL_ANNOTATIONS,
    )


def _tool_error(code: str, message: str) -> CallToolResult:
    """Return a model-visible tool error in text and structured forms."""
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        structured_content={"error": {"code": code, "message": message}},
        is_error=True,
    )


def _structured_tool_result(
    tool_name: str, content: list[TextContent]
) -> tuple[dict[str, Any], bool]:
    """Convert the legacy JSON text payload into an MCP structured result."""
    if len(content) != 1:
        raise ValueError(f"{tool_name} returned an unexpected content shape")

    parsed = json.loads(content[0].text)
    is_error = isinstance(parsed, dict) and "error" in parsed

    if tool_name in LIST_RESULT_TOOLS:
        if isinstance(parsed, list):
            return {"items": parsed}, is_error
        if isinstance(parsed, dict) and isinstance(parsed.get("data"), list):
            result = {"items": parsed["data"]}
            if "_truncation_info" in parsed:
                result["_truncation_info"] = parsed["_truncation_info"]
            return result, is_error

    if isinstance(parsed, dict) and isinstance(parsed.get("data"), dict):
        result = dict(parsed["data"])
        if "_truncation_info" in parsed:
            result["_truncation_info"] = parsed["_truncation_info"]
        return result, is_error
    if isinstance(parsed, dict):
        return parsed, is_error

    raise ValueError(f"{tool_name} returned a non-object result")


def truncate_json_response(data: str, max_length: int) -> str:
    """
    Return JSON response with size limit check.

    Args:
        data: JSON string to return
        max_length: Maximum length in characters

    Returns:
        JSON string (original or error message if too large)
    """
    if len(data) <= max_length:
        return data

    # If response is too large, return an error message instead
    # This ensures we always return valid JSON
    return json.dumps(
        {
            "error": "Response too large",
            "original_size": len(data),
            "limit": max_length,
            "message": "Response exceeds size limit. Please use more specific filters or query parameters to reduce data size.",
        },
        indent=2,
    )


def _truncate_string(value: str | None, max_length: int) -> tuple[str | None, bool]:
    """
    Truncate a string to max_length, adding ellipsis if truncated.

    Returns:
        Tuple of (truncated_value, was_truncated)
    """
    if value is None:
        return None, False
    if len(value) <= max_length:
        return value, False
    if max_length <= 3:
        truncated = "..."[:max_length] if max_length > 0 else None
        return truncated, True
    return value[: max_length - 3] + "...", True


def _truncate_comment(comment: str | None, max_length: int) -> str | None:
    """Truncate a comment to max_length, adding ellipsis if truncated."""
    result, _ = _truncate_string(comment, max_length)
    return result


def _truncate_list(items: list[Any], max_items: int) -> tuple[list[Any], bool]:
    """
    Truncate a list to max_items.

    Returns:
        Tuple of (truncated_list, was_truncated)
    """
    if len(items) <= max_items:
        return items, False
    return items[:max_items], True


# Constants for truncation limits
MAX_STRING_VALUE_LENGTH = 500  # Max length for individual string values in data
MAX_COMMON_VALUES = 20  # Max number of most_common_values entries
MAX_PLAN_LENGTH = 10000  # Max length for explain plan text
MAX_SCHEMA_COMMENT_LENGTH = 1000  # Max length for schema comments
MAX_TABLE_COMMENT_LENGTH = 500  # Max length for table comments in list_tables


def apply_truncation_to_list_schemas(
    schemas_data: list[dict[str, Any]], max_response_size: int
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Apply truncation to list_schemas response.

    Returns:
        Tuple of (truncated_data, list_of_truncated_field_names)
    """
    truncated_fields: list[str] = []

    for i, schema in enumerate(schemas_data):
        if schema.get("comment"):
            truncated, was_truncated = _truncate_string(
                schema["comment"], MAX_SCHEMA_COMMENT_LENGTH
            )
            if was_truncated:
                schema["comment"] = truncated
                field_name = f"schemas[{i}].comment"
                if field_name not in truncated_fields:
                    truncated_fields.append(field_name)

    return schemas_data, truncated_fields


def apply_truncation_to_list_tables(
    tables_data: list[dict[str, Any]], max_response_size: int
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Apply truncation to list_tables response.

    Returns:
        Tuple of (truncated_data, list_of_truncated_field_names)
    """
    truncated_fields: list[str] = []

    for i, table in enumerate(tables_data):
        if table.get("comment"):
            truncated, was_truncated = _truncate_string(
                table["comment"], MAX_TABLE_COMMENT_LENGTH
            )
            if was_truncated:
                table["comment"] = truncated
                truncated_fields.append(f"tables[{i}].comment")

    return tables_data, truncated_fields


def apply_truncation_to_sample_data(
    result_data: dict[str, Any], max_response_size: int
) -> tuple[dict[str, Any], list[str]]:
    """
    Apply truncation to sample_data response.

    Truncates long string values in rows to prevent one cell from dominating.

    Returns:
        Tuple of (truncated_data, list_of_truncated_field_names)
    """
    truncated_fields: list[str] = []
    rows = result_data.get("rows", [])

    for row_idx, row in enumerate(rows):
        for col_name, value in row.items():
            if isinstance(value, str) and len(value) > MAX_STRING_VALUE_LENGTH:
                truncated, _ = _truncate_string(value, MAX_STRING_VALUE_LENGTH)
                row[col_name] = truncated
                field_id = f"rows[].{col_name}"
                if field_id not in truncated_fields:
                    truncated_fields.append(field_id)

    return result_data, truncated_fields


def apply_truncation_to_analyze_column(
    stats_data: dict[str, Any], max_response_size: int
) -> tuple[dict[str, Any], list[str]]:
    """
    Apply truncation to analyze_column response.

    Truncates most_common_values list and individual value strings.

    Returns:
        Tuple of (truncated_data, list_of_truncated_field_names)
    """
    truncated_fields: list[str] = []

    # Truncate most_common_values list
    most_common = stats_data.get("most_common_values", [])
    if most_common:
        truncated_list, was_truncated = _truncate_list(most_common, MAX_COMMON_VALUES)
        if was_truncated:
            stats_data["most_common_values"] = truncated_list
            truncated_fields.append("most_common_values")

        # Truncate long string values within most_common_values
        for item in stats_data.get("most_common_values", []):
            if "value" in item and isinstance(item["value"], str):
                truncated, was_truncated = _truncate_string(
                    item["value"], MAX_STRING_VALUE_LENGTH
                )
                if was_truncated:
                    item["value"] = truncated
                    if "most_common_values[].value" not in truncated_fields:
                        truncated_fields.append("most_common_values[].value")

    # Also truncate min/max if they're long strings
    for field in ["min_value", "max_value", "median_value"]:
        if field in stats_data and isinstance(stats_data[field], str):
            truncated, was_truncated = _truncate_string(
                stats_data[field], MAX_STRING_VALUE_LENGTH
            )
            if was_truncated:
                stats_data[field] = truncated
                truncated_fields.append(field)

    return stats_data, truncated_fields


def apply_truncation_to_explain_query(
    plan_data: dict[str, Any], max_response_size: int
) -> tuple[dict[str, Any], list[str]]:
    """
    Apply truncation to explain_query response.

    Truncates long plan text while preserving essential information.

    Returns:
        Tuple of (truncated_data, list_of_truncated_field_names)
    """
    truncated_fields: list[str] = []

    # Truncate plan text if very long
    if plan_data.get("plan"):
        truncated, was_truncated = _truncate_string(plan_data["plan"], MAX_PLAN_LENGTH)
        if was_truncated:
            plan_data["plan"] = truncated
            truncated_fields.append("plan")

    # If plan_json is huge, remove it and keep only text plan
    if plan_data.get("plan_json"):
        plan_json_str = json.dumps(plan_data["plan_json"])
        if len(plan_json_str) > MAX_PLAN_LENGTH:
            plan_data["plan_json"] = None
            plan_data["plan_json_note"] = "JSON plan too large, see 'plan' text instead"
            truncated_fields.append("plan_json")

    return plan_data, truncated_fields


def wrap_response_with_truncation_info(
    data: dict[str, Any] | list[dict[str, Any]], truncated_fields: list[str]
) -> dict[str, Any]:
    """
    Wrap response data with truncation metadata.

    If any fields were truncated, adds _truncation_info to the response.

    Args:
        data: Original response data (dict or list)
        truncated_fields: List of field names that were truncated

    Returns:
        Response wrapped with truncation metadata if needed
    """
    if not truncated_fields:
        # No truncation occurred, return as-is
        if isinstance(data, list):
            return {"data": data}
        return data

    return {
        "data": data if isinstance(data, list) else data,
        "_truncation_info": {
            "truncated": True,
            "truncated_fields": truncated_fields,
            "message": "Some fields were truncated to fit response size limits. "
            "Use more specific queries or tools for full content.",
        },
    }


def wrap_list_response_with_truncation_info(
    data: list[dict[str, Any]], truncated_fields: list[str]
) -> list[dict[str, Any]] | dict[str, Any]:
    """
    Wrap list response with truncation info if needed.

    For list responses, we only wrap if truncation occurred.
    """
    if not truncated_fields:
        return data
    return wrap_response_with_truncation_info(data, truncated_fields)


def apply_dynamic_comment_limits(
    table_data: dict[str, Any], max_response_size: int
) -> tuple[dict[str, Any], list[str]]:
    """
    Apply dynamic comment length limits based on table size and response budget.

    This function distributes the available character budget for comments
    proportionally among the table comment and column comments, ensuring no
    single comment monopolizes the response size.

    Strategy:
    1. Calculate base response size without comments
    2. Reserve budget for comments (remaining space with safety margin)
    3. Allocate 10% of comment budget to table comment
    4. Distribute remaining 90% equally among column comments
    5. Truncate any comments exceeding their allocation

    Args:
        table_data: Dictionary from TableInfo.model_dump()
        max_response_size: Maximum allowed response size in characters

    Returns:
        Tuple of (modified_table_data, list_of_truncated_fields)
    """
    truncated_fields: list[str] = []

    # First, calculate the base size without any comments
    table_copy = table_data.copy()
    original_table_comment = table_copy.get("comment")
    table_copy["comment"] = None

    columns = table_copy.get("columns", [])
    original_column_comments: dict[int, str | None] = {}
    for i, col in enumerate(columns):
        original_column_comments[i] = col.get("comment")
        col["comment"] = None

    # Calculate base size (table structure without comments)
    base_json = json.dumps(table_copy, indent=2)
    base_size = len(base_json)

    # Calculate available budget for comments
    # Leave 10% safety margin for JSON formatting overhead
    safety_margin = int(max_response_size * 0.1)
    available_for_comments = max(0, max_response_size - base_size - safety_margin)

    # Count how many comments we have
    num_columns = len(columns)
    has_table_comment = original_table_comment is not None

    if available_for_comments <= 0 or (num_columns == 0 and not has_table_comment):
        # No budget for comments, return with all comments removed
        if has_table_comment:
            truncated_fields.append("comment")
        if any(c is not None for c in original_column_comments.values()):
            truncated_fields.append("columns[].comment")
        return table_copy, truncated_fields

    # Allocate budget:
    # - Table comment gets 10% of budget (max 2000 chars)
    # - Column comments share the remaining 90%
    table_comment_budget = 0
    column_comment_budget_each = 0

    if has_table_comment and num_columns > 0:
        # Both table and column comments
        table_comment_budget = min(int(available_for_comments * 0.1), 2000)
        remaining = available_for_comments - table_comment_budget
        column_comment_budget_each = remaining // num_columns
    elif has_table_comment:
        # Only table comment
        table_comment_budget = min(available_for_comments, 5000)
    elif num_columns > 0:
        # Only column comments
        column_comment_budget_each = available_for_comments // num_columns

    # Apply truncation to table comment
    if original_table_comment is not None:
        truncated, was_truncated = _truncate_string(
            original_table_comment, table_comment_budget
        )
        table_copy["comment"] = truncated
        if was_truncated:
            truncated_fields.append("comment")

    # Apply truncation to column comments
    column_was_truncated = False
    for i, col in enumerate(columns):
        original_comment = original_column_comments.get(i)
        if original_comment is not None:
            truncated, was_truncated = _truncate_string(
                original_comment, column_comment_budget_each
            )
            col["comment"] = truncated
            if was_truncated:
                column_was_truncated = True

    if column_was_truncated:
        truncated_fields.append("columns[].comment")

    return table_copy, truncated_fields


class DatabaseMCPServer:
    """MCP server for multi-database operations."""

    def __init__(self, config: DatabaseConfig):
        """
        Initialize database MCP server.

        Args:
            config: Database configuration
        """
        self.config = config
        self.connection = DatabaseConnection(config)
        self.adapter = create_adapter(config)
        self.inspector: Optional[MetadataInspector] = None
        self.executor: Optional[QueryExecutor] = None
        self.analyzer: Optional[StatisticsAnalyzer] = None
        self.searcher: Optional[ObjectSearcher] = None
        self.server = Server(
            "db-connect-mcp",
            version=__version__,
            title="DB Connect MCP",
            description=(
                "Read-only database exploration and analysis for PostgreSQL, "
                "MySQL, and ClickHouse"
            ),
            instructions=(
                "Use search_objects for token-efficient discovery, then inspect "
                "specific tables or run bounded read-only queries. Tool results "
                "include structured content and equivalent JSON text."
            ),
            website_url="https://github.com/yugui923/db-connect-mcp",
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )

    async def initialize(self) -> None:
        """Initialize all components."""
        await self.connection.initialize()

        self.inspector = MetadataInspector(self.connection, self.adapter)
        self.executor = QueryExecutor(self.connection, self.adapter)
        self.analyzer = StatisticsAnalyzer(self.connection, self.adapter)
        self.searcher = ObjectSearcher(self.inspector)

        # Register MCP tool handlers
        await self._register_tools()

        logger.info(
            f"Initialized {self.config.dialect} MCP server "
            f"({len(self.adapter.capabilities.get_supported_features())} features)"
        )

    async def _register_tools(self) -> None:
        """Register MCP tools based on database capabilities."""
        # Low-level MCP v2 handlers are bound in the Server constructor.
        # This hook remains for tool-related initialization work.
        pass

    async def _list_tools(
        self,
        _ctx: ServerRequestContext[Any],
        _params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        """List tools supported by the configured database."""
        return ListToolsResult(tools=self._available_tools())

    def _available_tools(self) -> list[Tool]:
        """Build the tool surface supported by the configured database."""
        tools = [
            self._create_get_database_info_tool(),
            self._create_list_schemas_tool(),
            self._create_list_tables_tool(),
            self._create_describe_table_tool(),
            self._create_execute_query_tool(),
            self._create_sample_data_tool(),
            self._create_search_objects_tool(),
        ]

        if self.adapter.capabilities.foreign_keys:
            tools.append(self._create_get_relationships_tool())

        if self.adapter.capabilities.advanced_stats:
            tools.append(self._create_analyze_column_tool())

        if self.adapter.capabilities.explain_plans:
            tools.append(self._create_explain_query_tool())

        return tools

    async def _call_tool(
        self,
        _ctx: ServerRequestContext[Any],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        """Dispatch a tool call while preserving model-visible error results."""
        handlers = {
            "get_database_info": self.handle_get_database_info,
            "list_schemas": self.handle_list_schemas,
            "list_tables": self.handle_list_tables,
            "describe_table": self.handle_describe_table,
            "execute_query": self.handle_execute_query,
            "sample_data": self.handle_sample_data,
            "search_objects": self.handle_search_objects,
        }
        if self.adapter.capabilities.foreign_keys:
            handlers["get_table_relationships"] = self.handle_get_relationships
        if self.adapter.capabilities.advanced_stats:
            handlers["analyze_column"] = self.handle_analyze_column
        if self.adapter.capabilities.explain_plans:
            handlers["explain_query"] = self.handle_explain_query

        handler = handlers.get(params.name)
        available_tool = next(
            (tool for tool in self._available_tools() if tool.name == params.name),
            None,
        )
        if handler is None or available_tool is None:
            return _tool_error(
                "tool_unavailable", f"Unknown or unavailable tool: {params.name}"
            )

        arguments = params.arguments or {}
        try:
            Draft202012Validator(available_tool.input_schema).validate(arguments)
        except ValidationError as exc:
            return _tool_error(
                "invalid_arguments",
                f"Invalid arguments for {params.name}: {exc.message}",
            )

        try:
            content = await handler(arguments)
            structured_content, is_error = _structured_tool_result(params.name, content)
        except Exception as exc:
            logger.warning("Tool %s failed: %s", params.name, exc)
            return _tool_error("tool_execution_error", str(exc))

        return CallToolResult(
            content=cast(list[ContentBlock], content),
            structured_content=structured_content,
            is_error=is_error,
        )

    def _create_get_database_info_tool(self) -> Tool:
        """Create get_database_info tool."""
        return _read_only_tool(
            name="get_database_info",
            title="Get Database Information",
            description=(
                "Get the configured database's version, dialect, read-only state, "
                "sanitized connection URL, and supported capabilities."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            output_schema=_model_output_schema(DatabaseInfo),
        )

    def _create_list_schemas_tool(self) -> Tool:
        """Create list_schemas tool."""
        return _read_only_tool(
            name="list_schemas",
            title="List Schemas",
            description="List schemas or databases visible to the configured user.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            output_schema=_list_output_schema(SchemaInfo),
        )

    def _create_list_tables_tool(self) -> Tool:
        """Create list_tables tool."""
        return _read_only_tool(
            name="list_tables",
            title="List Tables",
            description="List tables and optionally views in a database schema.",
            input_schema={
                "type": "object",
                "properties": {
                    "schema": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Schema name (optional, uses default if not specified)",
                    },
                    "include_views": {
                        "type": "boolean",
                        "description": "Whether to include views (default: true)",
                        "default": True,
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema=_list_output_schema(TableInfo),
        )

    def _create_describe_table_tool(self) -> Tool:
        """Create describe_table tool."""
        return _read_only_tool(
            name="describe_table",
            title="Describe Table",
            description=(
                "Get a table's columns, indexes, constraints, comments, and size "
                "metadata."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Table name",
                    },
                    "schema": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Schema name (optional)",
                    },
                },
                "required": ["table"],
                "additionalProperties": False,
            },
            output_schema=_model_output_schema(TableInfo),
        )

    def _create_execute_query_tool(self) -> Tool:
        """Create execute_query tool."""
        return _read_only_tool(
            name="execute_query",
            title="Execute Read-Only Query",
            description=(
                "Execute a bounded read-only SELECT, WITH, or EXPLAIN query and "
                "return rows with execution metadata."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "description": "SQL query to execute",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of rows to return (default: 1000)",
                        "default": 1000,
                        "minimum": 1,
                        "maximum": 10000,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema=_model_output_schema(QueryResult),
        )

    def _create_sample_data_tool(self) -> Tool:
        """Create sample_data tool."""
        return _read_only_tool(
            name="sample_data",
            title="Sample Table Data",
            description="Return a bounded preview of rows from a table.",
            input_schema={
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Table name",
                    },
                    "schema": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Schema name (optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of rows to sample (default: 100)",
                        "default": 100,
                        "minimum": 1,
                        "maximum": 1000,
                    },
                },
                "required": ["table"],
                "additionalProperties": False,
            },
            output_schema=_model_output_schema(QueryResult),
        )

    def _create_get_relationships_tool(self) -> Tool:
        """Create get_table_relationships tool."""
        return _read_only_tool(
            name="get_table_relationships",
            title="Get Table Relationships",
            description="List the foreign-key relationships for a table.",
            input_schema={
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Table name",
                    },
                    "schema": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Schema name (optional)",
                    },
                },
                "required": ["table"],
                "additionalProperties": False,
            },
            output_schema=_list_output_schema(RelationshipInfo),
        )

    def _create_analyze_column_tool(self) -> Tool:
        """Create analyze_column tool."""
        return _read_only_tool(
            name="analyze_column",
            title="Analyze Column",
            description=(
                "Calculate column statistics including nulls, distinct values, "
                "percentiles, and common values."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Table name",
                    },
                    "column": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Column name",
                    },
                    "schema": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Schema name (optional)",
                    },
                },
                "required": ["table", "column"],
                "additionalProperties": False,
            },
            output_schema=_model_output_schema(ColumnStats),
        )

    def _create_explain_query_tool(self) -> Tool:
        """Create explain_query tool."""
        return _read_only_tool(
            name="explain_query",
            title="Explain Query",
            description=(
                "Inspect a query execution plan. Setting analyze=true executes "
                "the read-only query to collect runtime statistics."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "description": "SQL query to explain",
                    },
                    "analyze": {
                        "type": "boolean",
                        "description": "Whether to execute the query (EXPLAIN ANALYZE)",
                        "default": False,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema=_model_output_schema(ExplainPlan),
        )

    def _create_search_objects_tool(self) -> Tool:
        """Create search_objects tool.

        Token-efficient cross-cutting search across schemas, tables, views,
        columns, and indexes. Inspired by bytebase/dbhub's search_objects.
        Three detail levels (``names`` / ``summary`` / ``full``) let the
        caller trade verbosity for tokens.
        """
        return _read_only_tool(
            name="search_objects",
            title="Search Database Objects",
            description=(
                "Search and explore database objects (schemas, tables, views, "
                "columns, indexes) with progressive disclosure for token "
                "efficiency. Use SQL LIKE pattern (% matches any sequence, "
                "_ matches one character) to match names. Three detail levels: "
                "'names' (most token-efficient), 'summary' (default, key "
                "metadata), 'full' (includes comments and full type info). "
                "For column/index search, narrow with `schema` (and optionally "
                "`table`) to avoid the per-call table cap."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "SQL LIKE pattern to match object names. Use '%' "
                            "to match all, '%user%' for substring, '_d' for "
                            "single-char wildcard."
                        ),
                    },
                    "object_types": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "enum": [
                                "schema",
                                "table",
                                "view",
                                "column",
                                "index",
                            ],
                        },
                        "description": (
                            "Types of objects to search. Defaults to all 5 "
                            "types. Restricting types is faster."
                        ),
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["names", "summary", "full"],
                        "default": "summary",
                        "description": (
                            "Response verbosity. 'names' returns just "
                            "identifiers (cheapest), 'summary' adds key "
                            "metadata, 'full' includes comments and type "
                            "details."
                        ),
                    },
                    "schema": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Restrict search to a specific schema. Strongly "
                            "recommended when searching columns or indexes."
                        ),
                    },
                    "table": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Restrict column/index search to a specific table. "
                            "Without `schema`, matches a table of that name in "
                            "any schema."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "default": 100,
                        "minimum": 1,
                        "maximum": 1000,
                        "description": (
                            "Max items to return (1-1000). Total match count "
                            "is reported separately in 'total_found'."
                        ),
                    },
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            output_schema=_model_output_schema(SearchResults),
        )

    # Tool handlers
    async def handle_get_database_info(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle get_database_info request."""
        if self.inspector is None:
            raise RuntimeError("Server not initialized")

        version = await self.connection.get_version()

        # Sanitize connection URL (remove password)
        url_parts = self.config.url.split("@")
        if len(url_parts) > 1:
            sanitized_url = f"<credentials>@{url_parts[-1]}"
        else:
            sanitized_url = self.config.url

        db_info = DatabaseInfo(
            name=self.config.url.split("/")[-1],  # Extract DB name from URL
            dialect=self.config.dialect,
            version=version,
            size_bytes=None,
            schema_count=None,
            table_count=None,
            capabilities=self.adapter.capabilities,
            server_encoding=None,
            collation=None,
            connection_url=sanitized_url,
            read_only=self.config.read_only,
        )

        response = json.dumps(db_info.model_dump(mode="json"), indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_DATABASE_INFO),
            )
        ]

    async def handle_list_schemas(self, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle list_schemas request."""
        if self.inspector is None:
            raise RuntimeError("Server not initialized")

        schemas = await self.inspector.get_schemas()
        schemas_data = [s.model_dump(mode="json") for s in schemas]

        # Apply truncation to schema comments
        schemas_data, truncated_fields = apply_truncation_to_list_schemas(
            schemas_data, MAX_RESPONSE_LIST_SCHEMAS
        )

        # Wrap with truncation info if any fields were truncated
        result = wrap_list_response_with_truncation_info(schemas_data, truncated_fields)

        response = json.dumps(result, indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_LIST_SCHEMAS),
            )
        ]

    async def handle_list_tables(self, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle list_tables request."""
        if self.inspector is None:
            raise RuntimeError("Server not initialized")

        schema = arguments.get("schema")
        include_views = arguments.get("include_views", True)

        tables = await self.inspector.get_tables(schema, include_views)
        tables_data = [t.model_dump(mode="json") for t in tables]

        # Apply truncation to table comments
        tables_data, truncated_fields = apply_truncation_to_list_tables(
            tables_data, MAX_RESPONSE_LIST_TABLES
        )

        # Wrap with truncation info if any fields were truncated
        result = wrap_list_response_with_truncation_info(tables_data, truncated_fields)

        response = json.dumps(result, indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_LIST_TABLES),
            )
        ]

    async def handle_describe_table(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle describe_table request."""
        if self.inspector is None:
            raise RuntimeError("Server not initialized")

        table = arguments["table"]
        schema = arguments.get("schema")

        table_info = await self.inspector.describe_table(table, schema)

        # Apply dynamic comment truncation based on table size and response limit
        table_data = table_info.model_dump(mode="json")
        table_data, truncated_fields = apply_dynamic_comment_limits(
            table_data, MAX_RESPONSE_DESCRIBE_TABLE
        )

        # Wrap with truncation info if any fields were truncated
        result = wrap_response_with_truncation_info(table_data, truncated_fields)

        response = json.dumps(result, indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_DESCRIBE_TABLE),
            )
        ]

    async def handle_execute_query(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle execute_query request."""
        if self.executor is None:
            raise RuntimeError("Server not initialized")

        query = arguments["query"]
        limit = arguments.get("limit", 1000)

        result = await self.executor.execute_query(query, limit=limit)

        response = json.dumps(result.model_dump(mode="json"), indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_EXECUTE_QUERY),
            )
        ]

    async def handle_sample_data(self, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle sample_data request."""
        if self.executor is None:
            raise RuntimeError("Server not initialized")

        table = arguments["table"]
        schema = arguments.get("schema")
        limit = arguments.get("limit", 100)

        result = await self.executor.sample_data(table, schema, limit)
        result_data = result.model_dump(mode="json")

        # Apply truncation to long string values in rows
        result_data, truncated_fields = apply_truncation_to_sample_data(
            result_data, MAX_RESPONSE_SAMPLE_DATA
        )

        # Wrap with truncation info if any fields were truncated
        final_result = wrap_response_with_truncation_info(result_data, truncated_fields)

        response = json.dumps(final_result, indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_SAMPLE_DATA),
            )
        ]

    async def handle_get_relationships(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle get_table_relationships request."""
        if self.inspector is None:
            raise RuntimeError("Server not initialized")

        table = arguments["table"]
        schema = arguments.get("schema")

        relationships = await self.inspector.get_relationships(table, schema)
        relationships_data = [r.model_dump(mode="json") for r in relationships]

        response = json.dumps(relationships_data, indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_GET_RELATIONSHIPS),
            )
        ]

    async def handle_analyze_column(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle analyze_column request."""
        if self.analyzer is None:
            raise RuntimeError("Server not initialized")

        table = arguments["table"]
        column = arguments["column"]
        schema = arguments.get("schema")

        stats = await self.analyzer.analyze_column(table, column, schema)
        stats_data = stats.model_dump(mode="json")

        # Apply truncation to most_common_values and long string values
        stats_data, truncated_fields = apply_truncation_to_analyze_column(
            stats_data, MAX_RESPONSE_ANALYZE_COLUMN
        )

        # Wrap with truncation info if any fields were truncated
        result = wrap_response_with_truncation_info(stats_data, truncated_fields)

        response = json.dumps(result, indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_ANALYZE_COLUMN),
            )
        ]

    async def handle_explain_query(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle explain_query request."""
        if self.executor is None:
            raise RuntimeError("Server not initialized")

        query = arguments["query"]
        analyze = arguments.get("analyze", False)

        plan = await self.executor.explain_query(query, analyze)
        plan_data = plan.model_dump(mode="json")

        # Apply truncation to long plan text
        plan_data, truncated_fields = apply_truncation_to_explain_query(
            plan_data, MAX_RESPONSE_EXPLAIN_QUERY
        )

        # Wrap with truncation info if any fields were truncated
        result = wrap_response_with_truncation_info(plan_data, truncated_fields)

        response = json.dumps(result, indent=2)
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_EXPLAIN_QUERY),
            )
        ]

    async def handle_search_objects(
        self, arguments: dict[str, Any]
    ) -> list[TextContent]:
        """Handle search_objects request.

        Validates and coerces incoming arguments into the typed enums used by
        :class:`ObjectSearcher`, then dumps the result with ``exclude_none``
        so the response stays as token-efficient as the chosen detail level
        allows.
        """
        if self.searcher is None:
            raise RuntimeError("Server not initialized")

        pattern = arguments.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("`pattern` is required and must be a non-empty string")

        # Detail level
        detail_raw = arguments.get("detail_level", "summary")
        try:
            detail_level = SearchDetailLevel(detail_raw)
        except ValueError:
            valid = ", ".join(d.value for d in SearchDetailLevel)
            raise ValueError(
                f"Invalid detail_level: {detail_raw!r}. Must be one of: {valid}"
            )

        # Object types
        object_types_raw = arguments.get("object_types")
        object_types: Optional[list[SearchObjectType]] = None
        if object_types_raw is not None:
            if not isinstance(object_types_raw, list):
                raise ValueError("`object_types` must be a list of strings")
            parsed: list[SearchObjectType] = []
            for ot in object_types_raw:
                try:
                    parsed.append(SearchObjectType(ot))
                except ValueError:
                    valid = ", ".join(t.value for t in SearchObjectType)
                    raise ValueError(
                        f"Invalid object_type: {ot!r}. Must be one of: {valid}"
                    )
            object_types = parsed

        schema = arguments.get("schema")
        table = arguments.get("table")
        limit = int(arguments.get("limit", 100))

        results = await self.searcher.search(
            pattern=pattern,
            object_types=object_types,
            detail_level=detail_level,
            schema=schema,
            table=table,
            limit=limit,
        )

        # exclude_none keeps the JSON minimal — fields that don't apply to the
        # chosen detail level or object type are dropped entirely.
        response = json.dumps(
            results.model_dump(mode="json", exclude_none=True), indent=2
        )
        return [
            TextContent(
                type="text",
                text=truncate_json_response(response, MAX_RESPONSE_SEARCH_OBJECTS),
            )
        ]

    async def cleanup(self) -> None:
        """Cleanup resources."""
        await self.connection.dispose()
        logger.info("Database MCP server cleaned up")


def _parse_int_env(
    name: str, value: Optional[str], default: Optional[int] = None
) -> Optional[int]:
    """Parse an environment variable as an integer with clear error messages."""
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(
            f"Environment variable {name} must be an integer, got: {value!r}"
        )


def _parse_bool_env(name: str, value: Optional[str], default: bool) -> bool:
    """Parse a strict boolean environment variable with a clear error."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"Environment variable {name} must be a boolean "
        f"(true/false, yes/no, on/off, or 1/0), got: {value!r}"
    )


def _load_ssh_tunnel_config() -> Optional[SSHTunnelConfig]:
    """
    Load SSH tunnel configuration from environment variables.

    Returns:
        SSHTunnelConfig if SSH_HOST is set, None otherwise
    """
    ssh_host = os.getenv("SSH_HOST")

    if not ssh_host:
        return None  # SSH tunnel not configured

    ssh_username = os.getenv("SSH_USERNAME")
    if not ssh_username:
        raise ValueError("SSH_USERNAME must be set when SSH_HOST is configured")

    # Get optional SSH config values
    ssh_password = os.getenv("SSH_PASSWORD")
    ssh_private_key = os.getenv("SSH_PRIVATE_KEY")
    ssh_private_key_path = os.getenv("SSH_PRIVATE_KEY_PATH")
    ssh_private_key_passphrase = os.getenv("SSH_PRIVATE_KEY_PASSPHRASE")
    remote_host = os.getenv("SSH_REMOTE_HOST")
    local_host = os.getenv("SSH_LOCAL_HOST", "127.0.0.1")

    ssh_port = _parse_int_env("SSH_PORT", os.getenv("SSH_PORT"), default=22) or 22
    remote_port = _parse_int_env("SSH_REMOTE_PORT", os.getenv("SSH_REMOTE_PORT"))
    local_port = _parse_int_env("SSH_LOCAL_PORT", os.getenv("SSH_LOCAL_PORT"))
    tunnel_timeout = (
        _parse_int_env(
            "SSH_TUNNEL_TIMEOUT", os.getenv("SSH_TUNNEL_TIMEOUT"), default=10
        )
        or 10
    )
    connect_timeout = _parse_int_env(
        "SSH_CONNECT_TIMEOUT",
        os.getenv("SSH_CONNECT_TIMEOUT"),
        default=tunnel_timeout,
    )
    banner_timeout = _parse_int_env(
        "SSH_BANNER_TIMEOUT",
        os.getenv("SSH_BANNER_TIMEOUT"),
        default=tunnel_timeout,
    )
    auth_timeout = _parse_int_env(
        "SSH_AUTH_TIMEOUT",
        os.getenv("SSH_AUTH_TIMEOUT"),
        default=tunnel_timeout,
    )
    channel_timeout = _parse_int_env(
        "SSH_CHANNEL_TIMEOUT",
        os.getenv("SSH_CHANNEL_TIMEOUT"),
        default=tunnel_timeout,
    )
    keepalive_interval = (
        _parse_int_env(
            "SSH_KEEPALIVE_INTERVAL",
            os.getenv("SSH_KEEPALIVE_INTERVAL"),
            default=30,
        )
        or 0
    )
    target_preflight = _parse_bool_env(
        "SSH_TARGET_PREFLIGHT",
        os.getenv("SSH_TARGET_PREFLIGHT"),
        default=True,
    )
    strict_host_key = _parse_bool_env(
        "SSH_STRICT_HOST_KEY",
        os.getenv("SSH_STRICT_HOST_KEY"),
        default=False,
    )
    known_hosts_path = os.getenv("SSH_KNOWN_HOSTS_PATH")

    return SSHTunnelConfig(
        ssh_host=ssh_host,
        ssh_port=ssh_port,
        ssh_username=ssh_username,
        ssh_password=ssh_password,
        ssh_private_key=ssh_private_key,
        ssh_private_key_path=ssh_private_key_path,
        ssh_private_key_passphrase=ssh_private_key_passphrase,
        remote_host=remote_host,
        remote_port=remote_port,
        local_host=local_host,
        local_port=local_port,
        tunnel_timeout=tunnel_timeout,
        connect_timeout=connect_timeout,
        banner_timeout=banner_timeout,
        auth_timeout=auth_timeout,
        channel_timeout=channel_timeout,
        keepalive_interval=keepalive_interval,
        target_preflight=target_preflight,
        known_hosts_path=known_hosts_path,
        strict_host_key=strict_host_key,
    )


class _MCPASGIApp:
    """ASGI application wrapper for MCP server with optional auth."""

    def __init__(
        self,
        session_manager: Any,
        auth_token: str | None = None,
    ) -> None:
        self.session_manager = session_manager
        self.auth_token = auth_token

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        from starlette.responses import Response

        if self.auth_token and scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth_value = headers.get(b"authorization", b"").decode()
            if (
                not auth_value.startswith("Bearer ")
                or auth_value[7:] != self.auth_token
            ):
                response = Response("Unauthorized", status_code=401)
                await response(scope, receive, send)
                return
        await self.session_manager.handle_request(scope, receive, send)


class _OAuthMCPASGIApp:
    """ASGI application wrapper for MCP server with OAuth 2.0 JWT verification."""

    def __init__(
        self,
        session_manager: Any,
        token_verifier: Any,
        required_scopes: list[str] | None = None,
    ) -> None:
        self.session_manager = session_manager
        self.token_verifier = token_verifier
        self.required_scopes = required_scopes or []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        from starlette.responses import JSONResponse

        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth_value = headers.get(b"authorization", b"").decode()

            # Check for Bearer token
            if not auth_value.startswith("Bearer "):
                response = JSONResponse(
                    {
                        "error": "unauthorized",
                        "error_description": "Missing bearer token",
                    },
                    status_code=401,
                    headers={"WWW-Authenticate": 'Bearer realm="mcp"'},
                )
                await response(scope, receive, send)
                return

            token = auth_value[7:]

            # Verify the token
            access_token = await self.token_verifier.verify_token(token)
            if access_token is None:
                response = JSONResponse(
                    {
                        "error": "invalid_token",
                        "error_description": "Token validation failed",
                    },
                    status_code=401,
                    headers={
                        "WWW-Authenticate": 'Bearer realm="mcp", error="invalid_token"'
                    },
                )
                await response(scope, receive, send)
                return

            # Check required scopes
            if self.required_scopes:
                missing_scopes = [
                    s for s in self.required_scopes if s not in access_token.scopes
                ]
                if missing_scopes:
                    response = JSONResponse(
                        {
                            "error": "insufficient_scope",
                            "error_description": f"Missing required scopes: {', '.join(missing_scopes)}",
                        },
                        status_code=403,
                        headers={
                            "WWW-Authenticate": f'Bearer realm="mcp", error="insufficient_scope", scope="{" ".join(self.required_scopes)}"'
                        },
                    )
                    await response(scope, receive, send)
                    return

            # Store token info in scope for downstream use
            scope["auth"] = access_token

        await self.session_manager.handle_request(scope, receive, send)


async def _run_streamable_http(
    mcp_server: DatabaseMCPServer,
    host: str,
    port: int,
    oauth_issuer: str | None = None,
    oauth_audience: str | None = None,
    oauth_scopes: list[str] | None = None,
) -> None:
    """Run the MCP server using Streamable HTTP transport.

    Supports three authentication modes:
    1. No auth: If neither MCP_AUTH_TOKEN nor oauth_issuer is set
    2. Simple bearer token: If MCP_AUTH_TOKEN env var is set
    3. OAuth 2.0 JWT: If oauth_issuer and oauth_audience are provided
    """
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server.server,
        json_response=True,
        stateless=True,
    )

    # Determine authentication mode
    auth_token = os.getenv("MCP_AUTH_TOKEN")
    mcp_asgi_app: _MCPASGIApp | _OAuthMCPASGIApp

    if oauth_issuer and oauth_audience:
        # OAuth 2.0 JWT verification mode
        from db_connect_mcp.auth import JWTTokenVerifier, JWTVerifierConfig

        config = JWTVerifierConfig(
            issuer=oauth_issuer,
            audience=oauth_audience,
            required_scopes=oauth_scopes,
        )
        token_verifier = JWTTokenVerifier(config)
        mcp_asgi_app = _OAuthMCPASGIApp(
            session_manager,
            token_verifier,
            required_scopes=oauth_scopes,
        )
        logger.info(f"OAuth 2.0 JWT verification enabled (issuer: {oauth_issuer})")
        if oauth_scopes:
            logger.info(f"Required scopes: {', '.join(oauth_scopes)}")
    else:
        # Simple bearer token or no auth mode
        mcp_asgi_app = _MCPASGIApp(session_manager, auth_token)
        if auth_token:
            logger.info("Bearer token authentication enabled (MCP_AUTH_TOKEN)")

    app = Starlette(
        routes=[Route("/mcp", endpoint=mcp_asgi_app)],
        lifespan=lambda app: session_manager.run(),
    )

    uvicorn_config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(uvicorn_config)

    logger.info(f"Starting Streamable HTTP server on {host}:{port}/mcp")

    await server.serve()


async def main(
    transport: str = "stdio",
    host: str = "0.0.0.0",
    port: int = 8000,
    oauth_issuer: str | None = None,
    oauth_audience: str | None = None,
    oauth_scopes: list[str] | None = None,
) -> None:
    """Main entry point for the MCP server."""
    # Get database URL from environment
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable must be set")

    # Load SSH tunnel config if present
    ssh_tunnel_config = _load_ssh_tunnel_config()

    # Log tunnel status
    if ssh_tunnel_config:
        logger.info(
            f"SSH tunnel configured: {ssh_tunnel_config.ssh_host}:{ssh_tunnel_config.ssh_port}"
        )

    # Parse statement timeout from environment
    statement_timeout = _parse_int_env(
        "DB_STATEMENT_TIMEOUT", os.getenv("DB_STATEMENT_TIMEOUT"), default=900
    )

    # Create configuration
    config = DatabaseConfig(
        url=database_url,
        ssh_tunnel=ssh_tunnel_config,
        statement_timeout=statement_timeout,
    )

    # Create and initialize server
    mcp_server = DatabaseMCPServer(config)

    try:
        await mcp_server.initialize()

        # Run the server
        if transport == "streamable-http":
            await _run_streamable_http(
                mcp_server,
                host,
                port,
                oauth_issuer=oauth_issuer,
                oauth_audience=oauth_audience,
                oauth_scopes=oauth_scopes,
            )
        else:
            from mcp.server.stdio import stdio_server

            async with stdio_server() as (read_stream, write_stream):
                await mcp_server.server.run(
                    read_stream,
                    write_stream,
                    mcp_server.server.create_initialization_options(),
                )

    finally:
        await mcp_server.cleanup()


def cli_entry() -> None:
    """
    Synchronous entry point for console script.

    This function is called by the 'db-connect-mcp' console script.
    It sets up the event loop and runs the async main() function.
    """
    parser = argparse.ArgumentParser(
        description="Multi-database MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Authentication modes (for streamable-http transport):
  1. No auth: Default when no auth options are set
  2. Simple bearer token: Set MCP_AUTH_TOKEN environment variable
  3. OAuth 2.0 JWT: Use --oauth-issuer and --oauth-audience

OAuth 2.0 examples:
  Auth0:
    --oauth-issuer https://your-tenant.auth0.com/ \\
    --oauth-audience https://your-api-identifier

  Azure AD:
    --oauth-issuer https://login.microsoftonline.com/{tenant}/v2.0 \\
    --oauth-audience your-client-id

  Okta:
    --oauth-issuer https://your-domain.okta.com/oauth2/default \\
    --oauth-audience api://default
""",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to for streamable-http (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for streamable-http (default: 8000)",
    )

    # OAuth 2.0 arguments
    oauth_group = parser.add_argument_group("OAuth 2.0 authentication")
    oauth_group.add_argument(
        "--oauth-issuer",
        default=os.getenv("MCP_OAUTH_ISSUER"),
        help="OAuth issuer URL (e.g., https://your-tenant.auth0.com/). "
        "Can also be set via MCP_OAUTH_ISSUER env var.",
    )
    oauth_group.add_argument(
        "--oauth-audience",
        default=os.getenv("MCP_OAUTH_AUDIENCE"),
        help="Expected audience claim (your API identifier). "
        "Can also be set via MCP_OAUTH_AUDIENCE env var.",
    )
    oauth_group.add_argument(
        "--oauth-scopes",
        default=os.getenv("MCP_OAUTH_SCOPES"),
        help="Required scopes (comma-separated). "
        "Can also be set via MCP_OAUTH_SCOPES env var.",
    )

    args = parser.parse_args()

    # Validate OAuth arguments
    if (args.oauth_issuer and not args.oauth_audience) or (
        args.oauth_audience and not args.oauth_issuer
    ):
        parser.error("--oauth-issuer and --oauth-audience must be used together")

    # Parse scopes
    oauth_scopes: list[str] | None = None
    if args.oauth_scopes:
        oauth_scopes = [s.strip() for s in args.oauth_scopes.split(",") if s.strip()]

    # Windows-specific event loop policy
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]

    try:
        asyncio.run(
            main(
                transport=args.transport,
                host=args.host,
                port=args.port,
                oauth_issuer=args.oauth_issuer,
                oauth_audience=args.oauth_audience,
                oauth_scopes=oauth_scopes,
            )
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    cli_entry()
