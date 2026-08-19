"""Core database operations layer."""

from .analyzer import StatisticsAnalyzer
from .connection import DatabaseConnection
from .executor import QueryExecutor
from .inspector import MetadataInspector
from .resources import DatabaseResourceCatalog, paginate_resources
from .search import ObjectSearcher, like_to_regex
from .tunnel import (
    KeyFormat,
    SSHTunnelError,
    SSHTunnelErrorCode,
    SSHTunnelManager,
    rewrite_database_url,
)

__all__ = [
    "DatabaseConnection",
    "DatabaseResourceCatalog",
    "KeyFormat",
    "MetadataInspector",
    "ObjectSearcher",
    "QueryExecutor",
    "StatisticsAnalyzer",
    "SSHTunnelManager",
    "SSHTunnelError",
    "SSHTunnelErrorCode",
    "like_to_regex",
    "paginate_resources",
    "rewrite_database_url",
]
