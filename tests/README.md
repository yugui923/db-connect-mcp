# Test Suite

This directory contains the comprehensive pytest-based test suite for the db-connect-mcp project.

## Test Structure

The test suite is organized into three main layers:

### 1. **Integration Tests** (`integration/`)

End-to-end tests that test the full MCP server implementation and complete workflows.

#### `integration/test_mcp_protocol.py`
Tests the MCP protocol layer including:
- Server initialization and lifecycle
- MCP tool registration based on database capabilities
- Tool input validation via JSON schemas
- Tool calls through the actual MCP protocol using ClientSession
- Response serialization to MCP TextContent format
- Error handling at the protocol layer

**Purpose**: Catch errors that only appear when running the actual MCP server with a real MCP client connection.

#### `integration/test_mcp_workflows.py`
Tests complete end-to-end workflows:
- Multi-step database exploration (get info → list schemas → list tables → describe)
- Query and analysis workflows
- Database profiling workflows
- Error recovery and handling

**Purpose**: Validate real-world usage patterns and multi-step operations.

### 2. **Module Tests** (`module/`)

Tests individual core components directly without MCP protocol overhead.

#### `module/test_inspector.py`
Tests `MetadataInspector` component:
- Schema listing with metadata
- Table listing with enriched metadata (row counts, sizes)
- Table description with columns, indexes, constraints
- Table relationship discovery (foreign keys)
- Edge cases and error handling

#### `module/test_executor.py`
Tests `QueryExecutor` component:
- Query execution with validation
- Data sampling from tables
- Read-only enforcement
- Query result serialization (all data types)
- EXPLAIN query functionality
- Edge cases (empty results, NULL values, syntax errors)

#### `module/test_analyzer.py`
Tests `StatisticsAnalyzer` component:
- Column statistics for numeric columns
- Column statistics for text columns
- Database profiling
- Edge cases (non-existent columns, all-NULL columns)

**Purpose**: Test business logic and database interaction without MCP protocol overhead. Fast, focused tests for core functionality.

### 3. **Unit Tests** (`unit/`)

Tests isolated components, utilities, and database adapters.

#### `unit/adapters/`
Database adapter tests:
- `test_postgresql_adapter.py` - PostgreSQL-specific implementation
- `test_clickhouse_adapter.py` - ClickHouse-specific implementation

Tests:
- Adapter configuration and capabilities
- Connection management
- Database-specific SQL generation
- Metadata enrichment

#### `unit/test_serialization.py`
Tests JSON serialization for all database types:
- Temporal types (TIMESTAMP, DATE, TIME, INTERVAL)
- Network types (INET, CIDR, MACADDR)
- Special types (UUID, JSON, JSONB, BYTEA)
- Numeric types, geometric types, arrays
- Edge cases and compatibility

**Purpose**: Prevent JSON serialization errors when returning data to MCP clients.

#### `unit/test_utils.py`
Tests supporting utilities:
- Test reporters
- Data type helpers
- Performance benchmarking

## Directory Structure

```
tests/
├── conftest.py                        # Shared fixtures and pytest configuration
├── integration/                       # Integration-level tests
│   ├── __init__.py
│   ├── test_mcp_protocol.py          # MCP protocol layer testing
│   └── test_mcp_workflows.py         # End-to-end workflow testing
├── module/                            # Module-level tests
│   ├── __init__.py
│   ├── test_analyzer.py              # StatisticsAnalyzer tests
│   ├── test_executor.py              # QueryExecutor tests
│   └── test_inspector.py             # MetadataInspector tests
├── unit/                              # Unit-level tests
│   ├── __init__.py
│   ├── adapters/                      # Database adapter tests
│   │   ├── __init__.py
│   │   ├── test_clickhouse_adapter.py
│   │   └── test_postgresql_adapter.py
│   ├── test_serialization.py          # JSON serialization tests
│   └── test_utils.py                  # Utility tests
└── README.md                          # This file
```

## Setup

### Install Test Dependencies

```bash
# Install all dependencies including dev dependencies
uv sync --dev

# Or using pip
pip install -e ".[dev]"
```

### Configure Test Databases

Create a `.env` file in the project root with your test database URLs:

```bash
# PostgreSQL
PG_TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/testdb

# ClickHouse
CH_TEST_DATABASE_URL=clickhouse+asynch://user:password@localhost:9000/testdb

# MySQL (optional)
MYSQL_TEST_DATABASE_URL=mysql+aiomysql://user:password@localhost:3306/testdb
```

**Note**: Tests will be skipped if the corresponding database URL is not configured.

## Running Tests

### Run All Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src --cov-report=html
```

### Run Tests by Layer

```bash
# Run integration tests only
pytest tests/integration/ -v

# Run module tests only
pytest tests/module/ -v

# Run unit tests only
pytest tests/unit/ -v
```

### Run Specific Test Files

```bash
# Run MCP protocol tests
pytest tests/integration/test_mcp_protocol.py -v

# Run executor module tests
pytest tests/module/test_executor.py -v

# Run PostgreSQL adapter tests
pytest tests/unit/adapters/test_postgresql_adapter.py -v
```

### Run Tests by Database

```bash
# PostgreSQL tests only
pytest -m postgresql

# ClickHouse tests only
pytest -m clickhouse

# MySQL tests only
pytest -m mysql
```

### Run Tests by Type

```bash
# Integration tests
pytest -m integration

# Exclude integration tests
pytest -m "not integration"

# Skip slow tests
pytest -m "not slow"
```

## Test Markers

Tests use pytest markers for organization:

- **`postgresql`**: PostgreSQL-specific tests
- **`clickhouse`**: ClickHouse-specific tests
- **`mysql`**: MySQL-specific tests
- **`integration`**: Integration tests requiring database connection
- **`slow`**: Slow-running tests (>5 seconds)

### Using Markers

```bash
# Run only PostgreSQL tests
pytest -m postgresql

# Run integration tests
pytest -m integration

# Run PostgreSQL integration tests
pytest -m "postgresql and integration"

# Run fast tests only
pytest -m "not slow"
```

## Test Fixtures

Shared fixtures are defined in `conftest.py`:

### Configuration Fixtures
- `pg_config`, `ch_config`, `mysql_config` - Database configurations
- `pg_database_url`, `ch_database_url`, `mysql_database_url` - Connection URLs

### Component Fixtures
- `pg_adapter`, `ch_adapter` - Database adapters
- `pg_connection`, `ch_connection` - Database connections (with automatic cleanup)
- `pg_inspector`, `ch_inspector` - Metadata inspectors
- `pg_analyzer`, `ch_analyzer` - Statistics analyzers
- `pg_mcp_server` - MCP server for protocol testing

### Parametrized Fixtures
- `db_config`, `db_adapter`, `db_connection` - Work across all databases

## Best Practices

### 1. Use Appropriate Test Layer

- **Integration tests**: Test MCP protocol, end-to-end workflows, multi-tool interactions
- **Module tests**: Test individual components, business logic, database operations
- **Unit tests**: Test utilities, serialization, adapter-specific logic

### 2. Use Fixtures for Setup

✅ **Do**: Use fixtures for database connections and components
```python
async def test_something(pg_connection, pg_inspector):
    schemas = await pg_inspector.get_schemas()
    assert len(schemas) > 0
```

❌ **Don't**: Create connections manually in tests

### 3. Use Descriptive Test Names

```python
async def test_execute_query_enforces_read_only_mode(self, pg_connection, pg_adapter):
    """Test that write queries are rejected."""
    ...
```

### 4. Skip When Necessary

```python
async def test_feature(ch_adapter):
    if not ch_adapter.capabilities.foreign_keys:
        pytest.skip("ClickHouse doesn't support foreign keys")
```

### 5. Test Edge Cases

Always test:
- Empty results
- NULL values
- Non-existent resources
- Invalid inputs
- Error conditions

## Troubleshooting

### Tests Skip Due to Missing Database URL

If you see:
```
SKIPPED: PG_TEST_DATABASE_URL not set in environment
```

**Solution**: Create a `.env` file with the appropriate database URL.

### Database Connection Failures

If tests are skipped due to connection errors:
```
SKIPPED: PostgreSQL database connection failed: [Errno -3] Temporary failure in name resolution
```

**Solution**:
1. Check that your database is running
2. Verify the connection URL is correct
3. Check network connectivity
4. Ensure firewall rules allow connections

### Windows Event Loop Issues

The test suite handles Windows-specific event loop requirements automatically in `conftest.py`:
```python
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

## Test Coverage

### Generate Coverage Report

```bash
# Run tests with coverage
pytest --cov=src --cov-report=term-missing

# Generate HTML coverage report
pytest --cov=src --cov-report=html

# Open HTML report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Coverage Goals

- **Integration tests**: 100% MCP tool coverage, key workflow paths
- **Module tests**: >90% coverage of core components
- **Unit tests**: >95% coverage of adapters, utilities, serialization

## Writing New Tests

### Example Integration Test

```python
# tests/integration/test_mcp_protocol.py

@pytest.mark.asyncio
async def test_new_mcp_tool(self, pg_config: DatabaseConfig):
    """Test new MCP tool via protocol."""
    server, client = await MCPProtocolHelper.create_test_server_and_client(pg_config)

    try:
        response = await client.call_tool("new_tool", arguments={})
        data = MCPProtocolHelper.check_and_parse_response(response)

        assert "expected_field" in data
    finally:
        await server.cleanup()
```

### Example Module Test

```python
# tests/module/test_executor.py

@pytest.mark.asyncio
async def test_new_executor_feature(
    self, pg_connection: DatabaseConnection, pg_adapter: BaseAdapter
):
    """Test new QueryExecutor feature."""
    executor = QueryExecutor(pg_connection, pg_adapter)

    result = await executor.new_feature()

    assert result is not None
    assert result.field == expected_value
```

### Example Unit Test

```python
# tests/unit/test_serialization.py

def test_new_data_type():
    """Test serialization of new data type."""
    data = {"field": NewDataType(...)}

    json_bytes = orjson.dumps(data, default=str)
    result = orjson.loads(json_bytes)

    assert result["field"] == expected_string
```

## Continuous Integration

The test suite is designed for CI/CD pipelines:

```yaml
# .github/workflows/test.yml
- name: Run Tests
  run: |
    uv sync --dev
    pytest --cov=src --cov-report=xml
  env:
    PG_TEST_DATABASE_URL: ${{ secrets.PG_TEST_DATABASE_URL }}
```

## Additional Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio documentation](https://pytest-asyncio.readthedocs.io/)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- [Project CLAUDE.md](../CLAUDE.md) - Development guidelines
- [MCP Protocol Specification](https://modelcontextprotocol.io/) - Official MCP docs
