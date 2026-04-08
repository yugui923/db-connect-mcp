"""Module Tests for ObjectSearcher against real PostgreSQL.

Tests the search_objects feature end-to-end against the local Docker test
database (with the seeded ``categories``, ``products``, ``users``, ``orders``
tables). Verifies LIKE pattern matching, detail-level shaping, schema/table
filters, and limit/truncation behavior on real metadata.
"""

import pytest

from db_connect_mcp.core import MetadataInspector, ObjectSearcher
from db_connect_mcp.models.search import SearchDetailLevel, SearchObjectType

pytestmark = [pytest.mark.postgresql, pytest.mark.integration]


@pytest.fixture
def pg_searcher(pg_inspector: MetadataInspector) -> ObjectSearcher:
    return ObjectSearcher(pg_inspector)


class TestSearchObjectsSchemas:
    @pytest.mark.asyncio
    async def test_find_public_schema(self, pg_searcher: ObjectSearcher):
        results = await pg_searcher.search(
            pattern="public",
            object_types=[SearchObjectType.SCHEMA],
        )
        assert results.total_found >= 1
        names = {r.name for r in results.results}
        assert "public" in names

    @pytest.mark.asyncio
    async def test_schema_summary_has_counts(self, pg_searcher: ObjectSearcher):
        results = await pg_searcher.search(
            pattern="public",
            object_types=[SearchObjectType.SCHEMA],
            detail_level=SearchDetailLevel.SUMMARY,
        )
        public = next(r for r in results.results if r.name == "public")
        assert public.table_count_in_schema is not None
        assert public.table_count_in_schema >= 5


class TestSearchObjectsTables:
    @pytest.mark.asyncio
    async def test_table_substring_match(self, pg_searcher: ObjectSearcher):
        results = await pg_searcher.search(
            pattern="%user%",
            object_types=[SearchObjectType.TABLE],
            schema="public",
        )
        names = {r.name for r in results.results}
        assert "users" in names

    @pytest.mark.asyncio
    async def test_match_all_with_percent(self, pg_searcher: ObjectSearcher):
        results = await pg_searcher.search(
            pattern="%",
            object_types=[SearchObjectType.TABLE],
            schema="public",
            limit=1000,
        )
        names = {r.name for r in results.results}
        # All known seeded tables should be present
        for expected in ("categories", "products", "users", "orders"):
            assert expected in names

    @pytest.mark.asyncio
    async def test_table_summary_includes_metadata(self, pg_searcher: ObjectSearcher):
        results = await pg_searcher.search(
            pattern="users",
            object_types=[SearchObjectType.TABLE],
            schema="public",
            detail_level=SearchDetailLevel.SUMMARY,
        )
        users = next(r for r in results.results if r.name == "users")
        assert users.table_type == "BASE TABLE"
        # row_count is only populated when the adapter enrichment runs and
        # PG ANALYZE has actually been run; just sanity-check the type if set.
        if users.row_count is not None:
            assert isinstance(users.row_count, int)


class TestSearchObjectsColumns:
    @pytest.mark.asyncio
    async def test_find_user_id_columns(self, pg_searcher: ObjectSearcher):
        results = await pg_searcher.search(
            pattern="user_id",
            object_types=[SearchObjectType.COLUMN],
            schema="public",
        )
        # user_id appears in users (PK) and orders (FK), at minimum
        assert results.total_found >= 2
        tables_with_user_id = {r.table for r in results.results}
        assert "users" in tables_with_user_id
        assert "orders" in tables_with_user_id

    @pytest.mark.asyncio
    async def test_column_summary_marks_primary_key(self, pg_searcher: ObjectSearcher):
        results = await pg_searcher.search(
            pattern="user_id",
            object_types=[SearchObjectType.COLUMN],
            schema="public",
            table="users",
            detail_level=SearchDetailLevel.SUMMARY,
        )
        assert results.total_found == 1
        col = results.results[0]
        assert col.table == "users"
        assert col.primary_key is True
        # Detail level summary populates data_type
        assert col.data_type is not None

    @pytest.mark.asyncio
    async def test_column_full_includes_type_details(self, pg_searcher: ObjectSearcher):
        results = await pg_searcher.search(
            pattern="email",
            object_types=[SearchObjectType.COLUMN],
            schema="public",
            table="users",
            detail_level=SearchDetailLevel.FULL,
        )
        assert results.total_found == 1
        col = results.results[0]
        assert col.data_type is not None
        # comment may or may not be set depending on the test fixture seed,
        # but the field exists and should be either None or a string.
        assert col.comment is None or isinstance(col.comment, str)


class TestSearchObjectsIndexes:
    @pytest.mark.asyncio
    async def test_index_search_returns_known_indexes(
        self, pg_searcher: ObjectSearcher
    ):
        # The seeded users table has indexes; match all to find them.
        results = await pg_searcher.search(
            pattern="%",
            object_types=[SearchObjectType.INDEX],
            schema="public",
            table="users",
        )
        # At least the primary key index should exist
        assert results.total_found >= 1
        for r in results.results:
            assert r.table == "users"
            assert r.columns is not None


class TestSearchObjectsLimits:
    @pytest.mark.asyncio
    async def test_limit_truncates_and_reports(self, pg_searcher: ObjectSearcher):
        results = await pg_searcher.search(
            pattern="%",
            object_types=[SearchObjectType.COLUMN],
            schema="public",
            limit=2,
        )
        assert results.returned == 2
        assert results.total_found > 2
        assert results.truncated is True

    @pytest.mark.asyncio
    async def test_invalid_limit_rejected(self, pg_searcher: ObjectSearcher):
        with pytest.raises(ValueError):
            await pg_searcher.search(pattern="%", limit=0)
        with pytest.raises(ValueError):
            await pg_searcher.search(pattern="%", limit=10000)

    @pytest.mark.asyncio
    async def test_empty_pattern_rejected(self, pg_searcher: ObjectSearcher):
        with pytest.raises(ValueError):
            await pg_searcher.search(pattern="")


class TestSearchObjectsDetailLevels:
    @pytest.mark.asyncio
    async def test_names_level_excludes_metadata(self, pg_searcher: ObjectSearcher):
        results = await pg_searcher.search(
            pattern="users",
            object_types=[SearchObjectType.TABLE],
            schema="public",
            detail_level=SearchDetailLevel.NAMES,
        )
        users = next(r for r in results.results if r.name == "users")
        # NAMES level should leave summary fields untouched
        assert users.row_count is None
        assert users.table_type is None
        assert users.comment is None

    @pytest.mark.asyncio
    async def test_exclude_none_dump_strips_empty_fields(
        self, pg_searcher: ObjectSearcher
    ):
        """Verify the JSON serialization (used by the MCP handler) drops Nones."""
        results = await pg_searcher.search(
            pattern="users",
            object_types=[SearchObjectType.TABLE],
            schema="public",
            detail_level=SearchDetailLevel.NAMES,
        )
        dumped = results.model_dump(mode="json", exclude_none=True)
        users_item = next(r for r in dumped["results"] if r["name"] == "users")
        # NAMES level → only object_type, name, schema should remain
        assert "row_count" not in users_item
        assert "table_type" not in users_item
        assert "comment" not in users_item
        assert users_item["object_type"] == "table"
        assert users_item["schema"] == "public"
