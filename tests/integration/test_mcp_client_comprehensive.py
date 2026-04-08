"""Comprehensive MCP Client Integration Tests

Tests ALL MCP tools across ALL supported database types using a real MCP client.
This provides comprehensive coverage of the MCP protocol layer.

Tools tested (10 total):
- get_database_info
- list_schemas
- list_tables
- describe_table
- execute_query
- sample_data
- search_objects
- get_table_relationships (conditional - requires foreign_keys capability)
- analyze_column (conditional - requires advanced_stats capability)
- explain_query (conditional - requires explain_plans capability)

Database types tested:
- PostgreSQL (direct and tunneled)
- MySQL (direct and tunneled)
- ClickHouse
"""

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import pytest
from mcp import ClientSession

from db_connect_mcp.models.config import DatabaseConfig
from .test_mcp_protocol import MCPProtocolHelper


# ============================================================================
# Fixtures for MCP Client Testing
# ============================================================================


@asynccontextmanager
async def mcp_client(config: DatabaseConfig) -> AsyncGenerator[ClientSession, None]:
    """Context manager that creates MCP server and client, handles cleanup."""
    server, client = await MCPProtocolHelper.create_test_server_and_client(config)
    try:
        yield client
    finally:
        await server.cleanup()


@pytest.fixture
async def pg_client(pg_config: DatabaseConfig) -> AsyncGenerator[ClientSession, None]:
    """PostgreSQL MCP client fixture."""
    async with mcp_client(pg_config) as client:
        yield client


@pytest.fixture
async def mysql_client(
    mysql_config: DatabaseConfig,
) -> AsyncGenerator[ClientSession, None]:
    """MySQL MCP client fixture."""
    async with mcp_client(mysql_config) as client:
        yield client


@pytest.fixture
async def ch_client(ch_config: DatabaseConfig) -> AsyncGenerator[ClientSession, None]:
    """ClickHouse MCP client fixture."""
    async with mcp_client(ch_config) as client:
        yield client


@pytest.fixture
async def pg_tunnel_client(
    pg_tunnel_config: DatabaseConfig,
) -> AsyncGenerator[ClientSession, None]:
    """PostgreSQL tunneled MCP client fixture."""
    async with mcp_client(pg_tunnel_config) as client:
        yield client


@pytest.fixture
async def mysql_tunnel_client(
    mysql_tunnel_config: DatabaseConfig,
) -> AsyncGenerator[ClientSession, None]:
    """MySQL tunneled MCP client fixture."""
    async with mcp_client(mysql_tunnel_config) as client:
        yield client


# ============================================================================
# Helper Functions
# ============================================================================


async def get_available_tools(client: ClientSession) -> set[str]:
    """Get set of available tool names from client."""
    tools_response = await client.list_tools()
    return {t.name for t in tools_response.tools}


async def call_tool_checked(
    client: ClientSession, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Call a tool and return parsed response, raising on error."""
    response = await client.call_tool(tool_name, arguments=arguments)
    return MCPProtocolHelper.check_and_parse_response(response)


async def skip_if_tool_unavailable(client: ClientSession, tool_name: str) -> None:
    """Skip test if tool is not available."""
    tools = await get_available_tools(client)
    if tool_name not in tools:
        pytest.skip(f"{tool_name} not available")


# ============================================================================
# PostgreSQL Direct Tests - All 9 Tools
# ============================================================================


@pytest.mark.postgresql
@pytest.mark.integration
@pytest.mark.xdist_group(name="mcp_pg_direct")
class TestPostgreSQLDirectMCPClient:
    """Comprehensive MCP client tests for PostgreSQL direct connection."""

    # --- Tool: get_database_info ---

    @pytest.mark.asyncio
    async def test_get_database_info(self, pg_client: ClientSession):
        """Test get_database_info returns correct PostgreSQL info."""
        data = await call_tool_checked(pg_client, "get_database_info", {})

        assert data["dialect"] == "postgresql"
        assert "name" in data
        assert "version" in data
        assert "capabilities" in data
        assert "read_only" in data

        # PostgreSQL should have all features
        caps = data["capabilities"]
        assert caps["foreign_keys"] is True
        assert caps["indexes"] is True
        assert caps["views"] is True
        assert caps["advanced_stats"] is True
        assert caps["explain_plans"] is True

    # --- Tool: list_schemas ---

    @pytest.mark.asyncio
    async def test_list_schemas(self, pg_client: ClientSession):
        """Test list_schemas returns PostgreSQL schemas."""
        data = await call_tool_checked(pg_client, "list_schemas", {})

        assert isinstance(data, list)
        assert len(data) > 0
        assert "name" in data[0]
        assert "table_count" in data[0]

        schema_names = [s["name"] for s in data]
        assert "public" in schema_names

    # --- Tool: list_tables ---

    @pytest.mark.asyncio
    async def test_list_tables_default(self, pg_client: ClientSession):
        """Test list_tables with default parameters."""
        data = await call_tool_checked(pg_client, "list_tables", {})

        assert isinstance(data, list)
        if len(data) > 0:
            assert "name" in data[0]
            assert "table_type" in data[0]

    @pytest.mark.asyncio
    async def test_list_tables_with_schema(self, pg_client: ClientSession):
        """Test list_tables with specific schema."""
        data = await call_tool_checked(pg_client, "list_tables", {"schema": "public"})

        assert isinstance(data, list)
        for table in data:
            assert table["schema"] == "public"

    @pytest.mark.asyncio
    async def test_list_tables_exclude_views(self, pg_client: ClientSession):
        """Test list_tables excluding views."""
        data = await call_tool_checked(
            pg_client, "list_tables", {"schema": "public", "include_views": False}
        )

        assert isinstance(data, list)
        for table in data:
            assert table["table_type"] in ("table", "TABLE", "BASE TABLE")

    # --- Tool: describe_table ---

    @pytest.mark.asyncio
    async def test_describe_table_structure(self, pg_client: ClientSession):
        """Test describe_table returns correct structure."""
        data = await call_tool_checked(
            pg_client, "describe_table", {"table": "products", "schema": "public"}
        )

        assert data["name"] == "products"
        assert "columns" in data
        assert len(data["columns"]) > 0

        col = data["columns"][0]
        assert "name" in col
        assert "data_type" in col
        assert "nullable" in col

        assert "indexes" in data
        assert "constraints" in data

    @pytest.mark.asyncio
    async def test_describe_table_with_comments(self, pg_client: ClientSession):
        """Test describe_table returns comments."""
        data = await call_tool_checked(
            pg_client, "describe_table", {"table": "categories", "schema": "public"}
        )

        assert data["comment"] is not None
        assert "categor" in data["comment"].lower()

    @pytest.mark.asyncio
    async def test_describe_table_nonexistent_returns_error(
        self, pg_client: ClientSession
    ):
        """Test describe_table with nonexistent table returns error."""
        response = await pg_client.call_tool(
            "describe_table",
            arguments={"table": "nonexistent_table_xyz123", "schema": "public"},
        )
        assert response.isError

    # --- Tool: execute_query ---

    @pytest.mark.asyncio
    async def test_execute_query_simple(self, pg_client: ClientSession):
        """Test execute_query with simple SELECT."""
        data = await call_tool_checked(
            pg_client,
            "execute_query",
            {"query": "SELECT 1 as num, 'hello' as greeting"},
        )

        assert data["row_count"] == 1
        assert "num" in data["columns"]
        assert "greeting" in data["columns"]
        assert data["rows"][0]["num"] == 1
        assert data["rows"][0]["greeting"] == "hello"
        assert "execution_time_ms" in data

    @pytest.mark.asyncio
    async def test_execute_query_respects_limit(self, pg_client: ClientSession):
        """Test execute_query respects limit parameter."""
        data = await call_tool_checked(
            pg_client, "execute_query", {"query": "SELECT * FROM products", "limit": 5}
        )

        assert data["row_count"] <= 5
        assert len(data["rows"]) <= 5

    @pytest.mark.asyncio
    async def test_execute_query_with_cte(self, pg_client: ClientSession):
        """Test execute_query with CTE."""
        cte_query = """
        WITH sample_data AS (
            SELECT 1 as id, 'Alice' as name
            UNION ALL SELECT 2, 'Bob'
            UNION ALL SELECT 3, 'Charlie'
        )
        SELECT * FROM sample_data ORDER BY id
        """
        data = await call_tool_checked(
            pg_client, "execute_query", {"query": cte_query, "limit": 10}
        )

        assert data["row_count"] == 3
        assert data["rows"][0]["name"] == "Alice"
        assert data["rows"][2]["name"] == "Charlie"

    @pytest.mark.asyncio
    async def test_execute_query_special_types_serialize(
        self, pg_client: ClientSession
    ):
        """Test execute_query serializes PostgreSQL special types."""
        query = """
        SELECT
            NOW()::TIMESTAMP as ts, CURRENT_DATE::DATE as dt,
            '192.168.1.1'::INET as ip, gen_random_uuid() as uuid_val,
            3.14159::NUMERIC as decimal_val, TRUE::BOOLEAN as bool_val,
            ARRAY[1,2,3]::INTEGER[] as arr
        """
        data = await call_tool_checked(pg_client, "execute_query", {"query": query})
        row = data["rows"][0]

        assert isinstance(row["ts"], str)
        assert isinstance(row["dt"], str)
        assert isinstance(row["ip"], str)
        assert isinstance(row["uuid_val"], str)
        assert isinstance(row["decimal_val"], (str, int, float))
        assert row["bool_val"] is True
        assert isinstance(row["arr"], list)

    @pytest.mark.asyncio
    async def test_execute_query_rejects_writes(self, pg_client: ClientSession):
        """Test that write queries are rejected."""
        write_queries = [
            "INSERT INTO products (name) VALUES ('test')",
            "UPDATE products SET name = 'test'",
            "DELETE FROM products",
            "DROP TABLE products",
        ]
        for query in write_queries:
            response = await pg_client.call_tool(
                "execute_query", arguments={"query": query}
            )
            assert response.isError, f"Expected error for: {query}"

    # --- Tool: sample_data ---

    @pytest.mark.asyncio
    async def test_sample_data_default(self, pg_client: ClientSession):
        """Test sample_data with default parameters."""
        data = await call_tool_checked(pg_client, "sample_data", {"table": "products"})

        assert "row_count" in data
        assert "columns" in data
        assert "rows" in data
        assert data["row_count"] <= 100

    @pytest.mark.asyncio
    async def test_sample_data_with_limit(self, pg_client: ClientSession):
        """Test sample_data with custom limit."""
        data = await call_tool_checked(
            pg_client,
            "sample_data",
            {"table": "products", "schema": "public", "limit": 5},
        )

        assert data["row_count"] <= 5
        assert len(data["rows"]) <= 5

    @pytest.mark.asyncio
    async def test_sample_data_json_serializable(self, pg_client: ClientSession):
        """Test that sample_data results are JSON serializable."""
        data = await call_tool_checked(
            pg_client, "sample_data", {"table": "data_type_examples", "limit": 10}
        )

        json_str = json.dumps(data)
        reparsed = json.loads(json_str)
        assert reparsed["row_count"] == data["row_count"]

    # --- Tool: get_table_relationships (conditional) ---

    @pytest.mark.asyncio
    async def test_get_table_relationships_products(self, pg_client: ClientSession):
        """Test get_table_relationships on products table (has FK to categories)."""
        await skip_if_tool_unavailable(pg_client, "get_table_relationships")

        data = await call_tool_checked(
            pg_client,
            "get_table_relationships",
            {"table": "products", "schema": "public"},
        )

        assert isinstance(data, list)
        assert len(data) > 0
        assert all(
            key in data[0]
            for key in ["from_table", "to_table", "from_columns", "to_columns"]
        )

    @pytest.mark.asyncio
    async def test_get_table_relationships_orders(self, pg_client: ClientSession):
        """Test get_table_relationships on orders table (has FK to users)."""
        await skip_if_tool_unavailable(pg_client, "get_table_relationships")

        data = await call_tool_checked(
            pg_client,
            "get_table_relationships",
            {"table": "orders", "schema": "public"},
        )

        user_rel = next((r for r in data if r.get("to_table") == "users"), None)
        assert user_rel is not None

    @pytest.mark.asyncio
    async def test_get_table_relationships_self_referencing(
        self, pg_client: ClientSession
    ):
        """Test get_table_relationships on categories (self-referencing FK)."""
        await skip_if_tool_unavailable(pg_client, "get_table_relationships")

        data = await call_tool_checked(
            pg_client,
            "get_table_relationships",
            {"table": "categories", "schema": "public"},
        )

        self_rel = next((r for r in data if r.get("to_table") == "categories"), None)
        assert self_rel is not None

    # --- Tool: analyze_column (conditional) ---

    @pytest.mark.asyncio
    async def test_analyze_column_numeric(self, pg_client: ClientSession):
        """Test analyze_column on numeric column (price)."""
        await skip_if_tool_unavailable(pg_client, "analyze_column")

        data = await call_tool_checked(
            pg_client,
            "analyze_column",
            {"table": "products", "column": "price", "schema": "public"},
        )

        assert data["column"] == "price"
        assert "total_rows" in data
        assert "null_count" in data
        assert "distinct_count" in data
        assert "min_value" in data
        assert "max_value" in data

    @pytest.mark.asyncio
    async def test_analyze_column_text(self, pg_client: ClientSession):
        """Test analyze_column on text column."""
        await skip_if_tool_unavailable(pg_client, "analyze_column")

        data = await call_tool_checked(
            pg_client,
            "analyze_column",
            {"table": "products", "column": "name", "schema": "public"},
        )

        assert data["column"] == "name"
        assert "total_rows" in data
        assert "distinct_count" in data

    @pytest.mark.asyncio
    async def test_analyze_column_nullable(self, pg_client: ClientSession):
        """Test analyze_column on nullable column."""
        await skip_if_tool_unavailable(pg_client, "analyze_column")

        data = await call_tool_checked(
            pg_client,
            "analyze_column",
            {"table": "users", "column": "last_login_at", "schema": "public"},
        )

        assert "null_count" in data
        assert isinstance(data["null_count"], int)

    # --- Tool: explain_query (conditional) ---

    @pytest.mark.asyncio
    async def test_explain_query_simple(self, pg_client: ClientSession):
        """Test explain_query with simple SELECT."""
        await skip_if_tool_unavailable(pg_client, "explain_query")

        data = await call_tool_checked(
            pg_client,
            "explain_query",
            {"query": "SELECT * FROM products WHERE price > 100"},
        )

        assert "query" in data
        assert "plan" in data
        assert len(data["plan"]) > 0

    @pytest.mark.asyncio
    async def test_explain_query_with_analyze(self, pg_client: ClientSession):
        """Test explain_query with EXPLAIN ANALYZE."""
        await skip_if_tool_unavailable(pg_client, "explain_query")

        data = await call_tool_checked(
            pg_client,
            "explain_query",
            {"query": "SELECT * FROM products LIMIT 10", "analyze": True},
        )

        plan_text = data["plan"].lower()
        assert "actual" in plan_text or "time" in plan_text

    @pytest.mark.asyncio
    async def test_explain_query_with_join(self, pg_client: ClientSession):
        """Test explain_query with JOIN query."""
        await skip_if_tool_unavailable(pg_client, "explain_query")

        query = """
        SELECT p.name, c.name as category_name
        FROM products p JOIN categories c ON p.category_id = c.category_id
        LIMIT 10
        """
        data = await call_tool_checked(pg_client, "explain_query", {"query": query})

        plan_text = data["plan"].lower()
        assert "join" in plan_text or "loop" in plan_text or "hash" in plan_text

    # --- Tool: search_objects ---

    @pytest.mark.asyncio
    async def test_search_objects_registered(self, pg_client: ClientSession):
        """Tool is registered and visible to MCP clients with a valid schema."""
        tools = await pg_client.list_tools()
        search = next((t for t in tools.tools if t.name == "search_objects"), None)
        assert search is not None, "search_objects should always be registered"
        # Verify the inputSchema is well-formed for an MCP client
        assert search.inputSchema["type"] == "object"
        assert "pattern" in search.inputSchema["properties"]
        assert search.inputSchema["required"] == ["pattern"]

    @pytest.mark.asyncio
    async def test_search_objects_finds_seeded_table(self, pg_client: ClientSession):
        """Searching for 'users' returns the seeded users table."""
        data = await call_tool_checked(
            pg_client,
            "search_objects",
            {
                "pattern": "users",
                "object_types": ["table"],
                "schema": "public",
            },
        )
        assert data["pattern"] == "users"
        assert data["total_found"] >= 1
        assert any(
            r["name"] == "users" and r["object_type"] == "table"
            for r in data["results"]
        )

    @pytest.mark.asyncio
    async def test_search_objects_substring_pattern(self, pg_client: ClientSession):
        """LIKE substring pattern matches multiple tables."""
        data = await call_tool_checked(
            pg_client,
            "search_objects",
            {
                "pattern": "%order%",
                "object_types": ["table"],
                "schema": "public",
            },
        )
        names = {r["name"] for r in data["results"]}
        # The seed schema has both `orders` and `order_items`
        assert "orders" in names
        assert "order_items" in names

    @pytest.mark.asyncio
    async def test_search_objects_columns_with_table_filter(
        self, pg_client: ClientSession
    ):
        """Column search restricted to a specific table returns one match."""
        data = await call_tool_checked(
            pg_client,
            "search_objects",
            {
                "pattern": "user_id",
                "object_types": ["column"],
                "schema": "public",
                "table": "users",
                "detail_level": "summary",
            },
        )
        assert data["total_found"] == 1
        col = data["results"][0]
        assert col["object_type"] == "column"
        assert col["name"] == "user_id"
        assert col["table"] == "users"
        # Summary level populates these
        assert col["primary_key"] is True
        assert "data_type" in col

    @pytest.mark.asyncio
    async def test_search_objects_user_id_across_tables(self, pg_client: ClientSession):
        """Without a `table` filter, user_id matches in users and orders."""
        data = await call_tool_checked(
            pg_client,
            "search_objects",
            {
                "pattern": "user_id",
                "object_types": ["column"],
                "schema": "public",
            },
        )
        tables_with_user_id = {r["table"] for r in data["results"]}
        assert "users" in tables_with_user_id
        assert "orders" in tables_with_user_id

    @pytest.mark.asyncio
    async def test_search_objects_names_level_excludes_metadata(
        self, pg_client: ClientSession
    ):
        """detail_level=names should drop metadata fields entirely."""
        data = await call_tool_checked(
            pg_client,
            "search_objects",
            {
                "pattern": "users",
                "object_types": ["table"],
                "schema": "public",
                "detail_level": "names",
            },
        )
        users = next(r for r in data["results"] if r["name"] == "users")
        # exclude_none drops absent fields, so these keys should not exist
        assert "row_count" not in users
        assert "table_type" not in users
        assert "comment" not in users
        # Identification fields are still present
        assert users["object_type"] == "table"
        assert users["schema"] == "public"

    @pytest.mark.asyncio
    async def test_search_objects_truncation(self, pg_client: ClientSession):
        """A small limit yields a truncation flag and partial results."""
        data = await call_tool_checked(
            pg_client,
            "search_objects",
            {
                "pattern": "%",
                "object_types": ["column"],
                "schema": "public",
                "limit": 2,
            },
        )
        assert data["returned"] == 2
        assert data["total_found"] > 2
        assert data["truncated"] is True
        assert "note" in data

    @pytest.mark.asyncio
    async def test_search_objects_invalid_pattern_returns_error(
        self, pg_client: ClientSession
    ):
        """Empty pattern is rejected at the MCP layer."""
        response = await pg_client.call_tool(
            "search_objects", arguments={"pattern": ""}
        )
        assert response.isError

    @pytest.mark.asyncio
    async def test_search_objects_index_results(self, pg_client: ClientSession):
        """Searching indexes on the users table returns at least one index."""
        data = await call_tool_checked(
            pg_client,
            "search_objects",
            {
                "pattern": "%",
                "object_types": ["index"],
                "schema": "public",
                "table": "users",
                "detail_level": "summary",
            },
        )
        assert data["total_found"] >= 1
        for r in data["results"]:
            assert r["object_type"] == "index"
            assert r["table"] == "users"
            assert "columns" in r and isinstance(r["columns"], list)


# ============================================================================
# MySQL Direct Tests
# ============================================================================


@pytest.mark.mysql
@pytest.mark.integration
@pytest.mark.xdist_group(name="mcp_mysql_direct")
class TestMySQLDirectMCPClient:
    """MCP client tests for MySQL direct connection."""

    @pytest.mark.asyncio
    async def test_get_database_info(self, mysql_client: ClientSession):
        """Test get_database_info returns correct MySQL info."""
        data = await call_tool_checked(mysql_client, "get_database_info", {})

        assert data["dialect"] == "mysql"
        caps = data["capabilities"]
        assert caps["foreign_keys"] is True
        assert caps["advanced_stats"] is False  # MySQL limitation

    @pytest.mark.asyncio
    async def test_list_schemas(self, mysql_client: ClientSession):
        """Test list_schemas returns MySQL databases."""
        data = await call_tool_checked(mysql_client, "list_schemas", {})

        assert isinstance(data, list)
        assert len(data) > 0

    @pytest.mark.asyncio
    async def test_list_tables(self, mysql_client: ClientSession):
        """Test list_tables returns MySQL tables."""
        data = await call_tool_checked(mysql_client, "list_tables", {})
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_describe_table(self, mysql_client: ClientSession):
        """Test describe_table on MySQL table."""
        tables = await call_tool_checked(mysql_client, "list_tables", {})
        if not tables:
            pytest.skip("No tables available")

        table_name = tables[0]["name"]
        args: dict[str, Any] = {"table": table_name}
        if schema := tables[0].get("schema"):
            args["schema"] = schema

        data = await call_tool_checked(mysql_client, "describe_table", args)
        assert data["name"] == table_name
        assert len(data["columns"]) > 0

    @pytest.mark.asyncio
    async def test_execute_query(self, mysql_client: ClientSession):
        """Test execute_query on MySQL."""
        data = await call_tool_checked(
            mysql_client,
            "execute_query",
            {"query": "SELECT 1 as num, 'hello' as greeting"},
        )

        assert data["row_count"] == 1
        assert data["rows"][0]["num"] == 1

    @pytest.mark.asyncio
    async def test_execute_query_rejects_writes(self, mysql_client: ClientSession):
        """Test that write queries are rejected in MySQL."""
        response = await mysql_client.call_tool(
            "execute_query", arguments={"query": "DROP TABLE IF EXISTS test_table"}
        )
        assert response.isError

    @pytest.mark.asyncio
    async def test_sample_data(self, mysql_client: ClientSession):
        """Test sample_data on MySQL table."""
        tables = await call_tool_checked(mysql_client, "list_tables", {})
        if not tables:
            pytest.skip("No tables available")

        data = await call_tool_checked(
            mysql_client, "sample_data", {"table": tables[0]["name"], "limit": 5}
        )
        assert data["row_count"] <= 5

    @pytest.mark.asyncio
    async def test_get_table_relationships(self, mysql_client: ClientSession):
        """Test get_table_relationships on MySQL."""
        await skip_if_tool_unavailable(mysql_client, "get_table_relationships")

        tables = await call_tool_checked(mysql_client, "list_tables", {})
        if not tables:
            pytest.skip("No tables available")

        data = await call_tool_checked(
            mysql_client, "get_table_relationships", {"table": tables[0]["name"]}
        )
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_explain_query(self, mysql_client: ClientSession):
        """Test explain_query on MySQL."""
        await skip_if_tool_unavailable(mysql_client, "explain_query")

        data = await call_tool_checked(
            mysql_client, "explain_query", {"query": "SELECT 1"}
        )
        assert "plan" in data

    @pytest.mark.asyncio
    async def test_search_objects_mysql(self, mysql_client: ClientSession):
        """Search_objects works through the MCP layer on MySQL too.

        Pattern is `%` to avoid relying on a specific seeded table name in
        the MySQL fixture, which differs from PostgreSQL.
        """
        data = await call_tool_checked(
            mysql_client,
            "search_objects",
            {
                "pattern": "%",
                "object_types": ["table"],
                "limit": 5,
            },
        )
        assert data["pattern"] == "%"
        # Either there are tables, or the user has an empty schema — both
        # outcomes are valid; we just need the envelope shape to be correct.
        assert "results" in data
        assert "total_found" in data
        assert "limit" in data and data["limit"] == 5

    @pytest.mark.asyncio
    async def test_analyze_column_not_available(self, mysql_client: ClientSession):
        """Test that analyze_column is not available for MySQL."""
        tools = await get_available_tools(mysql_client)
        assert "analyze_column" not in tools


# ============================================================================
# ClickHouse Tests
# ============================================================================


@pytest.mark.clickhouse
@pytest.mark.integration
@pytest.mark.xdist_group(name="mcp_clickhouse")
class TestClickHouseMCPClient:
    """MCP client tests for ClickHouse connection."""

    @pytest.mark.asyncio
    async def test_get_database_info(self, ch_client: ClientSession):
        """Test get_database_info returns correct ClickHouse info."""
        data = await call_tool_checked(ch_client, "get_database_info", {})

        assert data["dialect"] == "clickhouse"
        caps = data["capabilities"]
        assert caps["foreign_keys"] is False  # ClickHouse limitation
        assert caps["advanced_stats"] is True

    @pytest.mark.asyncio
    async def test_list_schemas(self, ch_client: ClientSession):
        """Test list_schemas returns ClickHouse databases."""
        data = await call_tool_checked(ch_client, "list_schemas", {})
        assert isinstance(data, list)
        assert len(data) > 0

    @pytest.mark.asyncio
    async def test_list_tables(self, ch_client: ClientSession):
        """Test list_tables returns ClickHouse tables."""
        data = await call_tool_checked(ch_client, "list_tables", {})
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_execute_query(self, ch_client: ClientSession):
        """Test execute_query on ClickHouse."""
        data = await call_tool_checked(
            ch_client,
            "execute_query",
            {"query": "SELECT 1 as num, 'hello' as greeting"},
        )
        assert data["row_count"] == 1

    @pytest.mark.asyncio
    async def test_get_relationships_not_available(self, ch_client: ClientSession):
        """Test that get_table_relationships is not available for ClickHouse."""
        tools = await get_available_tools(ch_client)
        assert "get_table_relationships" not in tools

    @pytest.mark.asyncio
    async def test_analyze_column(self, ch_client: ClientSession):
        """Test analyze_column on ClickHouse."""
        await skip_if_tool_unavailable(ch_client, "analyze_column")

        tables = await call_tool_checked(ch_client, "list_tables", {})
        if not tables:
            pytest.skip("No tables available")

        table = tables[0]
        desc = await call_tool_checked(
            ch_client,
            "describe_table",
            {"table": table["name"], "schema": table.get("schema")},
        )
        if not desc["columns"]:
            pytest.skip("No columns available")

        data = await call_tool_checked(
            ch_client,
            "analyze_column",
            {
                "table": table["name"],
                "column": desc["columns"][0]["name"],
                "schema": table.get("schema"),
            },
        )
        assert "total_rows" in data

    @pytest.mark.asyncio
    async def test_explain_query(self, ch_client: ClientSession):
        """Test explain_query on ClickHouse."""
        await skip_if_tool_unavailable(ch_client, "explain_query")

        data = await call_tool_checked(
            ch_client, "explain_query", {"query": "SELECT 1"}
        )
        assert "plan" in data


# ============================================================================
# SSH Tunnel Tests
# ============================================================================


@pytest.mark.postgresql
@pytest.mark.ssh_tunnel
@pytest.mark.integration
@pytest.mark.xdist_group(name="mcp_pg_tunneled")
class TestPostgreSQLTunneledMCPClient:
    """MCP client tests for PostgreSQL via SSH tunnel."""

    @pytest.mark.asyncio
    async def test_get_database_info(self, pg_tunnel_client: ClientSession):
        """Test get_database_info via SSH tunnel."""
        data = await call_tool_checked(pg_tunnel_client, "get_database_info", {})
        assert data["dialect"] == "postgresql"

    @pytest.mark.asyncio
    async def test_list_schemas(self, pg_tunnel_client: ClientSession):
        """Test list_schemas via SSH tunnel."""
        data = await call_tool_checked(pg_tunnel_client, "list_schemas", {})
        schema_names = [s["name"] for s in data]
        assert "public" in schema_names

    @pytest.mark.asyncio
    async def test_execute_query(self, pg_tunnel_client: ClientSession):
        """Test execute_query via SSH tunnel."""
        data = await call_tool_checked(
            pg_tunnel_client, "execute_query", {"query": "SELECT 1 as test_val"}
        )
        assert data["rows"][0]["test_val"] == 1

    @pytest.mark.asyncio
    async def test_sample_data(self, pg_tunnel_client: ClientSession):
        """Test sample_data via SSH tunnel."""
        tables = await call_tool_checked(pg_tunnel_client, "list_tables", {})
        if not tables:
            pytest.skip("No tables available")

        data = await call_tool_checked(
            pg_tunnel_client, "sample_data", {"table": tables[0]["name"], "limit": 5}
        )
        assert "rows" in data


@pytest.mark.mysql
@pytest.mark.ssh_tunnel
@pytest.mark.integration
@pytest.mark.xdist_group(name="mcp_mysql_tunneled")
class TestMySQLTunneledMCPClient:
    """MCP client tests for MySQL via SSH tunnel."""

    @pytest.mark.asyncio
    async def test_get_database_info(self, mysql_tunnel_client: ClientSession):
        """Test get_database_info via SSH tunnel."""
        data = await call_tool_checked(mysql_tunnel_client, "get_database_info", {})
        assert data["dialect"] == "mysql"

    @pytest.mark.asyncio
    async def test_list_schemas(self, mysql_tunnel_client: ClientSession):
        """Test list_schemas via SSH tunnel."""
        data = await call_tool_checked(mysql_tunnel_client, "list_schemas", {})
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_execute_query(self, mysql_tunnel_client: ClientSession):
        """Test execute_query via SSH tunnel."""
        data = await call_tool_checked(
            mysql_tunnel_client, "execute_query", {"query": "SELECT 1 as test_val"}
        )
        assert data["rows"][0]["test_val"] == 1


# ============================================================================
# Tool Registration Tests
# ============================================================================


@pytest.mark.integration
class TestMCPToolRegistration:
    """Test tool registration across different database types."""

    @pytest.mark.asyncio
    @pytest.mark.postgresql
    async def test_postgresql_registers_all_10_tools(self, pg_client: ClientSession):
        """Verify PostgreSQL registers all 10 tools."""
        tools = await get_available_tools(pg_client)

        expected = {
            "get_database_info",
            "list_schemas",
            "list_tables",
            "describe_table",
            "execute_query",
            "sample_data",
            "get_table_relationships",
            "analyze_column",
            "explain_query",
            "search_objects",
        }
        assert tools == expected

    @pytest.mark.asyncio
    @pytest.mark.mysql
    async def test_mysql_registers_9_tools(self, mysql_client: ClientSession):
        """Verify MySQL registers 9 tools (no analyze_column)."""
        tools = await get_available_tools(mysql_client)

        assert "get_table_relationships" in tools
        assert "analyze_column" not in tools
        assert "explain_query" in tools
        assert "search_objects" in tools
        assert len(tools) == 9

    @pytest.mark.asyncio
    @pytest.mark.clickhouse
    async def test_clickhouse_registers_9_tools(self, ch_client: ClientSession):
        """Verify ClickHouse registers 9 tools (no get_table_relationships)."""
        tools = await get_available_tools(ch_client)

        assert "get_table_relationships" not in tools
        assert "analyze_column" in tools
        assert "explain_query" in tools
        assert "search_objects" in tools
        assert len(tools) == 9


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.postgresql
class TestMCPErrorHandling:
    """Test error handling across MCP tools."""

    @pytest.mark.asyncio
    async def test_invalid_tool_name(self, pg_client: ClientSession):
        """Test calling a non-existent tool."""
        response = await pg_client.call_tool("non_existent_tool", arguments={})
        assert response.isError

    @pytest.mark.asyncio
    async def test_missing_required_argument(self, pg_client: ClientSession):
        """Test calling tool with missing required argument."""
        response = await pg_client.call_tool("describe_table", arguments={})
        assert response.isError

    @pytest.mark.asyncio
    async def test_invalid_query_syntax(self, pg_client: ClientSession):
        """Test execute_query with invalid SQL syntax."""
        response = await pg_client.call_tool(
            "execute_query", arguments={"query": "SELEKT * FORM products"}
        )
        assert response.isError

    @pytest.mark.asyncio
    async def test_recovery_after_error(self, pg_client: ClientSession):
        """Test that server recovers after an error."""
        # Trigger an error
        error_response = await pg_client.call_tool(
            "describe_table", arguments={"table": "nonexistent_xyz123"}
        )
        assert error_response.isError

        # Server should still work
        data = await call_tool_checked(pg_client, "get_database_info", {})
        assert data["dialect"] == "postgresql"


# ============================================================================
# Data Serialization Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.postgresql
class TestMCPDataSerialization:
    """Test data serialization through MCP protocol."""

    @pytest.mark.asyncio
    async def test_all_postgresql_types(self, pg_client: ClientSession):
        """Test serialization of all PostgreSQL data types."""
        data = await call_tool_checked(
            pg_client, "sample_data", {"table": "data_type_examples", "limit": 5}
        )

        for row in data["rows"]:
            json_str = json.dumps(row)
            assert len(json_str) > 0

    @pytest.mark.asyncio
    async def test_null_values(self, pg_client: ClientSession):
        """Test that NULL values are properly serialized."""
        data = await call_tool_checked(
            pg_client,
            "execute_query",
            {"query": "SELECT NULL as null_val, 1 as int_val, NULL::TEXT as null_text"},
        )

        row = data["rows"][0]
        assert row["null_val"] is None
        assert row["int_val"] == 1
        assert row["null_text"] is None

    @pytest.mark.asyncio
    async def test_large_text_handling(self, pg_client: ClientSession):
        """Test that large text values are handled."""
        large_text = "x" * 10000
        data = await call_tool_checked(
            pg_client,
            "execute_query",
            {"query": f"SELECT '{large_text}' as large_text"},
        )

        assert data["row_count"] == 1
        assert isinstance(data["rows"][0]["large_text"], str)


# ============================================================================
# Response Truncation Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.postgresql
class TestMCPResponseTruncation:
    """Test response size limits and truncation behavior."""

    @pytest.mark.asyncio
    async def test_describe_table_handles_long_comments(self, pg_client: ClientSession):
        """Test describe_table handles long comments."""
        response = await pg_client.call_tool(
            "describe_table",
            arguments={"table": "data_type_examples", "schema": "public"},
        )

        raw_data = MCPProtocolHelper.parse_text_content(response.content)
        data = raw_data.get("data", raw_data)
        assert data["name"] == "data_type_examples"

    @pytest.mark.asyncio
    async def test_sample_data_row_size_reasonable(self, pg_client: ClientSession):
        """Test sample_data keeps row sizes reasonable."""
        data = await call_tool_checked(
            pg_client, "sample_data", {"table": "data_type_examples", "limit": 10}
        )

        for row in data["rows"]:
            row_json = json.dumps(row)
            assert len(row_json) < 100000


# ============================================================================
# Sequential Request Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.postgresql
class TestMCPSequentialRequests:
    """Test sequential MCP requests."""

    @pytest.mark.asyncio
    async def test_multiple_queries_same_connection(self, pg_client: ClientSession):
        """Test multiple sequential queries on same connection."""
        for i in range(5):
            data = await call_tool_checked(
                pg_client, "execute_query", {"query": f"SELECT {i} as num"}
            )
            assert data["rows"][0]["num"] == i

    @pytest.mark.asyncio
    async def test_different_tools_sequential(self, pg_client: ClientSession):
        """Test calling different tools sequentially."""
        tools_to_test = [
            ("get_database_info", {}),
            ("list_schemas", {}),
            ("list_tables", {"schema": "public"}),
            ("execute_query", {"query": "SELECT 1"}),
        ]

        for tool_name, args in tools_to_test:
            data = await call_tool_checked(pg_client, tool_name, args)
            assert data is not None
