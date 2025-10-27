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

## Additional Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio documentation](https://pytest-asyncio.readthedocs.io/)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- [Project CLAUDE.md](../CLAUDE.md) - Development guidelines