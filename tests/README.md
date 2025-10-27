# Database Adapter Tests

This directory contains integration tests for the different database adapters supported by the Multi-Database MCP Server.

## Available Tests

- `test_psql_server.py` - Tests PostgreSQL adapter functionality
- `test_clickhouse_server.py` - Tests ClickHouse adapter functionality

## Prerequisites

### Environment Variables

The tests require specific database connection URLs to be set in your `.env` file:

```bash
# PostgreSQL test database
PG_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/test_db

# ClickHouse test database
CH_TEST_DATABASE_URL=clickhouse+asynch://user:pass@localhost:9000/test_db
```

### Database Setup

1. **PostgreSQL**: Ensure you have a PostgreSQL database running and accessible
2. **ClickHouse**: Ensure you have a ClickHouse database running and accessible

The tests are read-only and will not modify any data in your databases.

## Running Tests

### PostgreSQL Test
```bash
# Run with Python
python tests/test_psql_server.py

# Or with uv
uv run python tests/test_psql_server.py
```

### ClickHouse Test
```bash
# Run with Python
python tests/test_clickhouse_server.py

# Or with uv
uv run python tests/test_clickhouse_server.py
```

## Test Coverage

Each test verifies:

1. **Connection**: Database connectivity and version detection
2. **Metadata Inspector**:
   - Schema listing
   - Table listing with metadata
   - Detailed table structure (columns, indexes, constraints)
   - Foreign key relationships (where supported)
3. **Statistics Analyzer**:
   - Column statistics and profiling
   - Data sampling
4. **Database Capabilities**: Verification of supported features
5. **Read-only Mode**: Ensures safe, non-destructive access

## Known Issues

### ClickHouse asynch Driver Compatibility

There is a known compatibility issue between `clickhouse-sqlalchemy 0.3.2` and `asynch 0.3.0` that may prevent successful connection. The error manifests as:

```
AttributeError: module 'asynch' has no attribute 'connect'
```

**Workarounds:**
1. The test script gracefully handles this error and reports it as a known issue
2. Consider using a different version combination of the libraries
3. Use the synchronous driver for testing purposes

### Windows Event Loop Issues

On Windows, the tests set appropriate event loop policies:
- PostgreSQL test uses `WindowsSelectorEventLoopPolicy` for asyncpg compatibility
- ClickHouse test uses `WindowsSelectorEventLoopPolicy` as well

## Test Output

Successful tests will display:
- `[OK]` for passed checks
- `[INFO]` for informational messages
- `[WARNING]` for non-critical issues
- `[ERROR]` for test failures

The tests exit with code 0 on success and 1 on failure.

## Adding New Tests

When adding tests for new database adapters:

1. Create a new test file: `test_<database>_server.py`
2. Follow the pattern established in existing tests
3. Add the corresponding environment variable (e.g., `<DB>_TEST_DATABASE_URL`)
4. Update this README with the new test information
5. Handle any database-specific quirks or limitations gracefully

## Debugging

To enable SQL query logging during tests, set the `echo_sql` parameter in the DatabaseConfig:

```python
config = DatabaseConfig(url=database_url, echo_sql=True)
```

This will print all SQL queries executed during the test run.