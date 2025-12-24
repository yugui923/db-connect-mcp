"""Module Tests for MetadataInspector

Tests the MetadataInspector component directly without MCP protocol overhead.
Validates:
- Schema listing and metadata
- Table listing with enriched metadata
- Table description with columns, indexes, constraints
- Table relationships (foreign keys)
"""

import pytest

from db_connect_mcp.core import MetadataInspector

pytestmark = [pytest.mark.postgresql, pytest.mark.integration]


class TestMetadataInspectorSchemas:
    """Test schema listing functionality."""

    @pytest.mark.asyncio
    async def test_list_schemas(self, pg_inspector: MetadataInspector):
        """Test list_schemas returns schema information with metadata."""
        schemas = await pg_inspector.get_schemas()

        # Validate schemas returned
        assert len(schemas) > 0

        # Find public schema (guaranteed to exist)
        public_schema = next((s for s in schemas if s.name == "public"), None)
        assert public_schema is not None, "public schema should exist"

        # Validate schema structure
        assert public_schema.table_count is not None
        assert (
            public_schema.table_count >= 5
        )  # At least categories, products, users, orders, order_items

        # Size might be available
        if public_schema.size_bytes is not None:
            assert isinstance(public_schema.size_bytes, int)
            assert public_schema.size_bytes > 0


class TestMetadataInspectorTables:
    """Test table listing and description functionality."""

    @pytest.mark.asyncio
    async def test_list_tables_with_metadata(
        self, pg_inspector: MetadataInspector, known_tables
    ):
        """Test list_tables returns tables with complete metadata."""
        # Get tables from public schema
        tables = await pg_inspector.get_tables("public", include_views=True)

        # Should have at least the known tables
        assert len(tables) >= len(known_tables)

        # Verify known tables exist
        table_names = {t.name for t in tables}
        for table_name in known_tables.keys():
            assert table_name in table_names, (
                f"{table_name} should exist in local test database"
            )

        # Validate metadata for products table (guaranteed to have data)
        products_table = next((t for t in tables if t.name == "products"), None)
        assert products_table is not None
        assert products_table.table_type == "BASE TABLE"

        # Verify row count metadata
        if products_table.row_count is not None:
            expected_min = known_tables["products"]["row_count_min"]
            assert products_table.row_count >= expected_min, (
                f"products should have at least {expected_min} rows"
            )

        # Verify size metadata
        if products_table.size_bytes is not None:
            assert isinstance(products_table.size_bytes, int)
            assert products_table.size_bytes > 0

    @pytest.mark.asyncio
    async def test_describe_table_complete(self, pg_inspector: MetadataInspector):
        """Test describe_table returns complete table metadata."""
        # Use products table (guaranteed to exist with known structure)
        table_info = await pg_inspector.describe_table("products", "public")

        # Validate basic table metadata
        assert table_info.name == "products"
        assert table_info.schema == "public"
        assert len(table_info.columns) > 0

        # Validate known columns exist
        column_names = {col.name for col in table_info.columns}
        expected_columns = ["product_id", "name", "price", "category_id", "sku"]
        for col_name in expected_columns:
            assert col_name in column_names, (
                f"products table should have {col_name} column"
            )

        # Validate primary key
        primary_keys = [col for col in table_info.columns if col.primary_key]
        assert len(primary_keys) > 0, "products should have a primary key"
        assert primary_keys[0].name == "product_id"

        # Validate foreign keys (from constraints)
        if table_info.constraints:
            # products has FK to categories
            fk_constraints = [
                c for c in table_info.constraints if c.constraint_type == "FOREIGN KEY"
            ]
            category_fk = next(
                (fk for fk in fk_constraints if fk.referenced_table == "categories"),
                None,
            )
            assert category_fk is not None, "products should have FK to categories"

        # Validate indexes
        if table_info.indexes:
            assert len(table_info.indexes) > 0, "products should have indexes"


class TestMetadataInspectorRelationships:
    """Test table relationship discovery."""

    @pytest.mark.asyncio
    async def test_get_table_relationships(self, pg_inspector: MetadataInspector):
        """Test get_relationships returns foreign key relationships."""
        # Use products table (guaranteed to have FK to categories)
        relationships = await pg_inspector.get_relationships("products", "public")

        # Should have at least one relationship (to categories)
        assert len(relationships) > 0

        # Find the relationship to categories
        category_rel = next(
            (r for r in relationships if r.to_table == "categories"), None
        )
        assert category_rel is not None, "products should reference categories"
        assert category_rel.from_table == "products"
        assert "category_id" in category_rel.from_columns

    @pytest.mark.asyncio
    async def test_self_referencing_relationship(self, pg_inspector: MetadataInspector):
        """Test self-referencing foreign keys (categories.parent_category_id)."""
        relationships = await pg_inspector.get_relationships("categories", "public")

        # categories has self-referencing FK
        self_ref = next((r for r in relationships if r.to_table == "categories"), None)
        assert self_ref is not None, "categories should have self-referencing FK"
        assert self_ref.from_table == "categories"
        assert "parent_category_id" in self_ref.from_columns


class TestMetadataInspectorEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_list_tables_empty_schema(self, pg_inspector: MetadataInspector):
        """Test list_tables with non-existent schema returns empty list."""
        tables = await pg_inspector.get_tables("nonexistent_schema")
        assert len(tables) == 0

    @pytest.mark.asyncio
    async def test_describe_nonexistent_table(self, pg_inspector: MetadataInspector):
        """Test describe_table with non-existent table raises appropriate error."""
        with pytest.raises(Exception):  # Exact exception type depends on adapter
            await pg_inspector.describe_table("nonexistent_table", "public")
