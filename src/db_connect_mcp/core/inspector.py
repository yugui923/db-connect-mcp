"""Metadata inspection using SQLAlchemy reflection."""

from typing import TYPE_CHECKING, Any, Optional, cast

from sqlalchemy import inspect as sa_inspect

from db_connect_mcp.core.connection import DatabaseConnection
from db_connect_mcp.models.database import SchemaInfo
from db_connect_mcp.models.table import (
    ColumnInfo,
    ConstraintInfo,
    IndexInfo,
    RelationshipInfo,
    TableInfo,
)

if TYPE_CHECKING:
    from db_connect_mcp.adapters.base import BaseAdapter


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
        async with self.connection.get_connection() as conn:
            # Use run_sync to execute synchronous reflection methods
            def get_schema_data(sync_conn):
                inspector = sa_inspect(sync_conn)
                all_schemas = inspector.get_schema_names()

                schema_data = []
                for schema in all_schemas:
                    if self._is_system_schema(schema):
                        continue

                    table_count = len(inspector.get_table_names(schema=schema))
                    view_count = None
                    if self.adapter.capabilities.views:
                        view_count = len(inspector.get_view_names(schema=schema))

                    schema_data.append(
                        {
                            "name": schema,
                            "table_count": table_count,
                            "view_count": view_count,
                        }
                    )
                return schema_data

            schemas_data = await conn.run_sync(get_schema_data)
            result = []

            for data in schemas_data:
                schema_info = SchemaInfo(
                    name=data["name"],
                    owner=None,  # Will be filled by adapter if available
                    table_count=data["table_count"],
                    view_count=data["view_count"],
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
        async with self.connection.get_connection() as conn:
            # Use run_sync to execute synchronous reflection methods
            def get_table_data(sync_conn):
                inspector = sa_inspect(sync_conn)

                # Get table names
                table_names = inspector.get_table_names(schema=schema)
                table_data = []

                for table_name in table_names:
                    table_data.append({"name": table_name, "type": "BASE TABLE"})

                # Get views if requested and supported
                if include_views and self.adapter.capabilities.views:
                    view_names = inspector.get_view_names(schema=schema)
                    for view_name in view_names:
                        table_data.append({"name": view_name, "type": "VIEW"})

                return table_data

            tables_data = await conn.run_sync(get_table_data)
            tables = []

            for data in tables_data:
                table_info = TableInfo(
                    name=data["name"],
                    schema=schema,
                    table_type=data["type"],
                )
                # Let adapter provide size and row count efficiently
                table_info = await self.adapter.enrich_table_info(conn, table_info)
                tables.append(table_info)

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
        async with self.connection.get_connection() as conn:
            # Use run_sync to execute all synchronous reflection methods
            def get_table_details(sync_conn):
                inspector = sa_inspect(sync_conn)

                # Gather all table metadata
                result = {
                    "columns": inspector.get_columns(table_name, schema=schema),
                    "pk_constraint": inspector.get_pk_constraint(
                        table_name, schema=schema
                    ),
                    "indexes": [],
                    "foreign_keys": [],
                    "unique_constraints": inspector.get_unique_constraints(
                        table_name, schema=schema
                    ),
                    "check_constraints": [],
                }

                # Get indexes if supported
                if self.adapter.capabilities.indexes:
                    result["indexes"] = inspector.get_indexes(table_name, schema=schema)

                # Get foreign keys if supported
                if self.adapter.capabilities.foreign_keys:
                    result["foreign_keys"] = inspector.get_foreign_keys(
                        table_name, schema=schema
                    )

                # Try to get check constraints
                try:
                    result["check_constraints"] = inspector.get_check_constraints(
                        table_name, schema=schema
                    )
                except NotImplementedError:
                    pass

                return result

            table_data = await conn.run_sync(get_table_details)

            # Basic info
            table_info = TableInfo(
                name=table_name,
                schema=schema,
                table_type="BASE TABLE",  # Will be updated if it's a view
            )

            # Columns
            table_info.columns = [
                self._column_from_sa(cast(dict[str, Any], col_data))
                for col_data in table_data["columns"]
            ]

            # Primary key
            pk_constraint = table_data["pk_constraint"]
            if pk_constraint and pk_constraint.get("constrained_columns"):
                pk_cols = pk_constraint["constrained_columns"]
                for col in table_info.columns:
                    if col.name in pk_cols:
                        col.primary_key = True

            # Indexes
            for idx_data in table_data["indexes"]:
                index = self._index_from_sa(cast(dict[str, Any], idx_data))
                table_info.indexes.append(index)

                # Mark indexed columns
                for col_name in index.columns:
                    col = table_info.get_column(col_name)
                    if col:
                        col.indexed = True

            # Foreign keys
            for fk in table_data["foreign_keys"]:
                constraint = self._fk_constraint_from_sa(cast(dict[str, Any], fk))
                table_info.constraints.append(constraint)

                # Mark FK columns
                for col_name in constraint.columns:
                    col = table_info.get_column(col_name)
                    if col and constraint.referenced_table:
                        ref_cols = ",".join(constraint.referenced_columns or [])
                        col.foreign_key = f"{constraint.referenced_table}.{ref_cols}"

            # Unique constraints
            for uniq in table_data["unique_constraints"]:
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

            # Check constraints
            for check in table_data["check_constraints"]:
                constraint = ConstraintInfo(
                    name=check["name"],
                    constraint_type="CHECK",
                    columns=[],  # Check constraints don't always map to specific columns
                    definition=check.get("sqltext"),
                )
                table_info.constraints.append(constraint)

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

        async with self.connection.get_connection() as conn:
            # Use run_sync to execute synchronous reflection methods
            def get_fk_data(sync_conn):
                inspector = sa_inspect(sync_conn)
                return inspector.get_foreign_keys(table_name, schema=schema)

            fk_data = await conn.run_sync(get_fk_data)
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
