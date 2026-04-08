"""Cross-cutting metadata search across schemas, tables, columns, and indexes.

This module implements the search_objects MCP tool: a single, token-efficient
entry point for discovering database objects by name pattern. It is inspired by
bytebase/dbhub's ``search_objects`` tool and supports progressive disclosure
through three detail levels (``names``, ``summary``, ``full``).

The implementation deliberately reuses :class:`MetadataInspector` rather than
issuing dialect-specific ``information_schema`` queries. This keeps the change
scoped, automatically supports all configured adapters (PostgreSQL, MySQL,
ClickHouse), and benefits from the inspector's existing system-schema
filtering and adapter-driven enrichment.
"""

import logging
import re
from typing import TYPE_CHECKING, Optional

from db_connect_mcp.models.search import (
    DEFAULT_SEARCH_OBJECT_TYPES,
    SearchDetailLevel,
    SearchObjectType,
    SearchResultItem,
    SearchResults,
)
from db_connect_mcp.models.table import ColumnInfo, IndexInfo, TableInfo

if TYPE_CHECKING:
    from db_connect_mcp.core.inspector import MetadataInspector
    from db_connect_mcp.models.database import SchemaInfo

logger = logging.getLogger(__name__)


# Hard cap on tables we will ``describe_table`` in a single search call.
# describe_table is the most expensive inspector method (columns + indexes +
# FKs + constraints + adapter enrichment). When column or index search is
# requested, we walk all candidate tables; this cap is the safety net for
# users who don't pass ``schema``/``table`` filters.
MAX_TABLES_TO_DESCRIBE = 200

# Lower bound and upper bound for the result limit, matching dbhub.
MIN_LIMIT = 1
MAX_LIMIT = 1000


def like_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a SQL LIKE pattern to a case-insensitive anchored regex.

    - ``%`` matches any (possibly empty) sequence of characters.
    - ``_`` matches exactly one character.
    - All other characters are matched literally (regex metacharacters are
      escaped).
    - Escaping LIKE specials with backslash is not supported in v1.

    Raises:
        ValueError: If pattern is empty. Use ``%`` to match all objects.
    """
    if not pattern:
        raise ValueError("pattern must not be empty (use '%' to match all objects)")

    out: list[str] = []
    for ch in pattern:
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def _normalize_object_types(
    object_types: Optional[list[SearchObjectType]],
) -> list[SearchObjectType]:
    """Return a de-duplicated, defaulted object_types list."""
    if not object_types:
        return list(DEFAULT_SEARCH_OBJECT_TYPES)
    seen: set[SearchObjectType] = set()
    out: list[SearchObjectType] = []
    for t in object_types:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _validate_limit(limit: int) -> int:
    """Clamp/validate the limit to ``[MIN_LIMIT, MAX_LIMIT]``."""
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ValueError(
            f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}, got {limit}"
        )
    return limit


class ObjectSearcher:
    """Search database objects by name pattern with progressive disclosure.

    The searcher is a thin orchestrator over :class:`MetadataInspector`. It
    fetches schemas/tables once per call and filters the results in Python.
    Column and index searches additionally call ``describe_table`` for each
    candidate table, capped at :data:`MAX_TABLES_TO_DESCRIBE` per call.
    """

    def __init__(self, inspector: "MetadataInspector") -> None:
        self.inspector = inspector

    async def search(
        self,
        pattern: str,
        object_types: Optional[list[SearchObjectType]] = None,
        detail_level: SearchDetailLevel = SearchDetailLevel.SUMMARY,
        schema: Optional[str] = None,
        table: Optional[str] = None,
        limit: int = 100,
    ) -> SearchResults:
        """Run a search and return matched objects.

        Args:
            pattern: SQL LIKE pattern. ``%`` matches any sequence; ``_``
                matches one character.
            object_types: Object types to search. Defaults to all 5.
            detail_level: Verbosity. ``names`` is most token-efficient.
            schema: Restrict to a specific schema. Strongly recommended for
                column/index search to avoid hitting the table cap.
            table: Restrict column/index search to a specific table. Without
                ``schema`` this matches a table of that name in any schema.
            limit: Max items to return (1-1000). The total match count is
                still reported in ``total_found``.
        """
        regex = like_to_regex(pattern)
        types = _normalize_object_types(object_types)
        limit = _validate_limit(limit)

        results: list[SearchResultItem] = []
        early_termination = False
        notes: list[str] = []

        # ----- Resolve target schemas (single source of truth) -----
        all_schemas: Optional[list["SchemaInfo"]] = None
        if schema is not None:
            target_schema_names = [schema]
        else:
            all_schemas = await self.inspector.get_schemas()
            target_schema_names = [s.name for s in all_schemas]

        # ----- Schema results -----
        if SearchObjectType.SCHEMA in types:
            if all_schemas is None:
                all_schemas = await self.inspector.get_schemas()
            for s in all_schemas:
                if regex.match(s.name):
                    results.append(self._schema_to_result(s, detail_level))

        # Determine whether we need to walk tables at all.
        wants_table = SearchObjectType.TABLE in types
        wants_view = SearchObjectType.VIEW in types
        wants_column = SearchObjectType.COLUMN in types
        wants_index = SearchObjectType.INDEX in types
        wants_describe = wants_column or wants_index

        if not (wants_table or wants_view or wants_describe):
            return self._build_envelope(
                pattern=pattern,
                detail_level=detail_level,
                types=types,
                results=results,
                limit=limit,
                early_termination=False,
                notes=notes,
            )

        # ----- Walk schemas / tables -----
        described_count = 0
        for sch in target_schema_names:
            try:
                tables_in_schema = await self.inspector.get_tables(
                    sch, include_views=True
                )
            except Exception as e:
                logger.warning("Failed to list tables in schema %r: %s", sch, e)
                continue

            # Apply optional table-name filter (exact match for parent context)
            if table is not None:
                tables_in_schema = [t for t in tables_in_schema if t.name == table]

            # Match tables / views
            for t in tables_in_schema:
                is_view = bool(t.table_type) and "VIEW" in t.table_type.upper()
                type_token = (
                    SearchObjectType.VIEW if is_view else SearchObjectType.TABLE
                )
                if type_token not in types:
                    continue
                if regex.match(t.name):
                    results.append(self._table_to_result(t, detail_level))

            # Walk columns / indexes (requires describe_table)
            if not wants_describe:
                continue

            for t in tables_in_schema:
                if described_count >= MAX_TABLES_TO_DESCRIBE:
                    early_termination = True
                    break
                described_count += 1

                try:
                    info = await self.inspector.describe_table(t.name, sch)
                except Exception as e:
                    logger.warning(
                        "Failed to describe table %r in schema %r: %s", t.name, sch, e
                    )
                    continue

                if wants_column:
                    for col in info.columns:
                        if regex.match(col.name):
                            results.append(
                                self._column_to_result(col, info, detail_level)
                            )

                if wants_index:
                    for idx in info.indexes:
                        if regex.match(idx.name):
                            results.append(
                                self._index_to_result(idx, info, detail_level)
                            )

            if early_termination:
                break

        if early_termination:
            notes.append(
                f"Hit per-call cap of {MAX_TABLES_TO_DESCRIBE} described tables. "
                "Pass `schema` (and optionally `table`) to narrow the search."
            )

        return self._build_envelope(
            pattern=pattern,
            detail_level=detail_level,
            types=types,
            results=results,
            limit=limit,
            early_termination=early_termination,
            notes=notes,
        )

    # -------------------- Result builders --------------------

    @staticmethod
    def _build_envelope(
        *,
        pattern: str,
        detail_level: SearchDetailLevel,
        types: list[SearchObjectType],
        results: list[SearchResultItem],
        limit: int,
        early_termination: bool,
        notes: list[str],
    ) -> SearchResults:
        total = len(results)
        truncated = total > limit
        if truncated:
            notes.append(
                f"Returned {limit} of {total} matches. "
                "Increase `limit` or refine `pattern` / `object_types` for more."
            )
        return SearchResults(
            pattern=pattern,
            detail_level=detail_level.value,
            object_types=[t.value for t in types],
            results=results[:limit],
            total_found=total,
            returned=min(total, limit),
            limit=limit,
            truncated=truncated,
            early_termination=early_termination,
            note=" ".join(notes) if notes else None,
        )

    @staticmethod
    def _schema_to_result(
        schema: "SchemaInfo", detail: SearchDetailLevel
    ) -> SearchResultItem:
        item = SearchResultItem(
            object_type=SearchObjectType.SCHEMA.value, name=schema.name
        )
        if detail == SearchDetailLevel.NAMES:
            return item
        item.table_count_in_schema = schema.table_count
        item.view_count_in_schema = schema.view_count
        if detail == SearchDetailLevel.FULL:
            item.comment = schema.comment
        return item

    @staticmethod
    def _table_to_result(
        table: TableInfo, detail: SearchDetailLevel
    ) -> SearchResultItem:
        is_view = bool(table.table_type) and "VIEW" in table.table_type.upper()
        item = SearchResultItem(
            object_type=(
                SearchObjectType.VIEW if is_view else SearchObjectType.TABLE
            ).value,
            name=table.name,
            schema=table.schema,
        )
        if detail == SearchDetailLevel.NAMES:
            return item
        item.table_type = table.table_type
        item.row_count = table.row_count
        # column_count is only meaningful when columns have been populated
        # (get_tables doesn't populate them, so this stays None for the
        # match-table path; describe_table-driven matches would set it).
        if table.columns:
            item.column_count = len(table.columns)
        if detail == SearchDetailLevel.FULL:
            item.comment = table.comment
        return item

    @staticmethod
    def _column_to_result(
        column: ColumnInfo, table: TableInfo, detail: SearchDetailLevel
    ) -> SearchResultItem:
        item = SearchResultItem(
            object_type=SearchObjectType.COLUMN.value,
            name=column.name,
            schema=table.schema,
            table=table.name,
        )
        if detail == SearchDetailLevel.NAMES:
            return item
        item.data_type = column.data_type
        item.nullable = column.nullable
        item.primary_key = column.primary_key
        item.unique = column.unique
        item.indexed = column.indexed
        item.foreign_key = column.foreign_key
        if detail == SearchDetailLevel.FULL:
            item.comment = column.comment
            item.default = column.default
            item.max_length = column.max_length
            item.numeric_precision = column.numeric_precision
            item.numeric_scale = column.numeric_scale
        return item

    @staticmethod
    def _index_to_result(
        index: IndexInfo, table: TableInfo, detail: SearchDetailLevel
    ) -> SearchResultItem:
        item = SearchResultItem(
            object_type=SearchObjectType.INDEX.value,
            name=index.name,
            schema=table.schema,
            table=table.name,
        )
        if detail == SearchDetailLevel.NAMES:
            return item
        item.columns = list(index.columns)
        item.unique = index.unique
        item.index_type = index.index_type
        if detail == SearchDetailLevel.FULL:
            item.comment = index.comment
        return item
