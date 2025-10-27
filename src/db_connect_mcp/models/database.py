"""Database and schema information models."""

from typing import Optional

from pydantic import BaseModel, Field

from db_connect_mcp.models.capabilities import DatabaseCapabilities


class SchemaInfo(BaseModel):
    """Information about a database schema/namespace."""

    name: str = Field(..., description="Schema name")
    owner: Optional[str] = Field(None, description="Schema owner")
    table_count: Optional[int] = Field(None, description="Number of tables in schema")
    view_count: Optional[int] = Field(None, description="Number of views in schema")
    size_bytes: Optional[int] = Field(None, description="Schema size in bytes")
    comment: Optional[str] = Field(None, description="Schema comment/description")

    @property
    def size_human(self) -> Optional[str]:
        """Human-readable size."""
        if self.size_bytes is None:
            return None

        size = float(self.size_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"


class DatabaseInfo(BaseModel):
    """Information about the database instance."""

    name: str = Field(..., description="Database name")
    dialect: str = Field(
        ..., description="Database dialect (postgresql, mysql, clickhouse)"
    )
    version: str = Field(..., description="Database version string")
    size_bytes: Optional[int] = Field(None, description="Total database size in bytes")
    schema_count: Optional[int] = Field(None, description="Number of schemas")
    table_count: Optional[int] = Field(None, description="Total number of tables")
    capabilities: DatabaseCapabilities = Field(..., description="Database capabilities")
    server_encoding: Optional[str] = Field(
        None, description="Server character encoding"
    )
    collation: Optional[str] = Field(None, description="Default collation")
    connection_url: str = Field(..., description="Sanitized connection URL")
    read_only: bool = Field(
        default=True, description="Whether connections are read-only"
    )
    extra_info: dict[str, str | int | float | bool] = Field(
        default_factory=dict,
        description="Database-specific additional information",
    )

    @property
    def size_human(self) -> Optional[str]:
        """Human-readable size."""
        if self.size_bytes is None:
            return None

        size = float(self.size_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

    def get_feature_summary(self) -> str:
        """Get a summary of supported features."""
        supported = self.capabilities.get_supported_features()
        return f"{len(supported)} features supported: {', '.join(supported[:5])}" + (
            "..." if len(supported) > 5 else ""
        )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "mydb",
                    "dialect": "postgresql",
                    "version": "PostgreSQL 15.3",
                    "size_bytes": 1073741824,
                    "schema_count": 3,
                    "table_count": 42,
                    "capabilities": {
                        "foreign_keys": True,
                        "indexes": True,
                        "views": True,
                        "materialized_views": True,
                        "partitions": True,
                        "advanced_stats": True,
                        "explain_plans": True,
                        "profiling": True,
                        "comments": True,
                        "schemas": True,
                        "transactions": True,
                        "stored_procedures": True,
                        "triggers": True,
                    },
                    "server_encoding": "UTF8",
                    "collation": "en_US.UTF-8",
                    "connection_url": "postgresql+asyncpg://localhost:5432/mydb",
                    "read_only": True,
                    "extra_info": {},
                }
            ]
        }
    }
