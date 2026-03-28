"""Unit tests for MetadataInspector internal methods."""

import pytest

from db_connect_mcp.core.inspector import MetadataInspector
from db_connect_mcp.models.table import IndexInfo


class TestIndexFromSA:
    """Test _index_from_sa handling of expression-based indexes."""

    @pytest.fixture
    def inspector(self):
        """Create an inspector instance (adapter/connection not needed for _index_from_sa)."""
        # _index_from_sa is a pure data-conversion method — no DB access needed
        return MetadataInspector.__new__(MetadataInspector)

    def test_normal_index(self, inspector: MetadataInspector):
        """Regular column index should pass column names through."""
        idx_data = {
            "name": "idx_name_email",
            "column_names": ["name", "email"],
            "unique": False,
            "type": "btree",
        }
        result = inspector._index_from_sa(idx_data)
        assert isinstance(result, IndexInfo)
        assert result.name == "idx_name_email"
        assert result.columns == ["name", "email"]
        assert result.unique is False
        assert result.index_type == "btree"

    def test_expression_index_all_expressions(self, inspector: MetadataInspector):
        """Fully expression-based index should use expressions for None columns."""
        idx_data = {
            "name": "idx_lower_name",
            "column_names": [None],
            "expressions": ["lower(name)"],
            "unique": False,
        }
        result = inspector._index_from_sa(idx_data)
        assert result.columns == ["lower(name)"]

    def test_expression_index_mixed(self, inspector: MetadataInspector):
        """Mixed index (columns + expressions) should substitute only None entries."""
        idx_data = {
            "name": "idx_mixed",
            "column_names": ["id", None],
            "expressions": ["id", "lower(email)"],
            "unique": False,
        }
        result = inspector._index_from_sa(idx_data)
        assert result.columns == ["id", "lower(email)"]

    def test_expression_index_multiple_expressions(self, inspector: MetadataInspector):
        """Index with multiple expressions should substitute all None entries."""
        idx_data = {
            "name": "idx_multi_expr",
            "column_names": [None, None, "status"],
            "expressions": ["lower(name)", "upper(city)", "status"],
            "unique": True,
        }
        result = inspector._index_from_sa(idx_data)
        assert result.columns == ["lower(name)", "upper(city)", "status"]
        assert result.unique is True

    def test_no_expressions_key(self, inspector: MetadataInspector):
        """Index data without expressions key should work (older SQLAlchemy)."""
        idx_data = {
            "name": "idx_simple",
            "column_names": ["name"],
            "unique": False,
        }
        result = inspector._index_from_sa(idx_data)
        assert result.columns == ["name"]

    def test_empty_expressions_with_none_columns(self, inspector: MetadataInspector):
        """Empty expressions list with None in columns should filter out Nones."""
        idx_data = {
            "name": "idx_weird",
            "column_names": ["name", None],
            "expressions": [],
            "unique": False,
        }
        result = inspector._index_from_sa(idx_data)
        assert result.columns == ["name"]

    def test_unique_expression_index(self, inspector: MetadataInspector):
        """Unique expression index should preserve the unique flag."""
        idx_data = {
            "name": "idx_unique_lower",
            "column_names": [None],
            "expressions": ["lower(email)"],
            "unique": True,
        }
        result = inspector._index_from_sa(idx_data)
        assert result.columns == ["lower(email)"]
        assert result.unique is True

    def test_index_type_preserved(self, inspector: MetadataInspector):
        """Index type should be passed through."""
        idx_data = {
            "name": "idx_hash",
            "column_names": ["id"],
            "unique": False,
            "type": "hash",
        }
        result = inspector._index_from_sa(idx_data)
        assert result.index_type == "hash"

    def test_index_type_missing(self, inspector: MetadataInspector):
        """Missing index type should default to None."""
        idx_data = {
            "name": "idx_no_type",
            "column_names": ["id"],
            "unique": False,
        }
        result = inspector._index_from_sa(idx_data)
        assert result.index_type is None
