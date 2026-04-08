"""Unit tests for the search_objects core logic.

These tests do not touch a real database — they exercise:

  * ``like_to_regex`` pattern conversion
  * ``ObjectSearcher`` orchestration with a stub inspector
  * Detail-level shaping of result fields
  * Limit / truncation / early-termination handling
"""

from typing import Optional
from unittest.mock import AsyncMock

import pytest

from db_connect_mcp.core.search import (
    MAX_TABLES_TO_DESCRIBE,
    ObjectSearcher,
    _normalize_object_types,
    _validate_limit,
    like_to_regex,
)
from db_connect_mcp.models.database import SchemaInfo
from db_connect_mcp.models.search import (
    DEFAULT_SEARCH_OBJECT_TYPES,
    SearchDetailLevel,
    SearchObjectType,
)
from db_connect_mcp.models.table import ColumnInfo, IndexInfo, TableInfo


# ============================ like_to_regex ============================


class TestLikeToRegex:
    def test_percent_matches_anything(self):
        rx = like_to_regex("%")
        assert rx.match("anything")
        assert rx.match("")
        assert rx.match("with spaces and 123")

    def test_percent_substring(self):
        rx = like_to_regex("%user%")
        assert rx.match("users")
        assert rx.match("super_user")
        assert rx.match("user")
        assert not rx.match("orders")

    def test_underscore_single_char(self):
        rx = like_to_regex("a_c")
        assert rx.match("abc")
        assert rx.match("aXc")
        assert not rx.match("ac")
        assert not rx.match("abbc")

    def test_case_insensitive(self):
        rx = like_to_regex("USER%")
        assert rx.match("users")
        assert rx.match("UserName")

    def test_escapes_regex_metacharacters(self):
        # Dot and parens are regex metas — they must be escaped so they're
        # treated as literals.
        rx = like_to_regex("a.b(c)")
        assert rx.match("a.b(c)")
        assert not rx.match("aXbXcX")

    def test_anchored(self):
        # Without anchors, "user" would match "users". With anchors, it should
        # only match the exact string.
        rx = like_to_regex("user")
        assert rx.match("user")
        assert not rx.match("users")
        assert not rx.match("xuser")

    def test_empty_pattern_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            like_to_regex("")

    def test_combined_wildcards(self):
        rx = like_to_regex("u_er%")
        assert rx.match("user")
        assert rx.match("user_table")
        assert rx.match("uXer_anything")
        assert not rx.match("usrs")


# ============================ helpers ============================


class TestNormalizeObjectTypes:
    def test_none_returns_default(self):
        assert _normalize_object_types(None) == DEFAULT_SEARCH_OBJECT_TYPES

    def test_empty_returns_default(self):
        assert _normalize_object_types([]) == DEFAULT_SEARCH_OBJECT_TYPES

    def test_dedup_preserves_order(self):
        result = _normalize_object_types(
            [
                SearchObjectType.TABLE,
                SearchObjectType.COLUMN,
                SearchObjectType.TABLE,
            ]
        )
        assert result == [SearchObjectType.TABLE, SearchObjectType.COLUMN]


class TestValidateLimit:
    def test_in_range(self):
        assert _validate_limit(1) == 1
        assert _validate_limit(100) == 100
        assert _validate_limit(1000) == 1000

    def test_below_minimum(self):
        with pytest.raises(ValueError):
            _validate_limit(0)

    def test_above_maximum(self):
        with pytest.raises(ValueError):
            _validate_limit(1001)


# ============================ ObjectSearcher ============================


def _make_schema(name: str, *, comment: Optional[str] = None) -> SchemaInfo:
    return SchemaInfo(name=name, table_count=3, view_count=1, comment=comment)


def _make_table(
    name: str,
    *,
    schema: str = "public",
    table_type: str = "BASE TABLE",
    row_count: Optional[int] = 42,
    comment: Optional[str] = None,
    columns: Optional[list[ColumnInfo]] = None,
    indexes: Optional[list[IndexInfo]] = None,
) -> TableInfo:
    info = TableInfo(
        name=name,
        schema=schema,
        table_type=table_type,
        row_count=row_count,
        comment=comment,
    )
    if columns:
        info.columns = columns
    if indexes:
        info.indexes = indexes
    return info


def _make_column(
    name: str,
    *,
    data_type: str = "integer",
    nullable: bool = True,
    primary_key: bool = False,
    unique: bool = False,
    indexed: bool = False,
    comment: Optional[str] = None,
    default: Optional[str] = None,
) -> ColumnInfo:
    return ColumnInfo(
        name=name,
        data_type=data_type,
        nullable=nullable,
        primary_key=primary_key,
        unique=unique,
        indexed=indexed,
        comment=comment,
        default=default,
    )


def _make_index(
    name: str,
    *,
    columns: Optional[list[str]] = None,
    unique: bool = False,
    index_type: str = "btree",
    comment: Optional[str] = None,
) -> IndexInfo:
    return IndexInfo(
        name=name,
        columns=columns or ["id"],
        unique=unique,
        index_type=index_type,
        comment=comment,
    )


def _make_inspector_stub(
    schemas: list[SchemaInfo],
    tables_by_schema: dict[str, list[TableInfo]],
    described: dict[tuple[str, str], TableInfo],
) -> AsyncMock:
    """Create an AsyncMock inspector with predictable, scriptable responses."""
    inspector = AsyncMock()
    inspector.get_schemas = AsyncMock(return_value=schemas)

    async def get_tables(schema, include_views=True):
        return list(tables_by_schema.get(schema, []))

    async def describe_table(table_name, schema):
        key = (schema, table_name)
        if key in described:
            return described[key]
        # Default to a bare TableInfo so the searcher doesn't blow up
        return TableInfo(name=table_name, schema=schema)

    inspector.get_tables = AsyncMock(side_effect=get_tables)
    inspector.describe_table = AsyncMock(side_effect=describe_table)
    return inspector


@pytest.mark.asyncio
class TestObjectSearcher:
    async def test_schema_search_names_only(self):
        inspector = _make_inspector_stub(
            schemas=[_make_schema("public"), _make_schema("analytics")],
            tables_by_schema={},
            described={},
        )
        searcher = ObjectSearcher(inspector)

        results = await searcher.search(
            pattern="ana%",
            object_types=[SearchObjectType.SCHEMA],
            detail_level=SearchDetailLevel.NAMES,
        )

        assert results.returned == 1
        assert results.total_found == 1
        assert results.results[0].object_type == "schema"
        assert results.results[0].name == "analytics"
        # NAMES detail level → no metadata fields populated
        assert results.results[0].table_count_in_schema is None
        assert results.results[0].comment is None

    async def test_schema_search_summary_includes_counts(self):
        inspector = _make_inspector_stub(
            schemas=[_make_schema("public", comment="Public schema")],
            tables_by_schema={},
            described={},
        )
        searcher = ObjectSearcher(inspector)

        results = await searcher.search(
            pattern="public",
            object_types=[SearchObjectType.SCHEMA],
            detail_level=SearchDetailLevel.SUMMARY,
        )
        assert results.results[0].table_count_in_schema == 3
        assert results.results[0].view_count_in_schema == 1
        # comment is FULL only
        assert results.results[0].comment is None

    async def test_schema_search_full_includes_comment(self):
        inspector = _make_inspector_stub(
            schemas=[_make_schema("public", comment="Public schema")],
            tables_by_schema={},
            described={},
        )
        searcher = ObjectSearcher(inspector)
        results = await searcher.search(
            pattern="public",
            object_types=[SearchObjectType.SCHEMA],
            detail_level=SearchDetailLevel.FULL,
        )
        assert results.results[0].comment == "Public schema"

    async def test_table_and_view_distinction(self):
        tables = [
            _make_table("users", table_type="BASE TABLE"),
            _make_table("v_active_users", table_type="VIEW"),
        ]
        inspector = _make_inspector_stub(
            schemas=[_make_schema("public")],
            tables_by_schema={"public": tables},
            described={},
        )
        searcher = ObjectSearcher(inspector)

        # Only views
        results = await searcher.search(
            pattern="%user%",
            object_types=[SearchObjectType.VIEW],
        )
        assert results.total_found == 1
        assert results.results[0].name == "v_active_users"
        assert results.results[0].object_type == "view"

        # Only tables
        results = await searcher.search(
            pattern="%user%",
            object_types=[SearchObjectType.TABLE],
        )
        assert results.total_found == 1
        assert results.results[0].name == "users"
        assert results.results[0].object_type == "table"

    async def test_column_search_with_describe(self):
        described = {
            ("public", "users"): _make_table(
                "users",
                columns=[
                    _make_column("user_id", primary_key=True, indexed=True),
                    _make_column("email", data_type="varchar", unique=True),
                    _make_column("created_at", data_type="timestamp"),
                ],
            )
        }
        inspector = _make_inspector_stub(
            schemas=[_make_schema("public")],
            tables_by_schema={"public": [_make_table("users")]},
            described=described,
        )
        searcher = ObjectSearcher(inspector)

        results = await searcher.search(
            pattern="%id%",
            object_types=[SearchObjectType.COLUMN],
            detail_level=SearchDetailLevel.SUMMARY,
        )
        assert results.total_found == 1
        item = results.results[0]
        assert item.object_type == "column"
        assert item.name == "user_id"
        assert item.schema == "public"
        assert item.table == "users"
        assert item.primary_key is True
        assert item.indexed is True

    async def test_index_search(self):
        described = {
            ("public", "users"): _make_table(
                "users",
                indexes=[
                    _make_index("idx_users_email", columns=["email"], unique=True),
                    _make_index("idx_users_created", columns=["created_at"]),
                ],
            )
        }
        inspector = _make_inspector_stub(
            schemas=[_make_schema("public")],
            tables_by_schema={"public": [_make_table("users")]},
            described=described,
        )
        searcher = ObjectSearcher(inspector)

        results = await searcher.search(
            pattern="idx_users%",
            object_types=[SearchObjectType.INDEX],
            detail_level=SearchDetailLevel.SUMMARY,
        )
        assert results.total_found == 2
        names = {r.name for r in results.results}
        assert names == {"idx_users_email", "idx_users_created"}
        email_idx = next(r for r in results.results if r.name == "idx_users_email")
        assert email_idx.unique is True
        assert email_idx.columns == ["email"]
        assert email_idx.table == "users"

    async def test_schema_filter_avoids_other_schemas(self):
        inspector = _make_inspector_stub(
            schemas=[_make_schema("public"), _make_schema("analytics")],
            tables_by_schema={
                "public": [_make_table("users", schema="public")],
                "analytics": [_make_table("events", schema="analytics")],
            },
            described={},
        )
        searcher = ObjectSearcher(inspector)

        results = await searcher.search(
            pattern="%",
            object_types=[SearchObjectType.TABLE],
            schema="analytics",
        )
        # When schema is given, get_schemas is not used to enumerate targets
        inspector.get_schemas.assert_not_called()
        assert results.total_found == 1
        assert results.results[0].name == "events"

    async def test_table_filter_restricts_describe(self):
        described = {
            ("public", "users"): _make_table(
                "users",
                columns=[_make_column("id"), _make_column("email")],
            ),
            ("public", "orders"): _make_table(
                "orders",
                columns=[_make_column("id"), _make_column("user_id")],
            ),
        }
        inspector = _make_inspector_stub(
            schemas=[_make_schema("public")],
            tables_by_schema={
                "public": [_make_table("users"), _make_table("orders")],
            },
            described=described,
        )
        searcher = ObjectSearcher(inspector)

        results = await searcher.search(
            pattern="%id%",
            object_types=[SearchObjectType.COLUMN],
            schema="public",
            table="orders",
        )
        # describe_table called only for orders, not users
        called_tables = {
            call.args[0] if call.args else call.kwargs.get("table_name")
            for call in inspector.describe_table.call_args_list
        }
        assert called_tables == {"orders"}
        # Both id and user_id matched in orders
        assert results.total_found == 2

    async def test_limit_truncation(self):
        cols = [_make_column(f"col_{i}") for i in range(10)]
        described = {("public", "t"): _make_table("t", columns=cols)}
        inspector = _make_inspector_stub(
            schemas=[_make_schema("public")],
            tables_by_schema={"public": [_make_table("t")]},
            described=described,
        )
        searcher = ObjectSearcher(inspector)

        results = await searcher.search(
            pattern="col%",
            object_types=[SearchObjectType.COLUMN],
            limit=3,
        )
        assert results.total_found == 10
        assert results.returned == 3
        assert results.truncated is True
        assert results.note is not None
        assert "10" in results.note

    async def test_no_match(self):
        inspector = _make_inspector_stub(
            schemas=[_make_schema("public")],
            tables_by_schema={"public": []},
            described={},
        )
        searcher = ObjectSearcher(inspector)
        results = await searcher.search(pattern="nothing%")
        assert results.total_found == 0
        assert results.returned == 0
        assert results.truncated is False
        assert results.early_termination is False

    async def test_early_termination_on_table_cap(self):
        # Create more tables than the cap and request column search.
        many_tables = [
            _make_table(f"t_{i}", schema="public")
            for i in range(MAX_TABLES_TO_DESCRIBE + 5)
        ]
        described = {
            ("public", t.name): _make_table(
                t.name, columns=[_make_column("matching_col")]
            )
            for t in many_tables
        }
        inspector = _make_inspector_stub(
            schemas=[_make_schema("public")],
            tables_by_schema={"public": many_tables},
            described=described,
        )
        searcher = ObjectSearcher(inspector)

        results = await searcher.search(
            pattern="matching_col",
            object_types=[SearchObjectType.COLUMN],
            limit=1000,
        )
        assert results.early_termination is True
        # We described exactly MAX_TABLES_TO_DESCRIBE tables
        assert inspector.describe_table.call_count == MAX_TABLES_TO_DESCRIBE
        assert results.total_found == MAX_TABLES_TO_DESCRIBE
        assert results.note is not None
        assert "cap" in results.note.lower()

    async def test_full_detail_includes_column_extras(self):
        described = {
            ("public", "t"): _make_table(
                "t",
                columns=[
                    _make_column(
                        "email",
                        data_type="varchar",
                        comment="User email",
                        default="''",
                    )
                ],
            )
        }
        inspector = _make_inspector_stub(
            schemas=[_make_schema("public")],
            tables_by_schema={"public": [_make_table("t")]},
            described=described,
        )
        searcher = ObjectSearcher(inspector)

        results = await searcher.search(
            pattern="email",
            object_types=[SearchObjectType.COLUMN],
            detail_level=SearchDetailLevel.FULL,
        )
        item = results.results[0]
        assert item.comment == "User email"
        assert item.default == "''"
        assert item.data_type == "varchar"

    async def test_default_object_types_searches_everything(self):
        # Schema, table, column, and index all match the same `user%` pattern,
        # so we expect at least one result of each type to come back.
        described_table = _make_table(
            "users",
            schema="user_data",
            columns=[_make_column("user_id")],
            indexes=[_make_index("user_idx", columns=["user_id"])],
        )
        inspector = _make_inspector_stub(
            schemas=[_make_schema("user_data")],
            tables_by_schema={
                "user_data": [_make_table("users", schema="user_data")]
            },
            described={("user_data", "users"): described_table},
        )
        searcher = ObjectSearcher(inspector)

        results = await searcher.search(pattern="user%")
        types = {r.object_type for r in results.results}
        assert "schema" in types
        assert "table" in types
        assert "column" in types
        assert "index" in types
