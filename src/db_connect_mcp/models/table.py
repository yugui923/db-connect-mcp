"""Table, column, index, and constraint information models."""

import warnings
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# Suppress the specific warning about field 'schema' shadowing
warnings.filterwarnings(
    "ignore",
    message='Field name "schema" in "TableInfo" shadows an attribute in parent',
    category=UserWarning,
)


class ColumnInfo(BaseModel):
    """Information about a table column."""

    name: str = Field(..., description="Column name")
    data_type: str = Field(..., description="Column data type")
    nullable: bool = Field(..., description="Whether column allows NULL")
    default: Optional[str] = Field(None, description="Default value expression")
    primary_key: bool = Field(
        default=False, description="Whether column is part of primary key"
    )
    foreign_key: Optional[str] = Field(
        None, description="Foreign key reference (table.column)"
    )
    unique: bool = Field(
        default=False, description="Whether column has UNIQUE constraint"
    )
    indexed: bool = Field(default=False, description="Whether column is indexed")
    comment: Optional[str] = Field(None, description="Column comment/description")
    max_length: Optional[int] = Field(
        None, description="Maximum length for string types"
    )
    numeric_precision: Optional[int] = Field(
        None, description="Precision for numeric types"
    )
    numeric_scale: Optional[int] = Field(None, description="Scale for numeric types")
    extra_info: dict[str, Any] = Field(
        default_factory=dict,
        description="Database-specific additional information",
    )


class IndexInfo(BaseModel):
    """Information about a table index."""

    name: str = Field(..., description="Index name")
    columns: list[str] = Field(..., description="Indexed column names")
    unique: bool = Field(default=False, description="Whether index enforces uniqueness")
    primary: bool = Field(
        default=False, description="Whether this is the primary key index"
    )
    index_type: Optional[str] = Field(
        None, description="Index type (btree, hash, etc.)"
    )
    size_bytes: Optional[int] = Field(None, description="Index size in bytes")
    comment: Optional[str] = Field(None, description="Index comment")
    extra_info: dict[str, Any] = Field(
        default_factory=dict,
        description="Database-specific additional information",
    )

    @property
    def size_human(self) -> Optional[str]:
        """Human-readable size."""
        if self.size_bytes is None:
            return None

        size = float(self.size_bytes)
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"


class ConstraintInfo(BaseModel):
    """Information about a table constraint."""

    name: str = Field(..., description="Constraint name")
    constraint_type: str = Field(
        ..., description="Constraint type (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK)"
    )
    columns: list[str] = Field(..., description="Constrained column names")
    referenced_table: Optional[str] = Field(None, description="Referenced table for FK")
    referenced_columns: Optional[list[str]] = Field(
        None, description="Referenced columns for FK"
    )
    definition: Optional[str] = Field(None, description="Constraint definition SQL")
    deferrable: Optional[bool] = Field(
        None, description="Whether constraint is deferrable"
    )
    initially_deferred: Optional[bool] = Field(
        None, description="Whether initially deferred"
    )
    extra_info: dict[str, Any] = Field(
        default_factory=dict,
        description="Database-specific additional information",
    )


class RelationshipInfo(BaseModel):
    """Information about a foreign key relationship between tables."""

    from_table: str = Field(..., description="Source table name")
    from_schema: Optional[str] = Field(None, description="Source schema name")
    from_columns: list[str] = Field(..., description="Source column names")
    to_table: str = Field(..., description="Target table name")
    to_schema: Optional[str] = Field(None, description="Target schema name")
    to_columns: list[str] = Field(..., description="Target column names")
    constraint_name: str = Field(..., description="Foreign key constraint name")
    on_delete: Optional[str] = Field(None, description="ON DELETE action")
    on_update: Optional[str] = Field(None, description="ON UPDATE action")


class TableInfo(BaseModel):
    """Comprehensive information about a table."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(..., description="Table name")
    schema: Optional[str] = Field(default=None, description="Schema name")
    table_type: str = Field(
        default="BASE TABLE", description="Type (BASE TABLE, VIEW, etc.)"
    )
    row_count: Optional[int] = Field(None, description="Approximate row count")
    size_bytes: Optional[int] = Field(None, description="Table size in bytes")
    index_size_bytes: Optional[int] = Field(
        None, description="Total index size in bytes"
    )
    columns: list[ColumnInfo] = Field(
        default_factory=list, description="Column information"
    )
    indexes: list[IndexInfo] = Field(
        default_factory=list, description="Index information"
    )
    constraints: list[ConstraintInfo] = Field(
        default_factory=list, description="Constraint information"
    )
    comment: Optional[str] = Field(None, description="Table comment/description")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")
    owner: Optional[str] = Field(None, description="Table owner")
    extra_info: dict[str, Any] = Field(
        default_factory=dict,
        description="Database-specific additional information (engine, partitions, etc.)",
    )

    @property
    def size_human(self) -> Optional[str]:
        """Human-readable table size."""
        if self.size_bytes is None:
            return None

        size = float(self.size_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

    @property
    def total_size_bytes(self) -> Optional[int]:
        """Total size including indexes."""
        if self.size_bytes is None:
            return None
        return self.size_bytes + (self.index_size_bytes or 0)

    @property
    def total_size_human(self) -> Optional[str]:
        """Human-readable total size."""
        total = self.total_size_bytes
        if total is None:
            return None

        size = float(total)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

    @property
    def primary_key_columns(self) -> list[str]:
        """Get primary key column names."""
        return [col.name for col in self.columns if col.primary_key]

    @property
    def foreign_key_columns(self) -> list[str]:
        """Get foreign key column names."""
        return [col.name for col in self.columns if col.foreign_key is not None]

    @property
    def column_count(self) -> int:
        """Get number of columns."""
        return len(self.columns)

    @property
    def index_count(self) -> int:
        """Get number of indexes."""
        return len(self.indexes)

    @property
    def constraint_count(self) -> int:
        """Get number of constraints."""
        return len(self.constraints)

    def get_column(self, name: str) -> Optional[ColumnInfo]:
        """Get column by name."""
        for col in self.columns:
            if col.name == name:
                return col
        return None

    def get_index(self, name: str) -> Optional[IndexInfo]:
        """Get index by name."""
        for idx in self.indexes:
            if idx.name == name:
                return idx
        return None

    def get_constraint(self, name: str) -> Optional[ConstraintInfo]:
        """Get constraint by name."""
        for constraint in self.constraints:
            if constraint.name == name:
                return constraint
        return None
