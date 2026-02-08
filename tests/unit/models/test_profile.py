"""Tests for database profiling models."""

import pytest

from db_connect_mcp.models.profile import (
    DatabaseProfile,
    SchemaProfile,
    TableProfile,
)


class TestSchemaProfile:
    """Tests for SchemaProfile model."""

    def test_basic_creation(self):
        """Test creating a schema profile with required fields."""
        profile = SchemaProfile(name="public", table_count=10)
        assert profile.name == "public"
        assert profile.table_count == 10
        assert profile.view_count is None
        assert profile.total_size_bytes is None
        assert profile.total_rows is None

    def test_full_creation(self):
        """Test creating a schema profile with all fields."""
        profile = SchemaProfile(
            name="myschema",
            table_count=5,
            view_count=3,
            total_size_bytes=1024 * 1024 * 100,  # 100 MB
            total_rows=50000,
        )
        assert profile.name == "myschema"
        assert profile.table_count == 5
        assert profile.view_count == 3
        assert profile.total_size_bytes == 104857600
        assert profile.total_rows == 50000


class TestTableProfile:
    """Tests for TableProfile model."""

    def test_basic_creation(self):
        """Test creating a table profile with required fields."""
        profile = TableProfile(name="users", table_type="BASE TABLE")
        assert profile.name == "users"
        assert profile.table_type == "BASE TABLE"
        assert profile.schema is None
        assert profile.size_bytes is None
        assert profile.index_size_bytes is None
        assert profile.row_count is None

    def test_full_creation(self):
        """Test creating a table profile with all fields."""
        profile = TableProfile(
            schema="public",
            name="orders",
            table_type="BASE TABLE",
            size_bytes=1024 * 1024 * 50,  # 50 MB
            index_size_bytes=1024 * 1024 * 10,  # 10 MB
            row_count=100000,
        )
        assert profile.schema == "public"
        assert profile.name == "orders"
        assert profile.table_type == "BASE TABLE"
        assert profile.size_bytes == 52428800
        assert profile.index_size_bytes == 10485760
        assert profile.row_count == 100000

    def test_view_type(self):
        """Test creating a view profile."""
        profile = TableProfile(
            schema="public",
            name="active_users",
            table_type="VIEW",
        )
        assert profile.table_type == "VIEW"


class TestDatabaseProfile:
    """Tests for DatabaseProfile model."""

    def test_basic_creation(self):
        """Test creating a database profile with required fields."""
        profile = DatabaseProfile(
            database_name="testdb",
            version="PostgreSQL 15.0",
            total_schemas=3,
            total_tables=25,
        )
        assert profile.database_name == "testdb"
        assert profile.version == "PostgreSQL 15.0"
        assert profile.total_schemas == 3
        assert profile.total_tables == 25
        assert profile.total_size_bytes is None
        assert profile.total_views is None
        assert profile.schemas == []
        assert profile.largest_tables == []

    def test_total_size_mb_with_none(self):
        """Test total_size_mb returns None when total_size_bytes is None."""
        profile = DatabaseProfile(
            database_name="testdb",
            version="PostgreSQL 15.0",
            total_schemas=1,
            total_tables=1,
            total_size_bytes=None,
        )
        assert profile.total_size_mb is None

    def test_total_size_mb_conversion(self):
        """Test total_size_mb correctly converts bytes to megabytes."""
        # 100 MB in bytes
        size_bytes = 100 * 1024 * 1024
        profile = DatabaseProfile(
            database_name="testdb",
            version="PostgreSQL 15.0",
            total_schemas=1,
            total_tables=1,
            total_size_bytes=size_bytes,
        )
        assert profile.total_size_mb == 100.0

    def test_total_size_mb_fractional(self):
        """Test total_size_mb with fractional values."""
        # 1.5 MB in bytes
        size_bytes = int(1.5 * 1024 * 1024)
        profile = DatabaseProfile(
            database_name="testdb",
            version="PostgreSQL 15.0",
            total_schemas=1,
            total_tables=1,
            total_size_bytes=size_bytes,
        )
        assert profile.total_size_mb == pytest.approx(1.5, rel=0.01)

    def test_total_size_gb_with_none(self):
        """Test total_size_gb returns None when total_size_bytes is None."""
        profile = DatabaseProfile(
            database_name="testdb",
            version="PostgreSQL 15.0",
            total_schemas=1,
            total_tables=1,
            total_size_bytes=None,
        )
        assert profile.total_size_gb is None

    def test_total_size_gb_conversion(self):
        """Test total_size_gb correctly converts bytes to gigabytes."""
        # 2 GB in bytes
        size_bytes = 2 * 1024 * 1024 * 1024
        profile = DatabaseProfile(
            database_name="testdb",
            version="PostgreSQL 15.0",
            total_schemas=1,
            total_tables=1,
            total_size_bytes=size_bytes,
        )
        assert profile.total_size_gb == 2.0

    def test_total_size_gb_fractional(self):
        """Test total_size_gb with fractional values."""
        # 0.5 GB in bytes
        size_bytes = int(0.5 * 1024 * 1024 * 1024)
        profile = DatabaseProfile(
            database_name="testdb",
            version="PostgreSQL 15.0",
            total_schemas=1,
            total_tables=1,
            total_size_bytes=size_bytes,
        )
        assert profile.total_size_gb == pytest.approx(0.5, rel=0.01)

    def test_get_schema_by_name_found(self):
        """Test get_schema_by_name returns matching schema."""
        schemas = [
            SchemaProfile(name="public", table_count=10),
            SchemaProfile(name="private", table_count=5),
            SchemaProfile(name="analytics", table_count=20),
        ]
        profile = DatabaseProfile(
            database_name="testdb",
            version="PostgreSQL 15.0",
            total_schemas=3,
            total_tables=35,
            schemas=schemas,
        )

        result = profile.get_schema_by_name("private")
        assert result is not None
        assert result.name == "private"
        assert result.table_count == 5

    def test_get_schema_by_name_not_found(self):
        """Test get_schema_by_name returns None for non-existent schema."""
        schemas = [
            SchemaProfile(name="public", table_count=10),
        ]
        profile = DatabaseProfile(
            database_name="testdb",
            version="PostgreSQL 15.0",
            total_schemas=1,
            total_tables=10,
            schemas=schemas,
        )

        result = profile.get_schema_by_name("nonexistent")
        assert result is None

    def test_get_schema_by_name_empty_list(self):
        """Test get_schema_by_name with empty schemas list."""
        profile = DatabaseProfile(
            database_name="testdb",
            version="PostgreSQL 15.0",
            total_schemas=0,
            total_tables=0,
            schemas=[],
        )

        result = profile.get_schema_by_name("public")
        assert result is None

    def test_get_schema_by_name_case_sensitive(self):
        """Test get_schema_by_name is case-sensitive."""
        schemas = [
            SchemaProfile(name="Public", table_count=10),
        ]
        profile = DatabaseProfile(
            database_name="testdb",
            version="PostgreSQL 15.0",
            total_schemas=1,
            total_tables=10,
            schemas=schemas,
        )

        # Exact case match should work
        assert profile.get_schema_by_name("Public") is not None
        # Different case should not match
        assert profile.get_schema_by_name("public") is None
        assert profile.get_schema_by_name("PUBLIC") is None

    def test_get_schema_by_name_returns_first_match(self):
        """Test get_schema_by_name returns first match if duplicates exist."""
        schemas = [
            SchemaProfile(name="public", table_count=10),
            SchemaProfile(name="public", table_count=20),  # Duplicate name
        ]
        profile = DatabaseProfile(
            database_name="testdb",
            version="PostgreSQL 15.0",
            total_schemas=2,
            total_tables=30,
            schemas=schemas,
        )

        result = profile.get_schema_by_name("public")
        assert result is not None
        assert result.table_count == 10  # First one

    def test_full_profile_with_all_fields(self):
        """Test creating a complete database profile."""
        schemas = [
            SchemaProfile(
                name="public",
                table_count=10,
                view_count=2,
                total_size_bytes=1024 * 1024 * 500,
                total_rows=100000,
            )
        ]
        largest_tables = [
            TableProfile(
                schema="public",
                name="events",
                table_type="BASE TABLE",
                size_bytes=1024 * 1024 * 200,
                row_count=50000,
            )
        ]

        profile = DatabaseProfile(
            database_name="production",
            version="PostgreSQL 16.1",
            total_size_bytes=1024 * 1024 * 1024,  # 1 GB
            total_schemas=1,
            total_tables=10,
            total_views=2,
            total_indexes=15,
            schemas=schemas,
            largest_tables=largest_tables,
            total_index_size_bytes=1024 * 1024 * 100,
            index_to_table_ratio=0.1,
            extra_info={"uptime": "30 days", "connections": 50},
        )

        assert profile.database_name == "production"
        assert profile.total_size_gb == 1.0
        assert profile.total_size_mb == 1024.0
        assert len(profile.schemas) == 1
        assert len(profile.largest_tables) == 1
        assert profile.extra_info["uptime"] == "30 days"
