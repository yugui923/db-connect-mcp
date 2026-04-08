"""Models for the search_objects tool.

These models support cross-cutting metadata search across schemas, tables,
views, columns, and indexes with progressive disclosure (3 detail levels)
to control token usage in MCP responses.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SearchObjectType(str, Enum):
    """Database object types that can be searched."""

    SCHEMA = "schema"
    TABLE = "table"
    VIEW = "view"
    COLUMN = "column"
    INDEX = "index"


# Default object_types when caller does not specify any.
DEFAULT_SEARCH_OBJECT_TYPES: list[SearchObjectType] = [
    SearchObjectType.SCHEMA,
    SearchObjectType.TABLE,
    SearchObjectType.VIEW,
    SearchObjectType.COLUMN,
    SearchObjectType.INDEX,
]


class SearchDetailLevel(str, Enum):
    """Detail level controlling response verbosity / token cost.

    - ``names``: object_type + name + parent identifiers only.
    - ``summary``: + key metadata (data types, row counts, uniqueness, ...).
    - ``full``: + comments, defaults, max_length, numeric precision/scale.
    """

    NAMES = "names"
    SUMMARY = "summary"
    FULL = "full"


class SearchResultItem(BaseModel):
    """A single matched database object.

    Fields populated depend on ``object_type`` and ``SearchDetailLevel``.
    All non-applicable fields are ``None`` and should be excluded from JSON
    output (use ``model_dump(exclude_none=True)``).
    """

    model_config = ConfigDict(use_enum_values=True)

    # Always-present identification
    object_type: str = Field(
        ...,
        description="Type of object (schema, table, view, column, index)",
    )
    name: str = Field(..., description="Object name")
    schema: Optional[str] = Field(
        default=None, description="Schema containing the object (when applicable)"
    )
    table: Optional[str] = Field(
        default=None,
        description="Table containing the object (for column / index results)",
    )

    # ---- Summary level fields ----
    # Tables / views
    table_type: Optional[str] = Field(
        default=None, description="Table type (BASE TABLE, VIEW, ...)"
    )
    row_count: Optional[int] = Field(
        default=None, description="Approximate row count (tables only)"
    )
    column_count: Optional[int] = Field(
        default=None, description="Number of columns (tables/views only)"
    )

    # Schemas
    table_count_in_schema: Optional[int] = Field(
        default=None, description="Number of tables in schema (schema results only)"
    )
    view_count_in_schema: Optional[int] = Field(
        default=None, description="Number of views in schema (schema results only)"
    )

    # Columns
    data_type: Optional[str] = Field(
        default=None, description="Column data type (column results only)"
    )
    nullable: Optional[bool] = Field(
        default=None, description="Whether column allows NULL"
    )
    primary_key: Optional[bool] = Field(
        default=None, description="Whether column is part of the primary key"
    )
    unique: Optional[bool] = Field(
        default=None,
        description="Whether column has UNIQUE constraint or index is unique",
    )
    indexed: Optional[bool] = Field(
        default=None, description="Whether column is indexed"
    )
    foreign_key: Optional[str] = Field(
        default=None, description="Foreign key reference (table.column)"
    )

    # Indexes
    columns: Optional[list[str]] = Field(
        default=None, description="Indexed column names (index results only)"
    )
    index_type: Optional[str] = Field(default=None, description="Index type")

    # ---- Full level fields ----
    comment: Optional[str] = Field(default=None, description="Object comment")
    default: Optional[str] = Field(
        default=None, description="Column default value (column results only)"
    )
    max_length: Optional[int] = Field(
        default=None, description="Max length for string types"
    )
    numeric_precision: Optional[int] = Field(
        default=None, description="Numeric precision"
    )
    numeric_scale: Optional[int] = Field(default=None, description="Numeric scale")


class SearchResults(BaseModel):
    """Envelope returned by the search_objects tool."""

    pattern: str = Field(..., description="The LIKE pattern that was searched")
    detail_level: str = Field(..., description="Detail level used")
    object_types: list[str] = Field(..., description="Object types that were searched")
    results: list[SearchResultItem] = Field(
        default_factory=list, description="Matched objects (after applying limit)"
    )
    total_found: int = Field(
        ..., description="Total matches discovered before applying limit"
    )
    returned: int = Field(..., description="Number of items in ``results``")
    limit: int = Field(..., description="Limit that was applied")
    truncated: bool = Field(
        ..., description="True if total_found > limit (results were truncated)"
    )
    early_termination: bool = Field(
        default=False,
        description=(
            "True if the search stopped before exhausting the database "
            "(e.g. hit the per-call table-describe cap)."
        ),
    )
    note: Optional[str] = Field(
        default=None,
        description="Optional human-readable hint about the search outcome",
    )
