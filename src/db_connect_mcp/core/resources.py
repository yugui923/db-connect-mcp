"""Stable, paginated MCP resources for database context."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote, urlsplit

from mcp.types import Resource

from db_connect_mcp.models.database import DatabaseInfo

if TYPE_CHECKING:
    from db_connect_mcp.adapters.base import BaseAdapter
    from db_connect_mcp.core.connection import DatabaseConnection
    from db_connect_mcp.core.inspector import MetadataInspector
    from db_connect_mcp.models.config import DatabaseConfig

RESOURCE_SCHEME = "db-connect"
RESOURCE_PAGE_SIZE = 100


def _catalog_fingerprint(resources: Sequence[Resource]) -> str:
    """Return a short fingerprint for one ordered resource snapshot."""
    joined_uris = "\n".join(resource.uri for resource in resources)
    return hashlib.sha256(joined_uris.encode()).hexdigest()[:16]


def _encode_cursor(offset: int, fingerprint: str) -> str:
    """Encode pagination state into an opaque URL-safe cursor."""
    payload = json.dumps(
        {"fingerprint": fingerprint, "offset": offset, "version": 1},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, str]:
    """Decode and validate an opaque resource cursor."""
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError
        offset = payload["offset"]
        fingerprint = payload["fingerprint"]
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < 0
            or not isinstance(fingerprint, str)
            or not fingerprint
        ):
            raise ValueError
    except (
        binascii.Error,
        KeyError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("Invalid resource pagination cursor") from exc
    return offset, fingerprint


def paginate_resources(
    resources: Sequence[Resource],
    cursor: str | None,
    *,
    page_size: int = RESOURCE_PAGE_SIZE,
) -> tuple[list[Resource], str | None]:
    """Return one deterministic page and a cursor tied to this snapshot."""
    if page_size < 1:
        raise ValueError("Resource page size must be positive")

    fingerprint = _catalog_fingerprint(resources)
    offset = 0
    if cursor is not None:
        offset, cursor_fingerprint = _decode_cursor(cursor)
        if cursor_fingerprint != fingerprint:
            raise ValueError(
                "Resource pagination cursor is stale; restart from the first page"
            )
        if offset > len(resources):
            raise ValueError("Resource pagination cursor is out of range")

    end = min(offset + page_size, len(resources))
    next_cursor = _encode_cursor(end, fingerprint) if end < len(resources) else None
    return list(resources[offset:end]), next_cursor


def _schema_uri(schema: str) -> str:
    return f"{RESOURCE_SCHEME}://schema/{quote(schema, safe='')}"


def _table_uri(schema: str, table: str) -> str:
    return f"{RESOURCE_SCHEME}://table/{quote(schema, safe='')}/{quote(table, safe='')}"


class DatabaseResourceCatalog:
    """Expose database metadata as stable, machine-readable MCP resources."""

    def __init__(
        self,
        config: DatabaseConfig,
        connection: DatabaseConnection,
        adapter: BaseAdapter,
        inspector: MetadataInspector,
    ) -> None:
        self.config = config
        self.connection = connection
        self.adapter = adapter
        self.inspector = inspector

    async def get_database_info(self) -> DatabaseInfo:
        """Build the sanitized database overview shared by tools and resources."""
        version = await self.connection.get_version()
        url_parts = self.config.url.split("@")
        sanitized_url = (
            f"<credentials>@{url_parts[-1]}" if len(url_parts) > 1 else self.config.url
        )
        return DatabaseInfo(
            name=self.config.url.split("/")[-1],
            dialect=self.config.dialect,
            version=version,
            size_bytes=None,
            schema_count=None,
            table_count=None,
            capabilities=self.adapter.capabilities,
            server_encoding=None,
            collation=None,
            connection_url=sanitized_url,
            read_only=self.config.read_only,
        )

    async def list(self) -> list[Resource]:
        """List database, schema, and table resources in stable URI order."""
        resources = [
            Resource(
                uri=f"{RESOURCE_SCHEME}://database",
                name="database",
                title="Database Overview",
                description="Dialect, version, capabilities, and connection metadata",
                mime_type="application/json",
            )
        ]

        schemas = await self.inspector.get_schemas()
        for schema in schemas:
            resources.append(
                Resource(
                    uri=_schema_uri(schema.name),
                    name=f"schema:{schema.name}",
                    title=f"Schema: {schema.name}",
                    description=(
                        f"Schema metadata ({schema.table_count or 0} tables, "
                        f"{schema.view_count or 0} views)"
                    ),
                    mime_type="application/json",
                )
            )
            tables = await self.inspector.get_tables(schema.name, include_views=True)
            for table in tables:
                resources.append(
                    Resource(
                        uri=_table_uri(schema.name, table.name),
                        name=f"table:{schema.name}.{table.name}",
                        title=f"{schema.name}.{table.name}",
                        description=(
                            f"{table.table_type} metadata including columns, "
                            "indexes, and constraints"
                        ),
                        mime_type="application/json",
                    )
                )

        return sorted(resources, key=lambda resource: resource.uri)

    async def read(self, uri: str) -> dict[str, Any]:
        """Resolve a DB Connect resource URI to JSON-serializable metadata."""
        parsed = urlsplit(uri)
        if parsed.scheme != RESOURCE_SCHEME or parsed.query or parsed.fragment:
            raise ValueError(f"Unsupported database resource URI: {uri}")

        segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
        if parsed.netloc == "database" and not segments:
            info = await self.get_database_info()
            return info.model_dump(mode="json")

        if parsed.netloc == "schema" and len(segments) == 1:
            schema_name = segments[0]
            schemas = await self.inspector.get_schemas()
            schema = next((item for item in schemas if item.name == schema_name), None)
            if schema is None:
                raise ValueError(f"Unknown schema resource: {schema_name}")
            return schema.model_dump(mode="json")

        if parsed.netloc == "table" and len(segments) == 2:
            schema_name, table_name = segments
            table = await self.inspector.describe_table(table_name, schema_name)
            return table.model_dump(mode="json")

        raise ValueError(f"Unsupported database resource URI: {uri}")
