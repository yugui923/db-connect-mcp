# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **read-only** Multi-Database MCP (Model Context Protocol) server that provides safe database exploration and analysis capabilities for PostgreSQL, MySQL, and ClickHouse databases. The server enforces read-only access at multiple levels and is designed for exploratory data analysis without risk of data modification.

## Development Commands

### Setup & Installation

```bash
# Install dependencies using uv (preferred)
uv sync

# Or using pip
pip install -e .

# Install dev dependencies for testing
uv sync --dev
```

### Running the Server

```bash
# As a module (recommended - works without PATH configuration)
python -m db_connect_mcp

# Using uv (for development with dependencies)
uv run python -m db_connect_mcp

# For Windows: __main__.py sets WindowsProactorEventLoopPolicy automatically
```

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for detailed development setup.

### Testing

```bash
# Run the PostgreSQL integration test
uv run python tests/test_psql_server.py

# Note: Requires PG_TEST_DATABASE_URL in .env file pointing to a test database
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint
uv run ruff check .

# Type checking
npx pyright
```

## Architecture

### Adapter Pattern

The codebase uses an **adapter pattern** to support multiple database types. Each database has its own adapter that implements the `BaseAdapter` interface:

- **BaseAdapter** (`src/adapters/base.py`): Abstract interface defining all database operations
- **PostgresAdapter** (`src/adapters/postgresql.py`): PostgreSQL-specific implementation
- **MySQLAdapter** (`src/adapters/mysql.py`): MySQL/MariaDB implementation
- **ClickHouseAdapter** (`src/adapters/clickhouse.py`): ClickHouse implementation

The adapter is selected automatically based on the DATABASE_URL dialect via `create_adapter()` factory function.

### Core Components

1. **DatabaseConnection** (`src/core/connection.py`): Manages SQLAlchemy async engine and connection pooling. Enforces read-only at connection level.

2. **MetadataInspector** (`src/core/inspector.py`): Retrieves database metadata (schemas, tables, columns, relationships). Uses database-specific adapter methods for enrichment.

3. **QueryExecutor** (`src/core/executor.py`): Executes read-only SQL queries with validation. Automatically adds limits and validates query safety.

4. **StatisticsAnalyzer** (`src/core/analyzer.py`): Performs column profiling and statistical analysis. Delegates to adapter for database-specific statistics queries.

### MCP Server Integration

The **DatabaseMCPServer** (`src/server.py`) class:

- Initializes all core components with the selected adapter
- Registers MCP tools based on database capabilities
- Routes tool calls to appropriate core components
- Handles connection lifecycle and error management

### Safety Enforcement

Read-only access is enforced at multiple levels:

1. **Connection string modification**: Automatically adds read-only parameters
2. **Session-level settings**: Sets read-only mode on connection
3. **Query validation**: Only SELECT and WITH queries allowed
4. **Automatic limits**: Prevents large result sets

## Database-Specific Considerations

### PostgreSQL

- Requires `asyncpg` driver (specified as `postgresql+asyncpg://`)
- Supports full metadata including foreign keys and constraints
- Uses EXPLAIN ANALYZE for query planning
- Efficient sampling with TABLESAMPLE when available

### MySQL/MariaDB

- Requires `aiomysql` driver (specified as `mysql+aiomysql://`)
- Information schema queries for metadata
- Character set handling (default utf8mb4)
- Storage engine information available

### ClickHouse

- Requires `asynch` driver (specified as `clickhouse+asynch://`)
- Limited support for foreign keys and constraints
- Optimized for analytical workloads
- Special handling for distributed tables

## Configuration

The server reads configuration from environment variables:

- **DATABASE_URL** (required): Connection string with appropriate async driver
- **DB_POOL_SIZE** (optional): Connection pool size (default: 5)
- **DB_MAX_OVERFLOW** (optional): Max overflow connections (default: 10)
- **DB_POOL_TIMEOUT** (optional): Pool timeout in seconds (default: 30)

Example .env file provided in `.env.example`.

## MCP Tool Registration

Tools are registered in `src/server.py` and include:

- `get_database_info`: Database version and capabilities
- `list_schemas`: List all schemas
- `list_tables`: List tables with metadata
- `describe_table`: Detailed table structure
- `analyze_column`: Column statistics and distribution
- `sample_data`: Preview table data
- `execute_query`: Run read-only SQL
- `get_table_relationships`: Foreign key relationships

Tools are conditionally registered based on database capabilities from the adapter.

## Error Handling

The server implements comprehensive error handling:

- Connection errors are caught and logged with helpful messages
- Query validation errors provide specific feedback
- Database-specific errors are translated to user-friendly messages
- All errors maintain the read-only guarantee

## Windows Compatibility

The project includes Windows-specific handling:

- `src/db_connect_mcp/__main__.py` sets `WindowsProactorEventLoopPolicy` for async operations
- Test files set `WindowsSelectorEventLoopPolicy` for asyncpg compatibility
- Path handling uses `pathlib.Path` for cross-platform support
- Console script `db-connect-mcp` is automatically registered in pyproject.toml

## Additional Documentation

- **[Development Guide](docs/DEVELOPMENT.md)** - Complete development environment setup, testing, and contribution guidelines
- **[Test Guide](tests/README.md)** - Detailed testing documentation and best practices
- **[README.md](README.md)** - User-facing documentation and usage examples
