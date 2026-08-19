"""Tests for MCP database resources and cursor pagination."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import Resource

from db_connect_mcp.core.resources import (
    DatabaseResourceCatalog,
    paginate_resources,
)
from db_connect_mcp.models.capabilities import DatabaseCapabilities
from db_connect_mcp.models.config import DatabaseConfig
from db_connect_mcp.models.database import SchemaInfo
from db_connect_mcp.models.table import TableInfo


def _resource(uri: str) -> Resource:
    return Resource(uri=uri, name=uri, mime_type="application/json")


class TestResourcePagination:
    """Cursor pages remain ordered and tied to one catalog snapshot."""

    def test_pages_cover_snapshot_without_duplicates(self) -> None:
        resources = [
            _resource(f"db-connect://table/public/table-{index}") for index in range(5)
        ]

        first, first_cursor = paginate_resources(resources, None, page_size=2)
        assert [item.uri for item in first] == [item.uri for item in resources[:2]]
        assert first_cursor is not None

        second, second_cursor = paginate_resources(resources, first_cursor, page_size=2)
        assert [item.uri for item in second] == [item.uri for item in resources[2:4]]
        assert second_cursor is not None

        third, next_cursor = paginate_resources(resources, second_cursor, page_size=2)
        assert [item.uri for item in third] == [resources[4].uri]
        assert next_cursor is None

    def test_invalid_cursor_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid resource pagination cursor"):
            paginate_resources([_resource("db-connect://database")], "not-a-cursor")

    def test_cursor_is_rejected_when_catalog_changes(self) -> None:
        resources = [
            _resource("db-connect://database"),
            _resource("db-connect://schema/a"),
        ]
        _, cursor = paginate_resources(resources, None, page_size=1)
        assert cursor is not None

        with pytest.raises(ValueError, match="stale"):
            paginate_resources(
                [*resources, _resource("db-connect://schema/b")],
                cursor,
                page_size=1,
            )


class TestDatabaseResourceCatalog:
    """Resource catalog exposes sanitized, deterministic database metadata."""

    @pytest.fixture
    def catalog(self) -> DatabaseResourceCatalog:
        config = DatabaseConfig(url="postgresql://reader:secret@localhost:5432/example")
        connection = MagicMock()
        connection.get_version = AsyncMock(return_value="PostgreSQL 18")
        adapter = MagicMock()
        adapter.capabilities = DatabaseCapabilities()
        inspector = MagicMock()
        inspector.get_schemas = AsyncMock(
            return_value=[
                SchemaInfo(name="zeta", table_count=1, view_count=0),
                SchemaInfo(name="sales team", table_count=1, view_count=0),
            ]
        )

        async def get_tables(
            schema: str, include_views: bool = True
        ) -> list[TableInfo]:
            assert include_views is True
            return [TableInfo(name=f"{schema} orders", schema=schema)]

        inspector.get_tables = AsyncMock(side_effect=get_tables)
        inspector.describe_table = AsyncMock(
            return_value=TableInfo(name="sales team orders", schema="sales team")
        )
        return DatabaseResourceCatalog(config, connection, adapter, inspector)

    @pytest.mark.asyncio
    async def test_list_is_uri_sorted_and_encodes_identifiers(
        self, catalog: DatabaseResourceCatalog
    ) -> None:
        resources = await catalog.list()
        uris = [resource.uri for resource in resources]

        assert uris == sorted(uris)
        assert "db-connect://database" in uris
        assert "db-connect://schema/sales%20team" in uris
        assert "db-connect://table/sales%20team/sales%20team%20orders" in uris

    @pytest.mark.asyncio
    async def test_read_database_hides_credentials(
        self, catalog: DatabaseResourceCatalog
    ) -> None:
        payload = await catalog.read("db-connect://database")

        assert payload["version"] == "PostgreSQL 18"
        assert payload["connection_url"].startswith("<credentials>@")
        assert "secret" not in payload["connection_url"]

    @pytest.mark.asyncio
    async def test_read_schema_and_table_resources(
        self, catalog: DatabaseResourceCatalog
    ) -> None:
        schema = await catalog.read("db-connect://schema/sales%20team")
        table = await catalog.read(
            "db-connect://table/sales%20team/sales%20team%20orders"
        )

        assert schema["name"] == "sales team"
        assert table["name"] == "sales team orders"

    @pytest.mark.asyncio
    async def test_unknown_resource_is_rejected(
        self, catalog: DatabaseResourceCatalog
    ) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            await catalog.read("https://example.com/database")
