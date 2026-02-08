"""Tests for database and schema information models."""

import pytest

from db_connect_mcp.models.capabilities import DatabaseCapabilities
from db_connect_mcp.models.database import DatabaseInfo, SchemaInfo


class TestSchemaInfo:
    """Tests for SchemaInfo model."""

    def test_basic_creation(self):
        """Test creating a schema with required fields."""
        schema = SchemaInfo(name="public")
        assert schema.name == "public"
        assert schema.owner is None
        assert schema.table_count is None
        assert schema.size_bytes is None

    def test_full_creation(self):
        """Test creating a schema with all fields."""
        schema = SchemaInfo(
            name="analytics",
            owner="admin",
            table_count=15,
            view_count=3,
            size_bytes=1024 * 1024 * 100,
            comment="Analytics data warehouse",
        )
        assert schema.name == "analytics"
        assert schema.owner == "admin"
        assert schema.table_count == 15
        assert schema.view_count == 3
        assert schema.comment == "Analytics data warehouse"

    def test_size_human_none(self):
        """Test size_human returns None when size_bytes is None."""
        schema = SchemaInfo(name="public")
        assert schema.size_human is None

    def test_size_human_bytes(self):
        """Test size_human formats bytes correctly."""
        schema = SchemaInfo(name="public", size_bytes=512)
        assert schema.size_human == "512.00 B"

    def test_size_human_kilobytes(self):
        """Test size_human formats kilobytes correctly."""
        schema = SchemaInfo(name="public", size_bytes=2048)  # 2 KB
        assert schema.size_human == "2.00 KB"

    def test_size_human_megabytes(self):
        """Test size_human formats megabytes correctly."""
        schema = SchemaInfo(name="public", size_bytes=1024 * 1024 * 50)  # 50 MB
        assert schema.size_human == "50.00 MB"

    def test_size_human_gigabytes(self):
        """Test size_human formats gigabytes correctly."""
        schema = SchemaInfo(name="public", size_bytes=1024 * 1024 * 1024 * 2)  # 2 GB
        assert schema.size_human == "2.00 GB"

    def test_size_human_terabytes(self):
        """Test size_human formats terabytes correctly."""
        schema = SchemaInfo(
            name="public", size_bytes=1024 * 1024 * 1024 * 1024 * 3
        )  # 3 TB
        assert schema.size_human == "3.00 TB"

    def test_size_human_petabytes(self):
        """Test size_human formats petabytes correctly."""
        schema = SchemaInfo(
            name="public", size_bytes=1024 * 1024 * 1024 * 1024 * 1024 * 2
        )  # 2 PB
        assert schema.size_human == "2.00 PB"

    def test_size_human_fractional(self):
        """Test size_human with fractional values."""
        schema = SchemaInfo(name="public", size_bytes=1536)  # 1.5 KB
        assert schema.size_human == "1.50 KB"


class TestDatabaseInfo:
    """Tests for DatabaseInfo model."""

    @pytest.fixture
    def minimal_capabilities(self):
        """Create minimal capabilities for testing."""
        return DatabaseCapabilities(
            foreign_keys=False,
            indexes=True,
            views=True,
            materialized_views=False,
            partitions=False,
            advanced_stats=False,
            explain_plans=True,
            profiling=False,
            comments=False,
            schemas=True,
            transactions=True,
            stored_procedures=False,
            triggers=False,
        )

    @pytest.fixture
    def full_capabilities(self):
        """Create full capabilities for testing."""
        return DatabaseCapabilities(
            foreign_keys=True,
            indexes=True,
            views=True,
            materialized_views=True,
            partitions=True,
            advanced_stats=True,
            explain_plans=True,
            profiling=True,
            comments=True,
            schemas=True,
            transactions=True,
            stored_procedures=True,
            triggers=True,
        )

    def test_basic_creation(self, minimal_capabilities):
        """Test creating a database info with required fields."""
        db = DatabaseInfo(
            name="testdb",
            dialect="postgresql",
            version="PostgreSQL 15.0",
            capabilities=minimal_capabilities,
            connection_url="postgresql+asyncpg://localhost:5432/testdb",
        )
        assert db.name == "testdb"
        assert db.dialect == "postgresql"
        assert db.version == "PostgreSQL 15.0"
        assert db.read_only is True
        assert db.size_bytes is None

    def test_size_human_none(self, minimal_capabilities):
        """Test size_human returns None when size_bytes is None."""
        db = DatabaseInfo(
            name="testdb",
            dialect="postgresql",
            version="PostgreSQL 15.0",
            capabilities=minimal_capabilities,
            connection_url="postgresql+asyncpg://localhost:5432/testdb",
        )
        assert db.size_human is None

    def test_size_human_bytes(self, minimal_capabilities):
        """Test size_human formats bytes correctly."""
        db = DatabaseInfo(
            name="testdb",
            dialect="postgresql",
            version="PostgreSQL 15.0",
            capabilities=minimal_capabilities,
            connection_url="postgresql+asyncpg://localhost:5432/testdb",
            size_bytes=512,
        )
        assert db.size_human == "512.00 B"

    def test_size_human_kilobytes(self, minimal_capabilities):
        """Test size_human formats kilobytes correctly."""
        db = DatabaseInfo(
            name="testdb",
            dialect="postgresql",
            version="PostgreSQL 15.0",
            capabilities=minimal_capabilities,
            connection_url="postgresql+asyncpg://localhost:5432/testdb",
            size_bytes=2048,
        )
        assert db.size_human == "2.00 KB"

    def test_size_human_megabytes(self, minimal_capabilities):
        """Test size_human formats megabytes correctly."""
        db = DatabaseInfo(
            name="testdb",
            dialect="postgresql",
            version="PostgreSQL 15.0",
            capabilities=minimal_capabilities,
            connection_url="postgresql+asyncpg://localhost:5432/testdb",
            size_bytes=1024 * 1024 * 50,
        )
        assert db.size_human == "50.00 MB"

    def test_size_human_gigabytes(self, minimal_capabilities):
        """Test size_human formats gigabytes correctly."""
        db = DatabaseInfo(
            name="testdb",
            dialect="postgresql",
            version="PostgreSQL 15.0",
            capabilities=minimal_capabilities,
            connection_url="postgresql+asyncpg://localhost:5432/testdb",
            size_bytes=1024 * 1024 * 1024 * 2,
        )
        assert db.size_human == "2.00 GB"

    def test_size_human_terabytes(self, minimal_capabilities):
        """Test size_human formats terabytes correctly."""
        db = DatabaseInfo(
            name="testdb",
            dialect="postgresql",
            version="PostgreSQL 15.0",
            capabilities=minimal_capabilities,
            connection_url="postgresql+asyncpg://localhost:5432/testdb",
            size_bytes=1024 * 1024 * 1024 * 1024 * 3,
        )
        assert db.size_human == "3.00 TB"

    def test_size_human_petabytes(self, minimal_capabilities):
        """Test size_human formats petabytes correctly."""
        db = DatabaseInfo(
            name="testdb",
            dialect="postgresql",
            version="PostgreSQL 15.0",
            capabilities=minimal_capabilities,
            connection_url="postgresql+asyncpg://localhost:5432/testdb",
            size_bytes=1024 * 1024 * 1024 * 1024 * 1024 * 2,
        )
        assert db.size_human == "2.00 PB"

    def test_get_feature_summary_few_features(self, minimal_capabilities):
        """Test get_feature_summary with fewer than 5 features."""
        # minimal_capabilities has: indexes, views, explain_plans, schemas, transactions
        # That's exactly 5 features
        db = DatabaseInfo(
            name="testdb",
            dialect="postgresql",
            version="PostgreSQL 15.0",
            capabilities=minimal_capabilities,
            connection_url="postgresql+asyncpg://localhost:5432/testdb",
        )
        summary = db.get_feature_summary()
        assert "5 features supported" in summary
        assert "..." not in summary  # No ellipsis for exactly 5

    def test_get_feature_summary_many_features(self, full_capabilities):
        """Test get_feature_summary with more than 5 features."""
        db = DatabaseInfo(
            name="testdb",
            dialect="postgresql",
            version="PostgreSQL 15.0",
            capabilities=full_capabilities,
            connection_url="postgresql+asyncpg://localhost:5432/testdb",
        )
        summary = db.get_feature_summary()
        assert "13 features supported" in summary
        assert "..." in summary  # Has ellipsis for > 5 features

    def test_get_feature_summary_three_features(self):
        """Test get_feature_summary with only 3 features."""
        capabilities = DatabaseCapabilities(
            foreign_keys=False,
            indexes=True,
            views=True,
            materialized_views=False,
            partitions=False,
            advanced_stats=False,
            explain_plans=True,
            profiling=False,
            comments=False,
            schemas=False,
            transactions=False,
            stored_procedures=False,
            triggers=False,
        )
        db = DatabaseInfo(
            name="testdb",
            dialect="mysql",
            version="MySQL 8.0",
            capabilities=capabilities,
            connection_url="mysql+aiomysql://localhost:3306/testdb",
        )
        summary = db.get_feature_summary()
        assert "3 features supported" in summary
        assert "..." not in summary

    def test_full_database_info(self, full_capabilities):
        """Test creating a fully populated database info."""
        db = DatabaseInfo(
            name="production_db",
            dialect="postgresql",
            version="PostgreSQL 16.1",
            size_bytes=1024 * 1024 * 1024 * 10,  # 10 GB
            schema_count=5,
            table_count=150,
            capabilities=full_capabilities,
            server_encoding="UTF8",
            collation="en_US.UTF-8",
            connection_url="postgresql+asyncpg://localhost:5432/production_db",
            read_only=True,
            extra_info={"uptime_hours": 720, "max_connections": 100},
        )
        assert db.name == "production_db"
        assert db.size_human == "10.00 GB"
        assert db.schema_count == 5
        assert db.table_count == 150
        assert db.server_encoding == "UTF8"
        assert db.extra_info["uptime_hours"] == 720


class TestDatabaseCapabilities:
    """Tests for DatabaseCapabilities model."""

    def test_default_values(self):
        """Test that defaults are set correctly."""
        caps = DatabaseCapabilities()
        assert caps.foreign_keys is False
        assert caps.indexes is True
        assert caps.views is True
        assert caps.materialized_views is False
        assert caps.partitions is False
        assert caps.advanced_stats is False
        assert caps.explain_plans is True
        assert caps.profiling is False
        assert caps.comments is False
        assert caps.schemas is True
        assert caps.transactions is True
        assert caps.stored_procedures is False
        assert caps.triggers is False

    def test_get_supported_features(self):
        """Test get_supported_features returns only True features."""
        caps = DatabaseCapabilities(
            foreign_keys=True,
            indexes=True,
            views=False,
        )
        supported = caps.get_supported_features()
        assert "foreign_keys" in supported
        assert "indexes" in supported
        assert "views" not in supported

    def test_get_unsupported_features(self):
        """Test get_unsupported_features returns only False features."""
        caps = DatabaseCapabilities(
            foreign_keys=True,
            indexes=True,
            views=False,
            materialized_views=False,
        )
        unsupported = caps.get_unsupported_features()
        assert "foreign_keys" not in unsupported
        assert "indexes" not in unsupported
        assert "views" in unsupported
        assert "materialized_views" in unsupported

    def test_all_features_enabled(self):
        """Test with all features enabled."""
        caps = DatabaseCapabilities(
            foreign_keys=True,
            indexes=True,
            views=True,
            materialized_views=True,
            partitions=True,
            advanced_stats=True,
            explain_plans=True,
            profiling=True,
            comments=True,
            schemas=True,
            transactions=True,
            stored_procedures=True,
            triggers=True,
        )
        supported = caps.get_supported_features()
        unsupported = caps.get_unsupported_features()
        assert len(supported) == 13
        assert len(unsupported) == 0
