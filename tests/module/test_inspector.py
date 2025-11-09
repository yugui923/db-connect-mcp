"""Module Tests for MetadataInspector

Tests the MetadataInspector component directly without MCP protocol overhead.
Validates:
- Schema listing and metadata
- Table listing with enriched metadata
- Table description with columns, indexes, constraints
- Table relationships (foreign keys)
"""

import pytest

from db_connect_mcp.adapters.base import BaseAdapter
from db_connect_mcp.core import DatabaseConnection, MetadataInspector

pytestmark = [pytest.mark.postgresql, pytest.mark.integration]


class TestMetadataInspectorSchemas:
    """Test schema listing functionality."""

    @pytest.mark.asyncio
    async def test_list_schemas(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test list_schemas returns schema information with metadata."""
        inspector = MetadataInspector(pg_connection, pg_adapter)

        schemas = await inspector.get_schemas()

        # Validate schemas returned
        assert len(schemas) > 0

        for schema in schemas:
            # Validate schema structure
            assert schema.name is not None
            assert len(schema.name) > 0

            # Validate table count is populated
            assert schema.table_count is not None
            assert schema.table_count >= 0

            # Size might be available
            if schema.size_bytes is not None:
                assert isinstance(schema.size_bytes, int)
                assert schema.size_bytes >= 0


class TestMetadataInspectorTables:
    """Test table listing and description functionality."""

    @pytest.mark.asyncio
    async def test_list_tables_with_metadata(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test list_tables returns tables with complete metadata."""
        inspector = MetadataInspector(pg_connection, pg_adapter)

        # Get tables from public schema
        tables = await inspector.get_tables("public", include_views=True)

        # Should have at least some tables
        assert len(tables) > 0

        # Find a base table to validate
        base_table = None
        for table in tables:
            if table.table_type == "BASE TABLE":
                base_table = table
                break

        if base_table:
            # Validate metadata fields exist and are properly typed
            if base_table.row_count is not None:
                assert isinstance(base_table.row_count, int)
                # -1 is valid for PostgreSQL (means stats not gathered yet)
                assert base_table.row_count >= -1

            if base_table.size_bytes is not None:
                assert isinstance(base_table.size_bytes, int)
                assert base_table.size_bytes >= 0

    @pytest.mark.asyncio
    async def test_describe_table_complete(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test describe_table returns comprehensive table information."""
        inspector = MetadataInspector(pg_connection, pg_adapter)

        # Get first table
        tables = await inspector.get_tables("public")
        assert len(tables) > 0

        table_name = tables[0].name
        table_info = await inspector.describe_table(table_name, "public")

        # Validate basic info
        assert table_info.name == table_name
        assert table_info.schema == "public"

        # Validate columns
        assert len(table_info.columns) > 0
        for col in table_info.columns:
            assert col.name is not None
            assert col.data_type is not None
            assert col.nullable is not None

        # Validate statistics fields exist and are properly typed
        if table_info.table_type == "BASE TABLE":
            if table_info.row_count is not None:
                assert isinstance(table_info.row_count, int)
                assert table_info.row_count >= -1

            if table_info.size_bytes is not None:
                assert isinstance(table_info.size_bytes, int)
                assert table_info.size_bytes >= 0


class TestMetadataInspectorRelationships:
    """Test table relationship discovery."""

    @pytest.mark.asyncio
    async def test_get_table_relationships(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test get_table_relationships finds foreign keys."""
        if not pg_adapter.capabilities.foreign_keys:
            pytest.skip("Database doesn't support foreign keys")

        inspector = MetadataInspector(pg_connection, pg_adapter)
        tables = await inspector.get_tables("public")

        # Try to find a table with relationships
        for table in tables[:10]:  # Check first 10 tables
            relationships = await inspector.get_relationships(table.name, "public")

            if relationships:
                rel = relationships[0]

                # Validate relationship structure
                assert rel.from_table is not None
                assert rel.to_table is not None
                assert len(rel.from_columns) > 0
                assert len(rel.to_columns) > 0
                assert rel.constraint_name is not None
                break


class TestMetadataInspectorEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_list_tables_empty_schema(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test listing tables from a schema with no tables."""
        inspector = MetadataInspector(pg_connection, pg_adapter)

        # Try to get tables from a schema that might not have tables
        # This should not raise an error, just return empty list
        tables = await inspector.get_tables("information_schema")
        assert isinstance(tables, list)

    @pytest.mark.asyncio
    async def test_describe_nonexistent_table(
        self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
    ):
        """Test describing a table that doesn't exist."""
        inspector = MetadataInspector(pg_connection, pg_adapter)

        # This should raise an appropriate error
        with pytest.raises(Exception):
            await inspector.describe_table("nonexistent_table_xyz", "public")
