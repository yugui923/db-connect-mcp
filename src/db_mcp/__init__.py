"""
db_mcp - Multi-database MCP server for Claude Code

A Model Context Protocol (MCP) server that provides database analysis and querying
capabilities for PostgreSQL, MySQL, and ClickHouse databases.
"""

__version__ = "2.0.0"

from db_mcp.models.config import DatabaseConfig
from db_mcp.models.capabilities import DatabaseCapabilities
from db_mcp.models.database import DatabaseInfo, SchemaInfo
from db_mcp.models.table import TableInfo, ColumnInfo, IndexInfo, ConstraintInfo
from db_mcp.models.query import QueryResult, ExplainPlan
from db_mcp.models.statistics import ColumnStats, Distribution

__all__ = [
    "DatabaseConfig",
    "DatabaseCapabilities",
    "DatabaseInfo",
    "SchemaInfo",
    "TableInfo",
    "ColumnInfo",
    "IndexInfo",
    "ConstraintInfo",
    "QueryResult",
    "ExplainPlan",
    "ColumnStats",
    "Distribution",
]
