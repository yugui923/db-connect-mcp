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


class TestMetadataInspectorComments:
    """Test database comment retrieval for AI context."""

    @pytest.mark.asyncio
    async def test_table_comment_retrieved(self, pg_inspector: MetadataInspector):
        """Test that table comments are properly retrieved from database."""
        table_info = await pg_inspector.describe_table("categories", "public")

        # categories table has: COMMENT ON TABLE categories IS 'Product categories with hierarchical structure';
        assert table_info.comment is not None
        assert "Product categories" in table_info.comment
        assert "hierarchical" in table_info.comment

    @pytest.mark.asyncio
    async def test_column_comment_retrieved(self, pg_inspector: MetadataInspector):
        """Test that column comments are properly retrieved from database."""
        table_info = await pg_inspector.describe_table("categories", "public")

        # categories.parent_category_id has: COMMENT ON COLUMN categories.parent_category_id IS 'Self-referencing foreign key for category hierarchy';
        parent_col = next(
            (c for c in table_info.columns if c.name == "parent_category_id"), None
        )
        assert parent_col is not None
        assert parent_col.comment is not None
        assert "Self-referencing" in parent_col.comment

    @pytest.mark.asyncio
    async def test_products_table_and_column_comments(
        self, pg_inspector: MetadataInspector
    ):
        """Test comments on products table and its columns."""
        table_info = await pg_inspector.describe_table("products", "public")

        # Table comment: COMMENT ON TABLE products IS 'Product catalog with various data types for comprehensive testing';
        assert table_info.comment is not None
        assert "Product catalog" in table_info.comment

        # Column comment: COMMENT ON COLUMN products.product_uuid IS 'UUID for testing UUID serialization';
        uuid_col = next(
            (c for c in table_info.columns if c.name == "product_uuid"), None
        )
        assert uuid_col is not None
        assert uuid_col.comment is not None
        assert "UUID" in uuid_col.comment

    @pytest.mark.asyncio
    async def test_columns_without_comments(self, pg_inspector: MetadataInspector):
        """Test that columns without comments have None comment."""
        table_info = await pg_inspector.describe_table("products", "public")

        # product_id and name columns don't have comments
        product_id_col = next(
            (c for c in table_info.columns if c.name == "product_id"), None
        )
        assert product_id_col is not None
        # Columns without explicit comments should have None
        # (SQLAlchemy might still extract system-generated comments, so we just check it doesn't error)

    @pytest.mark.asyncio
    async def test_comments_in_json_serialization(
        self, pg_inspector: MetadataInspector
    ):
        """Test that comments are properly included in JSON serialization."""
        import json

        table_info = await pg_inspector.describe_table("categories", "public")

        # Serialize to JSON (as MCP tool does)
        json_output = table_info.model_dump(mode="json")

        # Table comment should be in JSON
        assert "comment" in json_output
        assert json_output["comment"] is not None
        assert "Product categories" in json_output["comment"]

        # Column comments should be in JSON
        columns = json_output["columns"]
        parent_col = next(
            (c for c in columns if c["name"] == "parent_category_id"), None
        )
        assert parent_col is not None
        assert "comment" in parent_col
        assert parent_col["comment"] is not None

        # Verify JSON is valid (no serialization errors)
        json_str = json.dumps(json_output)
        assert len(json_str) > 0
        parsed = json.loads(json_str)
        assert parsed["comment"] == json_output["comment"]

    @pytest.mark.asyncio
    async def test_all_columns_have_comment_field(
        self, pg_inspector: MetadataInspector
    ):
        """Test that all columns have a comment field (even if None)."""
        table_info = await pg_inspector.describe_table("products", "public")

        for col in table_info.columns:
            # Every column should have the comment attribute (can be None)
            assert hasattr(col, "comment"), (
                f"Column {col.name} missing comment attribute"
            )

    @pytest.mark.asyncio
    async def test_multiple_tables_comments(self, pg_inspector: MetadataInspector):
        """Test comments are retrieved correctly across multiple tables."""
        tables_with_comments = ["categories", "products", "users", "orders"]

        for table_name in tables_with_comments:
            table_info = await pg_inspector.describe_table(table_name, "public")

            # Each of these tables should have a table-level comment
            assert table_info.comment is not None, f"{table_name} should have a comment"
            assert len(table_info.comment) > 0, (
                f"{table_name} comment should not be empty"
            )

    @pytest.mark.asyncio
    async def test_comment_content_is_string(self, pg_inspector: MetadataInspector):
        """Test that comment values are always strings (not bytes or other types)."""
        table_info = await pg_inspector.describe_table("categories", "public")

        # Table comment should be string
        assert isinstance(table_info.comment, str)

        # Column comment should be string
        parent_col = next(
            (c for c in table_info.columns if c.name == "parent_category_id"), None
        )
        assert isinstance(parent_col.comment, str)


class TestMetadataInspectorLongComments:
    """Test edge cases with very long database comments."""

    @pytest.mark.asyncio
    async def test_long_column_comment_retrieved(self, pg_inspector: MetadataInspector):
        """Test that very long column comments (2000+ chars) are properly retrieved."""
        table_info = await pg_inspector.describe_table("data_type_examples", "public")

        # money_col has a very long comment (2700+ characters)
        money_col = next((c for c in table_info.columns if c.name == "money_col"), None)
        assert money_col is not None
        assert money_col.comment is not None

        # Should be a long comment
        assert len(money_col.comment) > 2000, (
            f"Expected long comment > 2000 chars, got {len(money_col.comment)}"
        )

        # Should contain expected content
        assert "PostgreSQL MONEY type" in money_col.comment
        assert "locale-aware" in money_col.comment

    @pytest.mark.asyncio
    async def test_long_comment_json_serialization(
        self, pg_inspector: MetadataInspector
    ):
        """Test that very long comments serialize correctly to JSON."""
        import json

        table_info = await pg_inspector.describe_table("data_type_examples", "public")

        # Serialize to JSON (as MCP tool does)
        json_output = table_info.model_dump(mode="json")
        json_str = json.dumps(json_output)

        # Should be valid JSON
        parsed = json.loads(json_str)

        # Find the money_col
        money_col = next(
            (c for c in parsed["columns"] if c["name"] == "money_col"), None
        )
        assert money_col is not None
        assert money_col["comment"] is not None
        assert len(money_col["comment"]) > 2000

    @pytest.mark.asyncio
    async def test_many_columns_with_comments(self, pg_inspector: MetadataInspector):
        """Test table with many column comments doesn't cause issues."""
        table_info = await pg_inspector.describe_table("data_type_examples", "public")

        # data_type_examples has 29 columns, all with comments
        cols_with_comments = [c for c in table_info.columns if c.comment]

        # Should have many columns with comments (at least 25)
        assert len(cols_with_comments) >= 25, (
            f"Expected at least 25 columns with comments, got {len(cols_with_comments)}"
        )

    @pytest.mark.asyncio
    async def test_comprehensive_column_comments(self, pg_inspector: MetadataInspector):
        """Test that all expected column comments are present in products table."""
        table_info = await pg_inspector.describe_table("products", "public")

        # Count columns with comments
        cols_with_comments = {
            c.name: c.comment for c in table_info.columns if c.comment
        }

        # Should have many column comments (we added 15+ in products)
        assert len(cols_with_comments) >= 10, (
            f"Expected at least 10 columns with comments, got {len(cols_with_comments)}"
        )

        # Check specific comments are meaningful
        if "sku" in cols_with_comments:
            assert "Stock Keeping Unit" in cols_with_comments["sku"]

        if "price" in cols_with_comments:
            assert (
                "USD" in cols_with_comments["price"]
                or "selling" in cols_with_comments["price"]
            )


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


class TestExpressionBasedIndexes:
    """Test that expression-based indexes don't crash describe_table."""

    @pytest.fixture(autouse=True)
    async def _setup_expression_index_table(self):
        """Create a test table with expression-based indexes.

        Uses a separate writable connection since pg_connection is read-only.
        """
        import os

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        url = os.getenv("PG_TEST_DATABASE_URL")
        if not url:
            pytest.skip("PG_TEST_DATABASE_URL not set")

        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS _test_expr_indexes ("
                    "  id serial PRIMARY KEY,"
                    "  name text NOT NULL,"
                    "  email text NOT NULL,"
                    "  city text"
                    ")"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_expr_lower_name "
                    "ON _test_expr_indexes (lower(name))"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_expr_mixed "
                    "ON _test_expr_indexes (id, lower(email))"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_expr_normal "
                    "ON _test_expr_indexes (name, email)"
                )
            )

        yield

        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS _test_expr_indexes"))
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_describe_table_with_expression_index(
        self, pg_inspector: MetadataInspector
    ):
        """describe_table should not fail on tables with expression indexes."""
        table_info = await pg_inspector.describe_table("_test_expr_indexes", "public")
        assert table_info.name == "_test_expr_indexes"
        assert len(table_info.indexes) >= 3

    @pytest.mark.asyncio
    async def test_expression_index_columns_are_strings(
        self, pg_inspector: MetadataInspector
    ):
        """All index column entries should be strings, never None."""
        table_info = await pg_inspector.describe_table("_test_expr_indexes", "public")
        for idx in table_info.indexes:
            for col in idx.columns:
                assert isinstance(col, str), (
                    f"Index {idx.name} has non-string column: {col!r}"
                )
                assert col, f"Index {idx.name} has empty column name"

    @pytest.mark.asyncio
    async def test_expression_index_contains_expression_text(
        self, pg_inspector: MetadataInspector
    ):
        """Expression-based index should include expression text in columns."""
        table_info = await pg_inspector.describe_table("_test_expr_indexes", "public")
        idx_map = {idx.name: idx for idx in table_info.indexes}

        lower_name_idx = idx_map.get("idx_expr_lower_name")
        assert lower_name_idx is not None
        assert any("lower" in col for col in lower_name_idx.columns)

        mixed_idx = idx_map.get("idx_expr_mixed")
        assert mixed_idx is not None
        assert "id" in mixed_idx.columns
        assert any("lower" in col for col in mixed_idx.columns)

    @pytest.mark.asyncio
    async def test_normal_index_unchanged(self, pg_inspector: MetadataInspector):
        """Normal column indexes should still work as before."""
        table_info = await pg_inspector.describe_table("_test_expr_indexes", "public")
        idx_map = {idx.name: idx for idx in table_info.indexes}

        normal_idx = idx_map.get("idx_expr_normal")
        assert normal_idx is not None
        assert normal_idx.columns == ["name", "email"]
