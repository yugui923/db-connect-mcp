"""Database profiling models."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class SchemaProfile(BaseModel):
    """Schema-level statistics."""

    name: str = Field(..., description="Schema name")
    table_count: int = Field(..., description="Number of tables in schema")
    view_count: Optional[int] = Field(None, description="Number of views in schema")
    total_size_bytes: Optional[int] = Field(
        None, description="Total size of all tables in bytes"
    )
    total_rows: Optional[int] = Field(None, description="Approximate total rows")


class TableProfile(BaseModel):
    """Table-level statistics for profiling."""

    schema: Optional[str] = Field(None, description="Schema name")
    name: str = Field(..., description="Table name")
    table_type: str = Field(..., description="Type (BASE TABLE, VIEW, etc.)")
    size_bytes: Optional[int] = Field(None, description="Table size in bytes")
    index_size_bytes: Optional[int] = Field(None, description="Index size in bytes")
    row_count: Optional[int] = Field(None, description="Approximate row count")


class DatabaseProfile(BaseModel):
    """Comprehensive database profiling information."""

    # Database Overview
    database_name: str = Field(..., description="Database name")
    version: str = Field(..., description="Database version")
    total_size_bytes: Optional[int] = Field(None, description="Total database size")
    total_schemas: int = Field(..., description="Number of schemas")
    total_tables: int = Field(..., description="Number of tables")
    total_views: Optional[int] = Field(None, description="Number of views")
    total_indexes: Optional[int] = Field(None, description="Number of indexes")

    # Schema breakdown
    schemas: list[SchemaProfile] = Field(
        default_factory=list, description="Schema-level statistics"
    )

    # Largest tables
    largest_tables: list[TableProfile] = Field(
        default_factory=list, description="Largest tables by size"
    )

    # Index health
    total_index_size_bytes: Optional[int] = Field(
        None, description="Total index size across all tables"
    )
    index_to_table_ratio: Optional[float] = Field(
        None, description="Ratio of index size to table size"
    )

    # Additional metadata
    extra_info: dict[str, Any] = Field(
        default_factory=dict, description="Database-specific additional information"
    )

    @property
    def total_size_mb(self) -> Optional[float]:
        """Total size in megabytes."""
        if self.total_size_bytes is None:
            return None
        return self.total_size_bytes / (1024 * 1024)

    @property
    def total_size_gb(self) -> Optional[float]:
        """Total size in gigabytes."""
        if self.total_size_bytes is None:
            return None
        return self.total_size_bytes / (1024 * 1024 * 1024)

    def get_schema_by_name(self, name: str) -> Optional[SchemaProfile]:
        """Get schema profile by name."""
        for schema in self.schemas:
            if schema.name == name:
                return schema
        return None
