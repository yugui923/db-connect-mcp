"""Tests for table, column, index, and constraint models."""

import pytest

from db_connect_mcp.models.table import (
    ColumnInfo,
    ConstraintInfo,
    IndexInfo,
    RelationshipInfo,
    TableInfo,
)


class TestColumnInfo:
    """Tests for ColumnInfo model."""

    def test_basic_creation(self):
        """Test creating a column with required fields."""
        col = ColumnInfo(name="id", data_type="integer", nullable=False)
        assert col.name == "id"
        assert col.data_type == "integer"
        assert col.nullable is False
        assert col.primary_key is False
        assert col.foreign_key is None

    def test_full_creation(self):
        """Test creating a column with all fields."""
        col = ColumnInfo(
            name="price",
            data_type="decimal",
            nullable=True,
            default="0.00",
            primary_key=False,
            foreign_key=None,
            unique=False,
            indexed=True,
            comment="Product price in USD",
            max_length=None,
            numeric_precision=10,
            numeric_scale=2,
            extra_info={"auto_increment": False},
        )
        assert col.name == "price"
        assert col.numeric_precision == 10
        assert col.numeric_scale == 2
        assert col.comment == "Product price in USD"


class TestIndexInfo:
    """Tests for IndexInfo model."""

    def test_basic_creation(self):
        """Test creating an index with required fields."""
        idx = IndexInfo(name="idx_users_email", columns=["email"])
        assert idx.name == "idx_users_email"
        assert idx.columns == ["email"]
        assert idx.unique is False
        assert idx.primary is False

    def test_size_human_none(self):
        """Test size_human returns None when size_bytes is None."""
        idx = IndexInfo(name="idx_test", columns=["id"])
        assert idx.size_human is None

    def test_size_human_bytes(self):
        """Test size_human formats bytes correctly."""
        idx = IndexInfo(name="idx_test", columns=["id"], size_bytes=512)
        assert idx.size_human == "512.00 B"

    def test_size_human_kilobytes(self):
        """Test size_human formats kilobytes correctly."""
        idx = IndexInfo(name="idx_test", columns=["id"], size_bytes=2048)
        assert idx.size_human == "2.00 KB"

    def test_size_human_megabytes(self):
        """Test size_human formats megabytes correctly."""
        idx = IndexInfo(name="idx_test", columns=["id"], size_bytes=1024 * 1024 * 50)
        assert idx.size_human == "50.00 MB"

    def test_size_human_gigabytes(self):
        """Test size_human formats gigabytes correctly."""
        idx = IndexInfo(
            name="idx_test", columns=["id"], size_bytes=1024 * 1024 * 1024 * 2
        )
        assert idx.size_human == "2.00 GB"

    def test_size_human_terabytes(self):
        """Test size_human formats terabytes correctly."""
        idx = IndexInfo(
            name="idx_test", columns=["id"], size_bytes=1024 * 1024 * 1024 * 1024 * 3
        )
        assert idx.size_human == "3.00 TB"

    def test_multi_column_index(self):
        """Test index with multiple columns."""
        idx = IndexInfo(
            name="idx_composite",
            columns=["first_name", "last_name"],
            unique=True,
            index_type="btree",
        )
        assert len(idx.columns) == 2
        assert idx.unique is True


class TestConstraintInfo:
    """Tests for ConstraintInfo model."""

    def test_primary_key_constraint(self):
        """Test creating a primary key constraint."""
        constraint = ConstraintInfo(
            name="pk_users", constraint_type="PRIMARY KEY", columns=["id"]
        )
        assert constraint.constraint_type == "PRIMARY KEY"
        assert constraint.columns == ["id"]

    def test_foreign_key_constraint(self):
        """Test creating a foreign key constraint."""
        constraint = ConstraintInfo(
            name="fk_orders_user",
            constraint_type="FOREIGN KEY",
            columns=["user_id"],
            referenced_table="users",
            referenced_columns=["id"],
        )
        assert constraint.constraint_type == "FOREIGN KEY"
        assert constraint.referenced_table == "users"
        assert constraint.referenced_columns == ["id"]

    def test_check_constraint(self):
        """Test creating a check constraint."""
        constraint = ConstraintInfo(
            name="chk_positive_price",
            constraint_type="CHECK",
            columns=["price"],
            definition="price > 0",
        )
        assert constraint.constraint_type == "CHECK"
        assert constraint.definition == "price > 0"


class TestRelationshipInfo:
    """Tests for RelationshipInfo model."""

    def test_basic_relationship(self):
        """Test creating a relationship."""
        rel = RelationshipInfo(
            from_table="orders",
            from_columns=["user_id"],
            to_table="users",
            to_columns=["id"],
            constraint_name="fk_orders_user",
        )
        assert rel.from_table == "orders"
        assert rel.to_table == "users"
        assert rel.from_columns == ["user_id"]
        assert rel.to_columns == ["id"]

    def test_relationship_with_actions(self):
        """Test creating a relationship with ON DELETE/UPDATE actions."""
        rel = RelationshipInfo(
            from_table="order_items",
            from_schema="public",
            from_columns=["order_id"],
            to_table="orders",
            to_schema="public",
            to_columns=["id"],
            constraint_name="fk_items_order",
            on_delete="CASCADE",
            on_update="NO ACTION",
        )
        assert rel.on_delete == "CASCADE"
        assert rel.on_update == "NO ACTION"
        assert rel.from_schema == "public"


class TestTableInfo:
    """Tests for TableInfo model."""

    @pytest.fixture
    def sample_columns(self):
        """Create sample columns for testing."""
        return [
            ColumnInfo(
                name="id", data_type="integer", nullable=False, primary_key=True
            ),
            ColumnInfo(
                name="user_id",
                data_type="integer",
                nullable=False,
                foreign_key="users.id",
            ),
            ColumnInfo(name="email", data_type="varchar(255)", nullable=False),
            ColumnInfo(name="notes", data_type="text", nullable=True),
        ]

    @pytest.fixture
    def sample_indexes(self):
        """Create sample indexes for testing."""
        return [
            IndexInfo(name="pk_orders", columns=["id"], primary=True, unique=True),
            IndexInfo(name="idx_user_id", columns=["user_id"]),
            IndexInfo(name="idx_email", columns=["email"], unique=True),
        ]

    @pytest.fixture
    def sample_constraints(self):
        """Create sample constraints for testing."""
        return [
            ConstraintInfo(
                name="pk_orders", constraint_type="PRIMARY KEY", columns=["id"]
            ),
            ConstraintInfo(
                name="fk_orders_user",
                constraint_type="FOREIGN KEY",
                columns=["user_id"],
                referenced_table="users",
                referenced_columns=["id"],
            ),
        ]

    def test_basic_creation(self):
        """Test creating a table with required fields."""
        table = TableInfo(name="users")
        assert table.name == "users"
        assert table.schema is None
        assert table.table_type == "BASE TABLE"
        assert table.columns == []
        assert table.indexes == []
        assert table.constraints == []

    def test_size_human_none(self):
        """Test size_human returns None when size_bytes is None."""
        table = TableInfo(name="users")
        assert table.size_human is None

    def test_size_human_bytes(self):
        """Test size_human formats bytes correctly."""
        table = TableInfo(name="users", size_bytes=512)
        assert table.size_human == "512.00 B"

    def test_size_human_kilobytes(self):
        """Test size_human formats kilobytes correctly."""
        table = TableInfo(name="users", size_bytes=2048)
        assert table.size_human == "2.00 KB"

    def test_size_human_megabytes(self):
        """Test size_human formats megabytes correctly."""
        table = TableInfo(name="users", size_bytes=1024 * 1024 * 50)
        assert table.size_human == "50.00 MB"

    def test_size_human_gigabytes(self):
        """Test size_human formats gigabytes correctly."""
        table = TableInfo(name="users", size_bytes=1024 * 1024 * 1024 * 2)
        assert table.size_human == "2.00 GB"

    def test_size_human_terabytes(self):
        """Test size_human formats terabytes correctly."""
        table = TableInfo(name="users", size_bytes=1024 * 1024 * 1024 * 1024 * 3)
        assert table.size_human == "3.00 TB"

    def test_size_human_petabytes(self):
        """Test size_human formats petabytes correctly."""
        table = TableInfo(name="users", size_bytes=1024 * 1024 * 1024 * 1024 * 1024 * 2)
        assert table.size_human == "2.00 PB"

    def test_total_size_bytes_none(self):
        """Test total_size_bytes returns None when size_bytes is None."""
        table = TableInfo(name="users", index_size_bytes=1024)
        assert table.total_size_bytes is None

    def test_total_size_bytes_no_index(self):
        """Test total_size_bytes with no index size."""
        table = TableInfo(name="users", size_bytes=1024 * 1024)
        assert table.total_size_bytes == 1024 * 1024

    def test_total_size_bytes_with_index(self):
        """Test total_size_bytes includes index size."""
        table = TableInfo(
            name="users",
            size_bytes=1024 * 1024 * 100,
            index_size_bytes=1024 * 1024 * 20,
        )
        assert table.total_size_bytes == 1024 * 1024 * 120

    def test_total_size_human_none(self):
        """Test total_size_human returns None when size_bytes is None."""
        table = TableInfo(name="users")
        assert table.total_size_human is None

    def test_total_size_human_with_index(self):
        """Test total_size_human formats correctly."""
        table = TableInfo(
            name="users",
            size_bytes=1024 * 1024 * 100,  # 100 MB
            index_size_bytes=1024 * 1024 * 50,  # 50 MB
        )
        assert table.total_size_human == "150.00 MB"

    def test_total_size_human_petabytes(self):
        """Test total_size_human formats petabytes correctly."""
        table = TableInfo(
            name="users",
            size_bytes=1024 * 1024 * 1024 * 1024 * 1024 * 2,  # 2 PB
        )
        assert table.total_size_human == "2.00 PB"

    def test_primary_key_columns(self, sample_columns):
        """Test primary_key_columns returns correct columns."""
        table = TableInfo(name="orders", columns=sample_columns)
        pk_cols = table.primary_key_columns
        assert pk_cols == ["id"]

    def test_primary_key_columns_empty(self):
        """Test primary_key_columns with no primary key."""
        columns = [
            ColumnInfo(name="col1", data_type="text", nullable=True),
            ColumnInfo(name="col2", data_type="text", nullable=True),
        ]
        table = TableInfo(name="temp", columns=columns)
        assert table.primary_key_columns == []

    def test_primary_key_columns_composite(self):
        """Test primary_key_columns with composite primary key."""
        columns = [
            ColumnInfo(
                name="user_id", data_type="integer", nullable=False, primary_key=True
            ),
            ColumnInfo(
                name="role_id", data_type="integer", nullable=False, primary_key=True
            ),
        ]
        table = TableInfo(name="user_roles", columns=columns)
        assert table.primary_key_columns == ["user_id", "role_id"]

    def test_foreign_key_columns(self, sample_columns):
        """Test foreign_key_columns returns correct columns."""
        table = TableInfo(name="orders", columns=sample_columns)
        fk_cols = table.foreign_key_columns
        assert fk_cols == ["user_id"]

    def test_foreign_key_columns_empty(self):
        """Test foreign_key_columns with no foreign keys."""
        columns = [
            ColumnInfo(name="id", data_type="integer", nullable=False),
        ]
        table = TableInfo(name="users", columns=columns)
        assert table.foreign_key_columns == []

    def test_foreign_key_columns_multiple(self):
        """Test foreign_key_columns with multiple foreign keys."""
        columns = [
            ColumnInfo(
                name="user_id",
                data_type="integer",
                nullable=False,
                foreign_key="users.id",
            ),
            ColumnInfo(
                name="product_id",
                data_type="integer",
                nullable=False,
                foreign_key="products.id",
            ),
        ]
        table = TableInfo(name="orders", columns=columns)
        assert table.foreign_key_columns == ["user_id", "product_id"]

    def test_column_count(self, sample_columns):
        """Test column_count returns correct count."""
        table = TableInfo(name="orders", columns=sample_columns)
        assert table.column_count == 4

    def test_column_count_empty(self):
        """Test column_count with no columns."""
        table = TableInfo(name="empty")
        assert table.column_count == 0

    def test_index_count(self, sample_indexes):
        """Test index_count returns correct count."""
        table = TableInfo(name="orders", indexes=sample_indexes)
        assert table.index_count == 3

    def test_index_count_empty(self):
        """Test index_count with no indexes."""
        table = TableInfo(name="empty")
        assert table.index_count == 0

    def test_constraint_count(self, sample_constraints):
        """Test constraint_count returns correct count."""
        table = TableInfo(name="orders", constraints=sample_constraints)
        assert table.constraint_count == 2

    def test_constraint_count_empty(self):
        """Test constraint_count with no constraints."""
        table = TableInfo(name="empty")
        assert table.constraint_count == 0

    def test_get_column_found(self, sample_columns):
        """Test get_column returns matching column."""
        table = TableInfo(name="orders", columns=sample_columns)
        col = table.get_column("email")
        assert col is not None
        assert col.name == "email"
        assert col.data_type == "varchar(255)"

    def test_get_column_not_found(self, sample_columns):
        """Test get_column returns None for non-existent column."""
        table = TableInfo(name="orders", columns=sample_columns)
        col = table.get_column("nonexistent")
        assert col is None

    def test_get_column_case_sensitive(self, sample_columns):
        """Test get_column is case-sensitive."""
        table = TableInfo(name="orders", columns=sample_columns)
        assert table.get_column("Email") is None
        assert table.get_column("email") is not None

    def test_get_index_found(self, sample_indexes):
        """Test get_index returns matching index."""
        table = TableInfo(name="orders", indexes=sample_indexes)
        idx = table.get_index("idx_email")
        assert idx is not None
        assert idx.name == "idx_email"
        assert idx.unique is True

    def test_get_index_not_found(self, sample_indexes):
        """Test get_index returns None for non-existent index."""
        table = TableInfo(name="orders", indexes=sample_indexes)
        idx = table.get_index("nonexistent")
        assert idx is None

    def test_get_constraint_found(self, sample_constraints):
        """Test get_constraint returns matching constraint."""
        table = TableInfo(name="orders", constraints=sample_constraints)
        constraint = table.get_constraint("fk_orders_user")
        assert constraint is not None
        assert constraint.name == "fk_orders_user"
        assert constraint.constraint_type == "FOREIGN KEY"

    def test_get_constraint_not_found(self, sample_constraints):
        """Test get_constraint returns None for non-existent constraint."""
        table = TableInfo(name="orders", constraints=sample_constraints)
        constraint = table.get_constraint("nonexistent")
        assert constraint is None

    def test_full_table_info(self, sample_columns, sample_indexes, sample_constraints):
        """Test creating a fully populated table info."""
        table = TableInfo(
            name="orders",
            schema="public",
            table_type="BASE TABLE",
            row_count=50000,
            size_bytes=1024 * 1024 * 100,
            index_size_bytes=1024 * 1024 * 20,
            columns=sample_columns,
            indexes=sample_indexes,
            constraints=sample_constraints,
            comment="Customer orders table",
            owner="admin",
            extra_info={"engine": "InnoDB"},
        )
        assert table.name == "orders"
        assert table.schema == "public"
        assert table.row_count == 50000
        assert table.column_count == 4
        assert table.index_count == 3
        assert table.constraint_count == 2
        assert table.size_human == "100.00 MB"
        assert table.total_size_human == "120.00 MB"
        assert table.primary_key_columns == ["id"]
        assert table.foreign_key_columns == ["user_id"]
