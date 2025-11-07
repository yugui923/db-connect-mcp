# Test Suite

This directory contains the pytest-based test suite for the db-connect-mcp project.

## Structure

```
tests/
├── conftest.py              # Shared fixtures and pytest configuration
├── test_postgresql.py       # PostgreSQL adapter tests
├── test_clickhouse.py       # ClickHouse adapter tests
├── test_psql_server.py      # Legacy PostgreSQL test (deprecated)
├── test_clickhouse_server.py # Legacy ClickHouse test (deprecated)
└── README.md               # This file
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
# Using uv
uv run pytest

# Using pytest directly
pytest
```

### Run Specific Database Tests

```bash
# PostgreSQL tests only
pytest -m postgresql

# ClickHouse tests only
pytest -m clickhouse

# Exclude integration tests
pytest -m "not integration"
```

### Run Specific Test Files

```bash
# Run PostgreSQL tests
pytest tests/test_postgresql.py

# Run ClickHouse tests
pytest tests/test_clickhouse.py
```

### Run Specific Test Classes or Functions

```bash
# Run a specific test class
pytest tests/test_postgresql.py::TestPostgreSQLConfiguration

# Run a specific test function
pytest tests/test_postgresql.py::TestPostgreSQLConfiguration::test_config_creation
```

### Verbose Output

```bash
# Show detailed output
pytest -v

# Show even more details (including local variables on failure)
pytest -vv --showlocals
```

### Fast Mode (Skip Slow Tests)

```bash
# Skip tests marked as slow
pytest -m "not slow"
```

## Test Markers

Tests are organized using pytest markers:

- **`postgresql`**: PostgreSQL-specific tests
- **`clickhouse`**: ClickHouse-specific tests
- **`mysql`**: MySQL-specific tests
- **`integration`**: Integration tests requiring database connection
- **`slow`**: Slow-running tests (>5 seconds)

### Using Markers

```bash
# Run only PostgreSQL tests
pytest -m postgresql

# Run only integration tests
pytest -m integration

# Run PostgreSQL tests but skip slow ones
pytest -m "postgresql and not slow"

# Run all tests except integration tests
pytest -m "not integration"
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
start htmlcov/index.html  # Windows
```

### Coverage Configuration

Coverage settings are configured in `pyproject.toml` under `[tool.coverage.*]`.

## Test Structure

### Fixtures (conftest.py)

Shared fixtures are defined in `conftest.py`:

- **Configuration fixtures**: `pg_config`, `ch_config`, `mysql_config`
- **Adapter fixtures**: `pg_adapter`, `ch_adapter`
- **Connection fixtures**: `pg_connection`, `ch_connection` (with automatic cleanup)
- **Inspector fixtures**: `pg_inspector`, `ch_inspector`
- **Analyzer fixtures**: `pg_analyzer`, `ch_analyzer`
- **Parametrized fixtures**: `db_config`, `db_adapter`, `db_connection` (work across all databases)

### Test Organization

Tests are organized into classes by functionality:

```python
class TestPostgreSQLConfiguration:
    """Configuration and setup tests"""

class TestPostgreSQLConnection:
    """Connection and basic query tests"""

class TestPostgreSQLMetadata:
    """Metadata inspection tests"""

class TestPostgreSQLStatistics:
    """Statistics and analysis tests"""

class TestPostgreSQLIntegration:
    """End-to-end integration tests"""
```

### Writing New Tests

#### Basic Test Structure

```python
import pytest

pytestmark = [pytest.mark.postgresql, pytest.mark.integration]

class TestNewFeature:
    async def test_something(self, pg_connection):
        """Test description"""
        # Arrange
        ...

        # Act
        result = await some_function()

        # Assert
        assert result is not None
        assert result.value == expected
```

#### Using Fixtures

```python
async def test_with_fixtures(
    pg_connection: DatabaseConnection,
    pg_inspector: MetadataInspector,
    pg_analyzer: StatisticsAnalyzer,
):
    """Fixtures are automatically injected"""
    schemas = await pg_inspector.get_schemas()
    assert len(schemas) > 0
```

#### Skipping Tests

```python
async def test_optional_feature(ch_adapter):
    """Test optional feature"""
    if not ch_adapter.capabilities.some_feature:
        pytest.skip("Feature not supported by this database")

    # Test code...
```

#### Parametrized Tests

```python
@pytest.mark.parametrize("schema_name", ["public", "test_schema"])
async def test_multiple_schemas(pg_inspector, schema_name):
    """Test runs once for each parameter value"""
    tables = await pg_inspector.get_tables(schema_name)
    assert tables is not None
```

## Best Practices

### 1. Use Fixtures for Setup

✅ **Do**: Use fixtures for database connections and components
```python
async def test_something(pg_connection):
    async with pg_connection.get_connection() as conn:
        result = await conn.execute(text("SELECT 1"))
```

❌ **Don't**: Create connections manually in tests
```python
async def test_something():
    config = DatabaseConfig(url=os.getenv("PG_TEST_DATABASE_URL"))
    connection = DatabaseConnection(config)
    await connection.initialize()
    # ... forgot to cleanup!
```

### 2. Use Descriptive Test Names

✅ **Do**: Describe what the test verifies
```python
async def test_get_schemas_returns_list_with_public_schema(pg_inspector):
    ...
```

❌ **Don't**: Use vague names
```python
async def test_schemas(pg_inspector):
    ...
```

### 3. Use Proper Assertions

✅ **Do**: Use pytest assertions with clear expectations
```python
assert result is not None
assert result.total_rows >= 0
assert len(schemas) > 0
```

❌ **Don't**: Use boolean checks or print statements
```python
if result:
    print("[OK] Result exists")
    return True
```

### 4. Mark Slow Tests

```python
@pytest.mark.slow
async def test_analyze_large_table(pg_analyzer):
    """This test takes >5 seconds"""
    ...
```

### 5. Skip Unavailable Tests

```python
async def test_feature(ch_adapter):
    if not ch_adapter.capabilities.foreign_keys:
        pytest.skip("ClickHouse doesn't support foreign keys")
```

### 6. Group Related Tests

```python
class TestMetadataInspection:
    """Group related tests in a class"""

    async def test_get_schemas(self, pg_inspector):
        ...

    async def test_get_tables(self, pg_inspector):
        ...
```

## Known Issues

### ClickHouse asynch Driver Compatibility

Some ClickHouse tests may skip due to known driver compatibility issues:
```
SKIPPED: Known ClickHouse asynch driver compatibility issue
```

This is expected and documented in the codebase. The error manifests as:
```
AttributeError: module 'asynch' has no attribute 'connect'
```

### Windows Event Loop Issues

The test suite handles Windows-specific event loop requirements automatically in `conftest.py`:
```python
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

## Troubleshooting

### Tests Skip Due to Missing Database URL

If you see:
```
SKIPPED [1] tests/conftest.py:XX: PG_TEST_DATABASE_URL not set in environment
```

Solution: Create a `.env` file with the appropriate database URL.

## Legacy Tests

The legacy test files (`test_psql_server.py` and `test_clickhouse_server.py`) are deprecated in favor of the new pytest-based tests. They will be removed in a future version.

To run legacy tests:
```bash
python tests/test_psql_server.py
python tests/test_clickhouse_server.py
```

---

## 🔬 MCP Tools Testing Framework

A comprehensive testing framework specifically for testing all 10 MCP server tool functions against real databases. This framework systematically validates that all MCP tools work correctly with real-world data and data types.

### Why This Framework?

After the comprehensive bug fixes (JSON serialization, SQL syntax errors, missing metadata), this framework ensures:
1. All 10 MCP tools are tested systematically
2. JSON serialization works for all PostgreSQL data types
3. Real-world scenarios are covered (actual tables, actual data)
4. Regressions are caught immediately
5. Test reports show exactly what works and what doesn't

### Test Files

- **`test_mcp_tools.py`** - Comprehensive tests for all 10 MCP tool functions
- **`test_utils.py`** - Testing utilities, report generation, helpers
- **`run_mcp_tests.py`** - Orchestration script for running tests and generating reports

### Quick Start - MCP Tools Tests

```bash
# Run all MCP tool tests with comprehensive reporting
python tests/run_mcp_tests.py

# Run PostgreSQL tests only
python tests/run_mcp_tests.py --database postgresql

# Generate report from last run
python tests/run_mcp_tests.py --report-only

# Verbose output
python tests/run_mcp_tests.py --verbose
```

### What Gets Tested

#### All 10 MCP Tool Functions

1. **`get_database_info`** - Database metadata and capabilities
2. **`list_schemas`** - Schema listing with sizes and counts
3. **`list_tables`** - Table listing with row counts and sizes (Bug Fix #3)
4. **`describe_table`** - Detailed table information with statistics (Bug Fix #4)
5. **`execute_query`** - SQL query execution
6. **`sample_data`** - Data sampling with JSON serialization (Bug Fix #1)
7. **`get_table_relationships`** - Foreign key discovery
8. **`analyze_column`** - Column statistics for numeric and text (Bug Fix #2)
9. **`explain_query`** - Query execution plans with proper JSON format (Bug Fix #5)
10. **`profile_database`** - Database-wide profiling (Bug Fix #6)

#### Data Type Coverage

Tests JSON serialization for all PostgreSQL types:
- **Temporal**: TIMESTAMP, DATE, TIME, INTERVAL
- **Network**: INET, CIDR, MACADDR
- **Special**: UUID, JSON, JSONB, BYTEA, BOOLEAN
- **Numeric**: INTEGER, BIGINT, NUMERIC, REAL, DOUBLE PRECISION
- **Text**: TEXT, VARCHAR, CHAR
- **Geometric**: POINT, LINE, POLYGON
- **Arrays**: INTEGER[], TEXT[]

### Test Reports

Comprehensive Markdown reports are generated in `test_reports/`:

```markdown
# 🔬 MCP Server Comprehensive Test Report

## Executive Summary

| Metric | Count | Percentage |
|--------|-------|------------|
| Total Tests | 15 | 100% |
| ✅ Passed | 15 | 100% |
| ❌ Failed | 0 | 0.0% |

## 🔧 Results by MCP Tool

### ✅ Tool 1: get_database_info
- ✅ test_get_database_info (0.15s)

### ✅ Tool 6: sample_data
- ✅ test_sample_data_json_serialization (0.23s)
```

### Example: Testing sample_data Bug Fix

The `test_sample_data_json_serialization` test validates the fix for Bug #1:

```python
async def test_sample_data_json_serialization(pg_connection, pg_adapter):
    """Test sample_data with various data types - was BROKEN."""
    executor = QueryExecutor(pg_connection, pg_adapter)

    result = await executor.sample_data("gold_users", "public", limit=5)

    # Critical: Verify JSON serialization works
    # This was failing before the fix with:
    # TypeError: Object of type IPv4Address is not JSON serializable
    json_str = json.dumps(result.model_dump())
    assert len(json_str) > 0
```

### Example: Testing analyze_column Bug Fix

The `test_analyze_column_numeric` and `test_analyze_column_text` tests validate Bug #2 fix:

```python
async def test_analyze_column_text(pg_connection, pg_adapter):
    """Test analyze_column with text columns - was BROKEN."""
    analyzer = StatisticsAnalyzer(pg_connection, pg_adapter)

    # This used to fail trying to compute AVG/STDDEV on text
    # Error: column must appear in GROUP BY clause
    stats = await analyzer.analyze_column("users", "country", "public")

    # Text columns should work now
    assert stats.data_type is not None
    assert stats.total_rows >= 0
    assert stats.warning is None  # No SQL errors
```

### Running Specific MCP Tool Tests

```bash
# Test only sample_data function
pytest tests/test_mcp_tools.py::TestMCPTools::test_sample_data_json_serialization -v

# Test only analyze_column functions
pytest tests/test_mcp_tools.py -k "analyze_column" -v

# Test all data type coverage
pytest tests/test_mcp_tools.py::TestDataTypeCoverage -v
```

### Test Utilities

From `test_utils.py`:

**`TestReporter`** - Generate comprehensive Markdown reports:
```python
reporter = TestReporter()
reporter.add_result("sample_data", "test_json", passed=True)
report_path = reporter.save_report("postgresql")
```

**`DataTypeTestHelper`** - Test all PostgreSQL types:
```python
query = DataTypeTestHelper.generate_type_test_query(["INTEGER", "TEXT", "TIMESTAMP"])
# SELECT 42 as col_0, 'text' as col_1, TIMESTAMP '2024-01-15' as col_2
```

**`validate_json_serialization()`** - Check JSON safety:
```python
is_safe, error = validate_json_serialization(result.model_dump())
assert is_safe, f"Not JSON-safe: {error}"
```

**`PerformanceBenchmark`** - Track performance:
```python
benchmark = PerformanceBenchmark()
benchmark.record("sample_data", "5_rows", 123.45)
stats = benchmark.get_stats("sample_data", "5_rows")
```

### Continuous Integration

Add to your CI pipeline:

```yaml
# .github/workflows/test.yml
- name: Run MCP Tools Tests
  run: |
    pip install pytest pytest-asyncio pytest-json-report
    python tests/run_mcp_tests.py
  env:
    PG_TEST_DATABASE_URL: ${{ secrets.PG_TEST_DATABASE_URL }}
```

### Test Matrix for All Databases

The framework supports testing across all database types:

```bash
# Test PostgreSQL
python tests/run_mcp_tests.py --database postgresql

# Test MySQL
python tests/run_mcp_tests.py --database mysql

# Test ClickHouse
python tests/run_mcp_tests.py --database clickhouse

# Test all configured databases
python tests/run_mcp_tests.py
```

### Interpreting Test Failures

#### JSON Serialization Failure
```
❌ test_sample_data_json_serialization
   TypeError: Object of type IPv4Address is not JSON serializable
```
**Fix**: Add type conversion in `src/db_connect_mcp/utils/serialization.py`

#### SQL Syntax Error
```
❌ test_analyze_column_numeric
   ProgrammingError: column must appear in GROUP BY clause
```
**Fix**: Restructure SQL query in adapter's `get_column_statistics()` method

#### Missing Metadata
```
❌ test_list_tables_with_metadata
   AssertionError: row_count should not be NULL
```
**Fix**: Check table enrichment query in adapter's `enrich_table_info()` method

### Coverage Goals

The MCP tools testing framework aims for:
- **100% MCP tool coverage** - All 10 tools tested
- **100% critical data types** - TIMESTAMP, INET, UUID, JSONB, etc.
- **>90% bug detection** - Catches serialization, SQL, metadata issues
- **<2s per test** - Fast enough for CI/CD

---

## Additional Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio documentation](https://pytest-asyncio.readthedocs.io/)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- [Project CLAUDE.md](../CLAUDE.md) - Development guidelines
- [MCP Protocol Specification](https://modelcontextprotocol.io/) - Official MCP docs