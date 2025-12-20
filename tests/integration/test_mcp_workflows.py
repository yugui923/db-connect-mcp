"""End-to-End MCP Workflow Integration Tests

Tests complete workflows using the MCP protocol, simulating real-world usage patterns.
These tests validate:
- Multi-step database exploration workflows
- Query and analysis workflows
- Error recovery and handling
- Performance and reliability

These tests use in-memory MCP client-server connections to test complete workflows.
"""

import pytest

from db_connect_mcp.models.config import DatabaseConfig
from .test_mcp_protocol import MCPProtocolHelper

# Mark all tests in this module for integration testing
pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.integration,
    pytest.mark.xdist_group(name="mcp_workflows"),
]


class TestDatabaseExplorationWorkflow:
    """Test end-to-end database exploration workflows."""

    @pytest.mark.asyncio
    async def test_full_workflow_explore_database(self, pg_config: DatabaseConfig):
        """Test a complete workflow: get info -> list schemas -> list tables -> describe table."""
        server, client = await MCPProtocolHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # 1. Get database info
            info_response = await client.call_tool("get_database_info", arguments={})
            info = MCPProtocolHelper.check_and_parse_response(info_response)
            assert "dialect" in info
            assert info["dialect"] == "postgresql"

            # 2. List schemas
            schemas_response = await client.call_tool("list_schemas", arguments={})
            schemas = MCPProtocolHelper.check_and_parse_response(schemas_response)
            assert len(schemas) > 0

            # 3. List tables in first schema
            schema_name = schemas[0]["name"]
            tables_response = await client.call_tool(
                "list_tables", arguments={"schema": schema_name}
            )
            tables = MCPProtocolHelper.check_and_parse_response(tables_response)

            if tables:
                # 4. Describe first table
                table_name = tables[0]["name"]
                describe_response = await client.call_tool(
                    "describe_table",
                    arguments={"table": table_name, "schema": schema_name},
                )
                table_info = MCPProtocolHelper.parse_text_content(
                    describe_response.content
                )

                assert table_info["name"] == table_name
                assert "columns" in table_info
                assert len(table_info["columns"]) > 0

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_workflow_discover_relationships(self, pg_config: DatabaseConfig):
        """Test workflow for discovering table relationships."""
        server, client = await MCPProtocolHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # 1. List tables
            tables_response = await client.call_tool(
                "list_tables", arguments={"schema": "public"}
            )
            tables = MCPProtocolHelper.check_and_parse_response(tables_response)

            if not tables:
                pytest.skip("No tables available for relationship testing")

            # 2. Check relationships for each table
            for table in tables[:5]:  # Check first 5 tables
                table_name = table["name"]

                # Get relationships
                rel_response = await client.call_tool(
                    "get_table_relationships",
                    arguments={"table": table_name, "schema": "public"},
                )
                relationships = MCPProtocolHelper.check_and_parse_response(rel_response)

                if relationships and len(relationships) > 0:
                    # Validate relationship structure
                    rel = relationships[0]
                    assert "from_table" in rel
                    assert "to_table" in rel
                    assert "from_columns" in rel
                    assert "to_columns" in rel
                    break

            # Note: Not all databases have relationships, so we just verify the workflow works

        finally:
            await server.cleanup()


class TestQueryAndAnalysisWorkflow:
    """Test query execution and analysis workflows."""

    @pytest.mark.asyncio
    async def test_full_workflow_query_and_analyze(self, pg_config: DatabaseConfig):
        """Test workflow: query data -> analyze results -> explain plan."""
        server, client = await MCPProtocolHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # 1. Execute a query
            query_response = await client.call_tool(
                "execute_query",
                arguments={
                    "query": "SELECT 1 as num, 'text' as txt",
                    "limit": 10,
                },
            )
            result = MCPProtocolHelper.check_and_parse_response(query_response)

            assert result["row_count"] == 1
            assert result["columns"] == ["num", "txt"]

            # 2. Get execution plan
            if server.adapter.capabilities.explain_plans:
                explain_response = await client.call_tool(
                    "explain_query",
                    arguments={"query": "SELECT 1", "analyze": False},
                )
                plan = MCPProtocolHelper.check_and_parse_response(explain_response)

                assert "query" in plan
                assert "plan" in plan

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_workflow_sample_and_analyze_column(self, pg_config: DatabaseConfig):
        """Test workflow: sample data -> analyze column statistics."""
        server, client = await MCPProtocolHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # 1. Get tables
            tables_response = await client.call_tool(
                "list_tables", arguments={"schema": "public"}
            )
            tables = MCPProtocolHelper.check_and_parse_response(tables_response)

            if not tables:
                pytest.skip("No tables available for testing")

            table_name = tables[0]["name"]

            # 2. Sample data from the table
            sample_response = await client.call_tool(
                "sample_data",
                arguments={"table": table_name, "schema": "public", "limit": 5},
            )
            sample_data = MCPProtocolHelper.check_and_parse_response(sample_response)

            assert "columns" in sample_data
            assert len(sample_data["columns"]) > 0

            if not sample_data["columns"]:
                pytest.skip("Table has no columns")

            # 3. Analyze a column if advanced_stats is supported
            if server.adapter.capabilities.advanced_stats:
                column_name = sample_data["columns"][0]

                analyze_response = await client.call_tool(
                    "analyze_column",
                    arguments={
                        "table": table_name,
                        "column": column_name,
                        "schema": "public",
                    },
                )
                stats = MCPProtocolHelper.check_and_parse_response(analyze_response)

                assert "column" in stats
                assert stats["column"] == column_name
                assert "total_rows" in stats
                assert "null_count" in stats

        finally:
            await server.cleanup()


class TestDatabaseProfilingWorkflow:
    """Test database profiling workflows."""


class TestErrorRecoveryWorkflow:
    """Test error handling and recovery in workflows."""

    @pytest.mark.asyncio
    async def test_workflow_invalid_query_recovery(self, pg_config: DatabaseConfig):
        """Test that invalid query doesn't break subsequent queries."""
        server, client = await MCPProtocolHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # 1. Try an invalid query (write operation)
            invalid_response = await client.call_tool(
                "execute_query",
                arguments={"query": "DROP TABLE nonexistent", "limit": 10},
            )
            assert invalid_response.isError

            # 2. Verify server still works with valid query
            valid_response = await client.call_tool(
                "execute_query",
                arguments={"query": "SELECT 1", "limit": 10},
            )
            data = MCPProtocolHelper.check_and_parse_response(valid_response)
            assert data["row_count"] == 1

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_workflow_nonexistent_table_recovery(self, pg_config: DatabaseConfig):
        """Test that querying nonexistent table doesn't break server."""
        server, client = await MCPProtocolHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # 1. Try to describe nonexistent table
            invalid_response = await client.call_tool(
                "describe_table",
                arguments={
                    "table": "nonexistent_table_xyz",
                    "schema": "public",
                },
            )
            # Should return error
            assert invalid_response.isError

            # 2. Verify server still works
            valid_response = await client.call_tool("list_schemas", arguments={})
            schemas = MCPProtocolHelper.check_and_parse_response(valid_response)
            assert len(schemas) > 0

        finally:
            await server.cleanup()


class TestComplexQueryWorkflow:
    """Test workflows with complex queries."""

    @pytest.mark.asyncio
    async def test_workflow_complex_query_with_joins(self, pg_config: DatabaseConfig):
        """Test complex query workflow with CTEs and expressions."""
        server, client = await MCPProtocolHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # 1. Execute a CTE query
            cte_query = """
            WITH sample AS (
                SELECT 1 as id, 'test' as name
                UNION ALL
                SELECT 2, 'test2'
            )
            SELECT * FROM sample
            """

            query_response = await client.call_tool(
                "execute_query",
                arguments={"query": cte_query, "limit": 10},
            )
            result = MCPProtocolHelper.check_and_parse_response(query_response)

            assert result["row_count"] == 2
            assert "id" in result["columns"]
            assert "name" in result["columns"]

            # 2. Explain the query if supported
            if server.adapter.capabilities.explain_plans:
                explain_response = await client.call_tool(
                    "explain_query",
                    arguments={"query": cte_query, "analyze": False},
                )
                plan = MCPProtocolHelper.check_and_parse_response(explain_response)

                assert "query" in plan
                assert "plan" in plan

        finally:
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_workflow_query_with_various_data_types(
        self, pg_config: DatabaseConfig
    ):
        """Test query workflow with various PostgreSQL data types."""
        server, client = await MCPProtocolHelper.create_test_server_and_client(
            pg_config
        )

        try:
            # Query with various data types
            complex_query = """
            SELECT
                1::INTEGER as int_col,
                'text'::TEXT as text_col,
                3.14::NUMERIC as numeric_col,
                TRUE::BOOLEAN as bool_col,
                NOW()::TIMESTAMP as timestamp_col,
                CURRENT_DATE::DATE as date_col,
                '192.168.1.1'::INET as inet_col,
                gen_random_uuid() as uuid_col
            """

            query_response = await client.call_tool(
                "execute_query",
                arguments={"query": complex_query, "limit": 1},
            )
            result = MCPProtocolHelper.check_and_parse_response(query_response)

            assert result["row_count"] == 1
            row = result["rows"][0]

            # Verify all types are properly serialized
            assert row["int_col"] == 1
            assert row["text_col"] == "text"
            assert isinstance(row["numeric_col"], (str, int, float))
            assert row["bool_col"] is True
            assert isinstance(row["timestamp_col"], str)
            assert isinstance(row["date_col"], str)
            assert isinstance(row["inet_col"], str)
            assert isinstance(row["uuid_col"], str)

        finally:
            await server.cleanup()
