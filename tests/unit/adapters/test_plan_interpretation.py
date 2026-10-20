"""Evidence-based EXPLAIN interpretation for supported engines."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from db_connect_mcp.adapters.clickhouse import ClickHouseAdapter
from db_connect_mcp.adapters.mysql import MySQLAdapter
from db_connect_mcp.adapters.postgresql import PostgresAdapter
from db_connect_mcp.core.executor import QueryExecutor
from db_connect_mcp.models.query import ExplainPlan
from db_connect_mcp.server import (
    MAX_RESPONSE_EXPLAIN_QUERY,
    DatabaseMCPServer,
    apply_truncation_to_explain_query,
)


@pytest.mark.asyncio
async def test_pg_small_scan_does_not_suggest_index():
    adapter = PostgresAdapter()
    plan = [
        {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "tiny",
                "Plan Rows": 4,
                "Total Cost": 1.1,
                "Filter": "id > 0",
                "Actual Rows": 4,
                "Rows Removed by Filter": 2,
                "Actual Loops": 1,
            }
        }
    ]
    result = await adapter.parse_explain_plan(json.dumps(plan), True)
    assert result["warnings"] == []
    assert result["recommendations"] == []


@pytest.mark.asyncio
async def test_pg_analyzed_filtered_scan_cites_observed_rows():
    adapter = PostgresAdapter()
    plan = [
        {
            "Plan": {
                "Node Type": "Aggregate",
                "Plan Rows": 1,
                "Plans": [
                    {
                        "Node Type": "Seq Scan",
                        "Relation Name": "orders",
                        "Plan Rows": 50,
                        "Actual Rows": 20,
                        "Actual Loops": 2,
                        "Rows Removed by Filter": 5000,
                        "Filter": "status = 'open'",
                    }
                ],
            }
        }
    ]
    result = await adapter.parse_explain_plan(json.dumps(plan), True)
    assert len(result["warnings"]) == 1
    assert "orders" in result["warnings"][0]
    assert "10000" in result["warnings"][0]
    assert "observed" in result["warnings"][0].lower()
    assert len(result["recommendations"]) == 1
    assert "orders" in result["recommendations"][0]
    assert result["json"] == plan


@pytest.mark.asyncio
async def test_pg_estimated_scan_does_not_claim_observed_work():
    adapter = PostgresAdapter()
    result = await adapter.parse_explain_plan(
        json.dumps(
            [
                {
                    "Plan": {
                        "Node Type": "Seq Scan",
                        "Relation Name": "orders",
                        "Plan Rows": 900000,
                        "Filter": "status = 'open'",
                    }
                }
            ]
        ),
        False,
    )
    assert result["warnings"] == []
    assert result["recommendations"] == []
    assert result.get("actual_rows") is None


@pytest.mark.asyncio
async def test_mysql_nested_filtered_scan_uses_estimates_only():
    adapter = MySQLAdapter()
    plan = {
        "query_block": {
            "cost_info": {"query_cost": "45.2"},
            "nested_loop": [
                {
                    "table": {
                        "table_name": "orders",
                        "access_type": "ALL",
                        "rows_examined_per_scan": 12000,
                        "rows_produced_per_join": 120,
                        "filtered": "1.00",
                    }
                }
            ],
        }
    }
    result = await adapter.parse_explain_plan(json.dumps(plan), False)
    assert result["estimated_cost"] == 45.2
    assert result["json"] == plan
    assert len(result["warnings"]) == 1
    assert "estimated" in result["warnings"][0].lower()
    assert "orders" in result["warnings"][0]
    assert result["recommendations"] == []


@pytest.mark.asyncio
async def test_mysql_small_scan_and_analyze_text_no_advice():
    adapter = MySQLAdapter()
    result = await adapter.parse_explain_plan(
        json.dumps(
            {
                "query_block": {
                    "table": {
                        "table_name": "tiny",
                        "access_type": "ALL",
                        "rows_examined_per_scan": 8,
                        "filtered": 10,
                    }
                }
            }
        ),
        False,
    )
    assert result["warnings"] == result["recommendations"] == []
    text = await adapter.parse_explain_plan(
        "-> Table scan on tiny (actual time=0.1..0.2 rows=8 loops=1)", True
    )
    assert text["warnings"] == text["recommendations"] == []


@pytest.mark.asyncio
async def test_pg_many_scans_bound_advice_through_handler():
    scans = [
        {
            "Node Type": "Seq Scan",
            "Relation Name": f"orders_{i:04d}",
            "Filter": "status = 'open'",
            "Actual Rows": 1,
            "Actual Loops": 1,
            "Rows Removed by Filter": 10000,
        }
        for i in range(800)
    ]
    plan = [{"Plan": {"Node Type": "Append", "Plans": scans}}]
    connection = MagicMock()
    connection.dialect = "postgresql"
    db_connection = MagicMock()
    db_connection.execute = AsyncMock(return_value=MagicMock())
    db_connection.execute.return_value.fetchall.return_value = [(plan,)]
    connection.get_connection.return_value.__aenter__.return_value = db_connection
    executor = QueryExecutor(connection, PostgresAdapter())
    server = DatabaseMCPServer.__new__(DatabaseMCPServer)
    server.executor = executor

    response = (
        await server.handle_explain_query({"query": "SELECT 1", "analyze": True})
    )[0].text
    result = json.loads(response)
    assert len(response) <= MAX_RESPONSE_EXPLAIN_QUERY
    assert "error" not in result
    data = result["data"]
    assert data["warnings"][0].startswith("Sequential scan on orders_0000")
    assert len(data["warnings"]) == 20
    assert len(data["recommendations"]) == 20
    assert data["warnings_omitted"] == 780
    assert data["recommendations_omitted"] == 780
    assert set(result["_truncation_info"]["truncated_fields"]) >= {
        "plan",
        "plan_json",
        "warnings",
        "recommendations",
    }
    assert "orders_0020" not in " ".join(data["warnings"])


@pytest.mark.asyncio
async def test_mysql_many_tables_bound_advice_through_handler():
    tables = [
        {
            "table": {
                "table_name": f"orders_{i:04d}",
                "access_type": "ALL",
                "rows_examined_per_scan": 10000,
                "filtered": 1,
            }
        }
        for i in range(800)
    ]
    plan = {"query_block": {"nested_loop": tables}}
    connection = MagicMock()
    connection.dialect = "mysql"
    db_connection = MagicMock()
    db_connection.execute = AsyncMock(return_value=MagicMock())
    db_connection.execute.return_value.fetchall.return_value = [(json.dumps(plan),)]
    connection.get_connection.return_value.__aenter__.return_value = db_connection
    executor = QueryExecutor(connection, MySQLAdapter())
    server = DatabaseMCPServer.__new__(DatabaseMCPServer)
    server.executor = executor

    response = (await server.handle_explain_query({"query": "SELECT 1"}))[0].text
    result = json.loads(response)
    assert len(response) <= MAX_RESPONSE_EXPLAIN_QUERY
    assert "error" not in result
    data = result["data"]
    assert data["warnings"][0].startswith("Full scan on orders_0000")
    assert len(data["warnings"]) == 20
    assert data["warnings_omitted"] == 780
    assert data["recommendations"] == []
    assert data["recommendations_omitted"] == 0
    assert "warnings" in result["_truncation_info"]["truncated_fields"]


def test_legacy_explain_advice_is_bounded_with_omitted_counts():
    plan = ExplainPlan(
        query="SELECT 1",
        plan="Result",
        warnings=[f"Warning {i}" for i in range(25)],
        recommendations=[f"Recommendation {i}" for i in range(22)],
    )
    result, truncated = apply_truncation_to_explain_query(plan.model_dump(), 100000)
    assert result["warnings"] == [f"Warning {i}" for i in range(20)]
    assert result["recommendations"] == [f"Recommendation {i}" for i in range(20)]
    assert result["warnings_omitted"] == 5
    assert result["recommendations_omitted"] == 2
    assert set(truncated) == {"warnings", "recommendations"}


def test_explain_plan_legacy_advice_defaults_and_deduplication():
    plan = ExplainPlan(query="SELECT 1", plan="Result")
    plan.add_warning("Review the scan")
    plan.add_warning("Review the scan")
    plan.add_recommendation("Review the index")
    assert plan.warnings == ["Review the scan"]
    assert plan.recommendations == ["Review the index"]
    assert plan.warnings_omitted == plan.recommendations_omitted == 0


@pytest.mark.asyncio
async def test_pg_invalid_json_preserves_raw_plan():
    result = await PostgresAdapter().parse_explain_plan("not json", False)
    assert result["plan_text"] == "not json"
    assert result["json"] is None
    assert result["recommendations"] == []


@pytest.mark.asyncio
async def test_clickhouse_text_does_not_infer_index_from_scan_words():
    result = await ClickHouseAdapter().parse_explain_plan(
        "Full scan of tiny table", False
    )
    assert result["warnings"] == result["recommendations"] == []
