"""Module Tests for MySQL MetadataInspector

Tests both direct and tunneled MySQL access for the MetadataInspector component.
"""

import pytest

from db_connect_mcp.core import MetadataInspector


# ==================== MySQL Direct ====================


class TestMySQLDirectInspectorSchemas:
    """Test schema listing for MySQL direct."""

    pytestmark = [pytest.mark.mysql]

    @pytest.mark.asyncio
    async def test_list_schemas(self, mysql_inspector: MetadataInspector):
        schemas = await mysql_inspector.get_schemas()
        assert len(schemas) > 0
        testdb = next((s for s in schemas if s.name == "testdb"), None)
        assert testdb is not None, "testdb schema should exist"
        assert testdb.table_count is not None
        assert testdb.table_count >= 3


class TestMySQLDirectInspectorTables:
    """Test table listing and description for MySQL direct."""

    pytestmark = [pytest.mark.mysql]

    @pytest.mark.asyncio
    async def test_list_tables(self, mysql_inspector: MetadataInspector):
        tables = await mysql_inspector.get_tables("testdb")
        table_names = {t.name for t in tables}
        assert "categories" in table_names
        assert "products" in table_names
        assert "users" in table_names

    @pytest.mark.asyncio
    async def test_describe_table_categories(self, mysql_inspector: MetadataInspector):
        table = await mysql_inspector.describe_table("categories", "testdb")
        assert table is not None
        assert table.name == "categories"
        col_names = [c.name for c in table.columns]
        assert "category_id" in col_names
        assert "name" in col_names

    @pytest.mark.asyncio
    async def test_describe_table_products(self, mysql_inspector: MetadataInspector):
        table = await mysql_inspector.describe_table("products", "testdb")
        assert table is not None
        col_names = [c.name for c in table.columns]
        assert "product_id" in col_names
        assert "price" in col_names
        assert "category_id" in col_names

    @pytest.mark.asyncio
    async def test_describe_table_has_indexes(self, mysql_inspector: MetadataInspector):
        table = await mysql_inspector.describe_table("products", "testdb")
        assert table is not None
        if table.indexes:
            assert len(table.indexes) > 0


class TestMySQLDirectInspectorRelationships:
    """Test FK detection for MySQL direct."""

    pytestmark = [pytest.mark.mysql]

    @pytest.mark.asyncio
    async def test_get_relationships(self, mysql_inspector: MetadataInspector):
        relationships = await mysql_inspector.get_relationships("products", "testdb")
        assert len(relationships) > 0
        assert relationships[0].from_table == "products"
        assert "category_id" in relationships[0].from_columns


# ==================== MySQL Tunneled ====================


class TestMySQLTunneledInspectorSchemas:
    """Test schema listing for MySQL via SSH tunnel."""

    pytestmark = [pytest.mark.mysql, pytest.mark.ssh_tunnel]

    @pytest.mark.asyncio
    async def test_list_schemas(self, mysql_tunnel_inspector: MetadataInspector):
        schemas = await mysql_tunnel_inspector.get_schemas()
        assert len(schemas) > 0
        testdb = next((s for s in schemas if s.name == "testdb"), None)
        assert testdb is not None, "testdb schema should exist"
        assert testdb.table_count is not None
        assert testdb.table_count >= 3


class TestMySQLTunneledInspectorTables:
    """Test table listing and description for MySQL via SSH tunnel."""

    pytestmark = [pytest.mark.mysql, pytest.mark.ssh_tunnel]

    @pytest.mark.asyncio
    async def test_list_tables(self, mysql_tunnel_inspector: MetadataInspector):
        tables = await mysql_tunnel_inspector.get_tables("testdb")
        table_names = {t.name for t in tables}
        assert "categories" in table_names
        assert "products" in table_names
        assert "users" in table_names

    @pytest.mark.asyncio
    async def test_describe_table_products(self, mysql_tunnel_inspector: MetadataInspector):
        table = await mysql_tunnel_inspector.describe_table("products", "testdb")
        assert table is not None
        col_names = [c.name for c in table.columns]
        assert "product_id" in col_names
        assert "price" in col_names


class TestMySQLTunneledInspectorRelationships:
    """Test FK detection for MySQL via SSH tunnel."""

    pytestmark = [pytest.mark.mysql, pytest.mark.ssh_tunnel]

    @pytest.mark.asyncio
    async def test_get_relationships(self, mysql_tunnel_inspector: MetadataInspector):
        relationships = await mysql_tunnel_inspector.get_relationships("products", "testdb")
        assert len(relationships) > 0
        assert relationships[0].from_table == "products"
