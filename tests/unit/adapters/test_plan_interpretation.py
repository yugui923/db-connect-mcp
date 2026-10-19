"""Evidence-based EXPLAIN interpretation for supported engines."""

import json

import pytest

from db_connect_mcp.adapters.clickhouse import ClickHouseAdapter
from db_connect_mcp.adapters.mysql import MySQLAdapter
from db_connect_mcp.adapters.postgresql import PostgresAdapter


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
