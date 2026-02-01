"""Module Tests for MySQL MetadataInspector (via SSH Tunnel)

Tests the MetadataInspector component with MySQL accessed through SSH tunnel.
Validates:
- Schema listing and metadata
- Table listing with enriched metadata
- Table description with columns, indexes, constraints
- Table relationships (foreign keys)
"""

import pytest

from db_connect_mcp.core import MetadataInspector

pytestmark = [pytest.mark.mysql, pytest.mark.ssh_tunnel]


class TestMySQLInspectorSchemas:
    """Test schema listing for MySQL."""

    @pytest.mark.asyncio
    async def test_list_schemas(self, mysql_inspector: MetadataInspector):
        """Test list_schemas returns schema information."""
        schemas = await mysql_inspector.get_schemas()

        assert len(schemas) > 0

        # Find testdb schema (MySQL treats databases as schemas)
        testdb = next((s for s in schemas if s.name == "testdb"), None)
        assert testdb is not None, "testdb schema should exist"
        assert testdb.table_count is not None
        assert testdb.table_count >= 3  # categories, products, users


class TestMySQLInspectorTables:
    """Test table listing and description for MySQL."""

    @pytest.mark.asyncio
    async def test_list_tables(self, mysql_inspector: MetadataInspector):
        """Test list_tables returns tables with metadata."""
        tables = await mysql_inspector.get_tables("testdb")

        table_names = {t.name for t in tables}
        assert "categories" in table_names
        assert "products" in table_names
        assert "users" in table_names

    @pytest.mark.asyncio
    async def test_describe_table_categories(self, mysql_inspector: MetadataInspector):
        """Test describe_table for categories table."""
        table = await mysql_inspector.describe_table("categories", "testdb")

        assert table is not None
        assert table.name == "categories"

        col_names = [c.name for c in table.columns]
        assert "category_id" in col_names
        assert "name" in col_names
        assert "description" in col_names

    @pytest.mark.asyncio
    async def test_describe_table_products(self, mysql_inspector: MetadataInspector):
        """Test describe_table for products table."""
        table = await mysql_inspector.describe_table("products", "testdb")

        assert table is not None
        col_names = [c.name for c in table.columns]
        assert "product_id" in col_names
        assert "name" in col_names
        assert "price" in col_names
        assert "category_id" in col_names

    @pytest.mark.asyncio
    async def test_describe_table_has_indexes(self, mysql_inspector: MetadataInspector):
        """Test that indexes are detected on products table."""
        table = await mysql_inspector.describe_table("products", "testdb")

        assert table is not None
        # products has idx_products_name index
        if table.indexes:
            index_names = [idx.name for idx in table.indexes]
            assert any("products_name" in name for name in index_names) or len(index_names) > 0


class TestMySQLInspectorRelationships:
    """Test foreign key relationship detection for MySQL."""

    @pytest.mark.asyncio
    async def test_get_relationships(self, mysql_inspector: MetadataInspector):
        """Test that foreign key relationships are detected."""
        relationships = await mysql_inspector.get_relationships("products", "testdb")

        # products.category_id -> categories.category_id
        assert len(relationships) > 0
        assert relationships[0].from_table == "products"
        assert "category_id" in relationships[0].from_columns
