"""
db_mcp - Multi-database MCP server for Claude Code

A Model Context Protocol (MCP) server that provides database analysis and querying
capabilities for PostgreSQL, MySQL, and ClickHouse databases.
"""

__version__ = "2.0.0"

from .models.config import DatabaseConfig
from .models.capabilities import DatabaseCapabilities
from .models.database import DatabaseInfo, SchemaInfo
from .models.table import TableInfo, ColumnInfo, IndexInfo, ConstraintInfo
from .models.query import QueryResult, ExplainPlan
from .models.statistics import ColumnStats, Distribution

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
