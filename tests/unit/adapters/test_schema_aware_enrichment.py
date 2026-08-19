"""Schema-aware metadata enrichment tests for database adapters."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from db_connect_mcp.adapters.clickhouse import ClickHouseAdapter
from db_connect_mcp.adapters.mysql import MySQLAdapter
from db_connect_mcp.models.table import ColumnInfo, TableInfo


def _result(*, row: tuple[object, ...] | None = None) -> MagicMock:
    result = MagicMock()
    result.fetchone.return_value = row
    result.fetchall.return_value = []
    return result


@pytest.mark.asyncio
async def test_mysql_table_enrichment_uses_requested_schema() -> None:
    connection = MagicMock()
    connection.execute = AsyncMock(
        return_value=_result(
            row=("InnoDB", 4, 1024, 256, "analytics orders", None, None)
        )
    )
    table = TableInfo(name="orders", schema="analytics")

    enriched = await MySQLAdapter().enrich_table_info(connection, table)

    _, parameters = connection.execute.await_args.args
    assert parameters == {"schema_name": "analytics", "table_name": "orders"}
    assert enriched.comment == "analytics orders"


@pytest.mark.asyncio
async def test_mysql_column_comments_use_requested_schema() -> None:
    result = _result()
    result.fetchall.return_value = [("order_id", "analytics identifier")]
    connection = MagicMock()
    connection.execute = AsyncMock(return_value=result)
    columns = [ColumnInfo(name="order_id", data_type="int", nullable=False)]

    enriched = await MySQLAdapter().enrich_column_comments(
        connection, "orders", "analytics", columns
    )

    _, parameters = connection.execute.await_args.args
    assert parameters == {"schema_name": "analytics", "table_name": "orders"}
    assert enriched[0].comment == "analytics identifier"


@pytest.mark.asyncio
async def test_clickhouse_table_enrichment_uses_requested_database() -> None:
    table_result = _result(
        row=("MergeTree", 4, 1024, "", "order_id", "order_id", "", "analytics")
    )
    compression_result = _result(row=(256, 1024))
    connection = MagicMock()
    connection.execute = AsyncMock(side_effect=[table_result, compression_result])
    table = TableInfo(name="orders", schema="analytics")

    enriched = await ClickHouseAdapter().enrich_table_info(connection, table)

    for awaited_call in connection.execute.await_args_list:
        _, parameters = awaited_call.args
        assert parameters == {
            "schema_name": "analytics",
            "table_name": "orders",
        }
    assert enriched.comment == "analytics"
    assert enriched.extra_info["compression_ratio"] == 0.25


@pytest.mark.asyncio
async def test_clickhouse_column_comments_use_requested_database() -> None:
    result = _result()
    result.fetchall.return_value = [("order_id", "analytics identifier")]
    connection = MagicMock()
    connection.execute = AsyncMock(return_value=result)
    columns = [ColumnInfo(name="order_id", data_type="UInt64", nullable=False)]

    enriched = await ClickHouseAdapter().enrich_column_comments(
        connection, "orders", "analytics", columns
    )

    _, parameters = connection.execute.await_args.args
    assert parameters == {"schema_name": "analytics", "table_name": "orders"}
    assert enriched[0].comment == "analytics identifier"
