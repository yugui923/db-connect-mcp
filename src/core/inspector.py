"""Metadata inspection using SQLAlchemy reflection."""

from typing import TYPE_CHECKING, Any, Optional, cast

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import reflection
from sqlalchemy.ext.asyncio import AsyncConnection

from src.core.connection import DatabaseConnection
from src.models.database import SchemaInfo
from src.models.table import (
    ColumnInfo,
    ConstraintInfo,
    IndexInfo,
    RelationshipInfo,
    TableInfo,
)

if TYPE_CHECKING:
    from src.adapters.base import BaseAdapter


class MetadataInspector:
    """Database metadata inspection using SQLAlchemy Inspector."""

    def __init__(self, connection: DatabaseConnection, adapter: "BaseAdapter"):
        """
        Initialize metadata inspector.

        Args:
            connection: Database connection manager
            adapter: Database-specific adapter for extended functionality
        """
        self.connection = connection
        self.adapter = adapter

    async def get_schemas(self) -> list[SchemaInfo]:
        """
        List all schemas in the database.

        Returns:
            List of schema information objects
        """
        async with await self.connection.get_connection() as conn:
            sync_bind = await self._get_sync_bind(conn)
            inspector_obj = sa_inspect(sync_bind)
            assert isinstance(inspector_obj, reflection.Inspector), (
                "Failed to create Inspector"
            )

            schemas = inspector_obj.get_schema_names()
            result = []

            for schema in schemas:
                # Skip system schemas based on dialect
                if self._is_system_schema(schema):
                    continue

                schema_info = SchemaInfo(
                    name=schema,
                    owner=None,  # Will be filled by adapter if available
                    table_count=len(inspector_obj.get_table_names(schema=schema)),
                    view_count=len(inspector_obj.get_view_names(schema=schema))
                    if self.adapter.capabilities.views
                    else None,
                )

                # Let adapter enrich with database-specific info
                schema_info = await self.adapter.enrich_schema_info(conn, schema_info)
                result.append(schema_info)

            return result

    async def get_tables(
        self, schema: Optional[str] = None, include_views: bool = True
    ) -> list[TableInfo]:
        """
        List tables in a schema.

        Args:
            schema: Schema name (None for default schema)
            include_views: Whether to include views

        Returns:
            List of basic table information
        """
        async with await self.connection.get_connection() as conn:
            sync_bind = await self._get_sync_bind(conn)
            inspector_obj = sa_inspect(sync_bind)
            assert isinstance(inspector_obj, reflection.Inspector), (
                "Failed to create Inspector"
            )

            # Get table names
            table_names = inspector_obj.get_table_names(schema=schema)
            tables = []

            for table_name in table_names:
                table_info = await self._get_basic_table_info(
                    conn, inspector_obj, table_name, schema, "BASE TABLE"
                )
                tables.append(table_info)

            # Get views if requested and supported
            if include_views and self.adapter.capabilities.views:
                view_names = inspector_obj.get_view_names(schema=schema)
                for view_name in view_names:
                    view_info = await self._get_basic_table_info(
                        conn, inspector_obj, view_name, schema, "VIEW"
                    )
                    tables.append(view_info)

            return tables

    async def describe_table(
        self, table_name: str, schema: Optional[str] = None
    ) -> TableInfo:
        """
        Get comprehensive table description.

        Args:
            table_name: Table name
            schema: Schema name (None for default)

        Returns:
            Comprehensive table information
        """
        async with await self.connection.get_connection() as conn:
            sync_bind = await self._get_sync_bind(conn)
            inspector_obj = sa_inspect(sync_bind)
            assert isinstance(inspector_obj, reflection.Inspector), (
                "Failed to create Inspector"
            )

            # Basic info
            table_info = TableInfo(
                name=table_name,
                schema=schema,
                table_type="BASE TABLE",  # Will be updated if it's a view
            )

            # Columns
            columns_data = inspector_obj.get_columns(table_name, schema=schema)
            table_info.columns = [
                self._column_from_sa(cast(dict[str, Any], col_data))
                for col_data in columns_data
            ]

            # Primary key
            pk_constraint = inspector_obj.get_pk_constraint(table_name, schema=schema)
            if pk_constraint and pk_constraint.get("constrained_columns"):
                pk_cols = pk_constraint["constrained_columns"]
                for col in table_info.columns:
                    if col.name in pk_cols:
                        col.primary_key = True

            # Indexes
            if self.adapter.capabilities.indexes:
                indexes_data = inspector_obj.get_indexes(table_name, schema=schema)
                table_info.indexes = [
                    self._index_from_sa(cast(dict[str, Any], idx_data))
                    for idx_data in indexes_data
                ]

                # Mark indexed columns
                for index in table_info.indexes:
                    for col_name in index.columns:
                        col = table_info.get_column(col_name)
                        if col:
                            col.indexed = True

            # Foreign keys
            if self.adapter.capabilities.foreign_keys:
                fk_data = inspector_obj.get_foreign_keys(table_name, schema=schema)
                for fk in fk_data:
                    constraint = self._fk_constraint_from_sa(cast(dict[str, Any], fk))
                    table_info.constraints.append(constraint)

                    # Mark FK columns
                    for col_name in constraint.columns:
                        col = table_info.get_column(col_name)
                        if col and constraint.referenced_table:
                            ref_cols = ",".join(constraint.referenced_columns or [])
                            col.foreign_key = (
                                f"{constraint.referenced_table}.{ref_cols}"
                            )

            # Unique constraints
            unique_data = inspector_obj.get_unique_constraints(
                table_name, schema=schema
            )
            for uniq in unique_data:
                constraint = ConstraintInfo(
                    name=uniq["name"],
                    constraint_type="UNIQUE",
                    columns=uniq["column_names"],
                )
                table_info.constraints.append(constraint)

                # Mark unique columns
                for col_name in constraint.columns:
                    col = table_info.get_column(col_name)
                    if col:
                        col.unique = True

            # Check constraints (if available)
            try:
                check_data = inspector_obj.get_check_constraints(
                    table_name, schema=schema
                )
                for check in check_data:
                    constraint = ConstraintInfo(
                        name=check["name"],
                        constraint_type="CHECK",
                        columns=[],  # Check constraints don't always map to specific columns
                        definition=check.get("sqltext"),
                    )
                    table_info.constraints.append(constraint)
            except NotImplementedError:
                # Some dialects don't support check constraints
                pass

            # Let adapter enrich with database-specific info
            table_info = await self.adapter.enrich_table_info(conn, table_info)

            return table_info

    async def get_relationships(
        self, table_name: str, schema: Optional[str] = None
    ) -> list[RelationshipInfo]:
        """
        Get foreign key relationships for a table.

        Args:
            table_name: Table name
            schema: Schema name

        Returns:
            List of relationship information
        """
        if not self.adapter.capabilities.foreign_keys:
            return []

        async with await self.connection.get_connection() as conn:
            sync_bind = await self._get_sync_bind(conn)
            inspector_obj = sa_inspect(sync_bind)
            assert isinstance(inspector_obj, reflection.Inspector), (
                "Failed to create Inspector"
            )

            fk_data = inspector_obj.get_foreign_keys(table_name, schema=schema)
            relationships = []

            for fk in fk_data:
                fk_dict = cast(dict[str, Any], fk)
                constraint_name = fk_dict.get("name") or f"fk_{table_name}_auto"
                rel = RelationshipInfo(
                    from_table=table_name,
                    from_schema=schema,
                    from_columns=fk_dict["constrained_columns"],
                    to_table=fk_dict["referred_table"],
                    to_schema=fk_dict.get("referred_schema"),
                    to_columns=fk_dict["referred_columns"],
                    constraint_name=constraint_name,
                    on_delete=fk_dict.get("options", {}).get("ondelete"),
                    on_update=fk_dict.get("options", {}).get("onupdate"),
                )
                relationships.append(rel)

            return relationships

    async def _get_basic_table_info(
        self,
        conn: AsyncConnection,
        inspector: reflection.Inspector,
        table_name: str,
        schema: Optional[str],
        table_type: str,
    ) -> TableInfo:
        """Get basic table info without full details."""
        table_info = TableInfo(
            name=table_name,
            schema=schema,
            table_type=table_type,
        )

        # Let adapter provide size and row count efficiently
        table_info = await self.adapter.enrich_table_info(conn, table_info)

        return table_info

    def _column_from_sa(self, col_data: dict) -> ColumnInfo:
        """Convert SQLAlchemy column data to ColumnInfo."""
        return ColumnInfo(
            name=col_data["name"],
            data_type=str(col_data["type"]),
            nullable=col_data["nullable"],
            default=str(col_data["default"]) if col_data.get("default") else None,
            primary_key=False,  # Will be set later
            foreign_key=None,  # Will be set later
            unique=False,  # Will be set later
            indexed=False,  # Will be set later
            comment=col_data.get("comment"),
        )

    def _index_from_sa(self, idx_data: dict) -> IndexInfo:
        """Convert SQLAlchemy index data to IndexInfo."""
        return IndexInfo(
            name=idx_data["name"],
            columns=idx_data["column_names"],
            unique=idx_data.get("unique", False),
            index_type=idx_data.get("type"),
        )

    def _fk_constraint_from_sa(self, fk_data: dict) -> ConstraintInfo:
        """Convert SQLAlchemy FK data to ConstraintInfo."""
        return ConstraintInfo(
            name=fk_data["name"],
            constraint_type="FOREIGN KEY",
            columns=fk_data["constrained_columns"],
            referenced_table=fk_data["referred_table"],
            referenced_columns=fk_data["referred_columns"],
        )

    def _is_system_schema(self, schema: str) -> bool:
        """Check if schema is a system schema to skip."""
        system_schemas = {
            "postgresql": {"information_schema", "pg_catalog", "pg_toast"},
            "mysql": {"information_schema", "mysql", "performance_schema", "sys"},
            "clickhouse": {"information_schema", "INFORMATION_SCHEMA", "system"},
        }

        dialect = self.connection.dialect
        return schema in system_schemas.get(dialect, set())

    async def _get_sync_bind(self, conn: AsyncConnection):
        """Get synchronous bind for Inspector (SQLAlchemy reflection is sync-only)."""
        # SQLAlchemy Inspector requires sync engine
        # We use the connection's sync_connection for inspection
        return conn.sync_connection
