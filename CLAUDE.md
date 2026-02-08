# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **read-only** Multi-Database MCP (Model Context Protocol) server that provides safe database exploration and analysis capabilities for PostgreSQL, MySQL, and ClickHouse databases. The server enforces read-only access at multiple levels and is designed for exploratory data analysis without risk of data modification.

## Pre-Commit Requirements

**IMPORTANT:** Before every commit and push, ALL of the following checks must pass:

```bash
# 1. Format code
uv run ruff format .

# 2. Lint code
uv run ruff check .

# 3. Type checking
npx pyright

# 4. Run all tests
uv run pytest -n 6
```

Do NOT commit or push if any of these checks fail. Fix all issues first.

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

See [docs/guides/DEVELOPMENT.md](docs/guides/DEVELOPMENT.md) for detailed development setup.

### Testing

**IMPORTANT:** Always run tests with **6 parallel workers** (`-n 6`) for optimal performance.

```bash
# Start local test database (PostgreSQL 17 with sample data)
cd tests/docker && docker-compose up -d && cd ../..

# Run all tests in parallel (preferred - 6 workers)
uv run pytest -n 6

# Run specific test modules in parallel
uv run pytest tests/module/test_inspector.py -v -n 6
uv run pytest tests/integration/ -v -n 6

# Stop test database
cd tests/docker && docker-compose down && cd ../..

# Reset database (clean slate with fresh data)
cd tests/docker && docker-compose down -v && docker-compose up -d && cd ../..
```

**Local Test Database:**

- PostgreSQL 17 with 50K+ rows of sample data across 7 tables
- Automatically initialized via Docker Compose
- No cloud database or .env configuration required
- See [Docker Setup](docs/guides/DOCKER.md) for details

**Performance Notes:**

- With database running: `-n 6` provides ~4-5x speedup
- Without database (tests skipped): Sequential is faster due to worker overhead
- Always use `-n 6` when running the full test suite with database

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

## SSH Tunnel Support

The server supports connecting to databases through SSH tunnels, enabling secure access to databases that are not directly reachable (e.g., behind firewalls or in private networks).

### Core Components

- **SSHTunnelManager** (`src/core/tunnel.py`): Manages the SSH tunnel lifecycle (start, stop, health checks, context manager support). Uses the `sshtunnel` library with `paramiko` (pinned `<4.0.0` for compatibility).
- **SSHTunnelConfig** (`src/models/config.py`): Pydantic model for SSH tunnel configuration — SSH host/port, authentication (password or private key), remote/local bind addresses.
- **DatabaseConnection integration** (`src/core/connection.py`): When `ssh_tunnel` is set on `DatabaseConfig`, the connection automatically establishes the tunnel during `initialize()`, rewrites the database URL to point at the local tunnel endpoint, and tears down the tunnel on `dispose()`.
- **`rewrite_database_url()`** (`src/core/tunnel.py`): Rewrites any database URL (PostgreSQL, MySQL, ClickHouse) to route through the tunnel's local bind port.

### Configuration

SSH tunnel is configured via `SSHTunnelConfig` on `DatabaseConfig.ssh_tunnel`:

| Field | Default | Description |
| ----- | ------- | ----------- |
| `ssh_host` | (required) | SSH server hostname |
| `ssh_port` | `22` | SSH server port |
| `ssh_username` | (required) | SSH username |
| `ssh_password` | (optional) | Password authentication |
| `ssh_private_key` | (optional) | SSH private key content (raw PEM or base64-encoded PEM) |
| `ssh_private_key_path` | (optional) | Path to private key file |
| `ssh_private_key_passphrase` | (optional) | Passphrase for encrypted key |
| `remote_host` | (auto from URL) | Database host as seen from SSH server |
| `remote_port` | (auto from URL) | Database port as seen from SSH server |
| `local_host` | `127.0.0.1` | Local bind host |
| `local_port` | `None` (auto) | Local bind port |
| `tunnel_timeout` | `10` | SSH connection timeout (seconds) |

### Dependencies

- `sshtunnel>=0.4.0`
- `paramiko>=3.0.0,<4.0.0` (pinned to avoid compatibility issues with sshtunnel)

## Devcontainer Setup

The project includes a full devcontainer configuration (`.devcontainer/`) with **5 Docker containers** covering all 4 database access patterns:

| Container | Port | Network | Access Pattern |
| --------- | ---- | ------- | -------------- |
| `postgres-direct` | 5432 (published) | host | Direct access via localhost |
| `mysql-direct` | 3306 (published) | host | Direct access via localhost |
| `postgres-tunneled` | None (no published ports) | `tunnel-internal` | SSH tunnel only |
| `mysql-tunneled` | None (no published ports) | `tunnel-internal` | SSH tunnel only |
| `bastion` | 2222 → 22 | `tunnel-internal` | SSH gateway (Alpine + OpenSSH) |

The `tunnel-internal` bridge network isolates tunneled databases — they are **not** accessible from the devcontainer directly and must be reached through the bastion SSH tunnel.

### Environment Variables (set automatically in devcontainer)

```text
PG_TEST_DATABASE_URL=postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb
MYSQL_TEST_DATABASE_URL=mysql+aiomysql://testuser:testpass@localhost:3306/testdb
PG_TUNNEL_DATABASE_URL=postgresql+asyncpg://devuser:devpassword@postgres-tunneled:5432/devdb
MYSQL_TUNNEL_DATABASE_URL=mysql+aiomysql://testuser:testpass@mysql-tunneled:3306/testdb
SSH_HOST=localhost
SSH_PORT=2222
SSH_USERNAME=tunneluser
SSH_PASSWORD=tunnelpass
```

## Version Management

**IMPORTANT:** Before bumping the version and tagging a new release, ensure all version strings are aligned across the project.

### Files Containing Version Information

| File | Location |
| ---- | -------- |
| `pyproject.toml` | `version = "X.Y.Z"` (line ~7) |
| `src/db_connect_mcp/__init__.py` | `__version__ = "X.Y.Z"` |
| `uv.lock` | Auto-generated (run `uv sync` after updating pyproject.toml) |

### Version Bump Process

1. **Verify current versions are aligned** before making changes:
   ```bash
   grep -E "^version|__version__" pyproject.toml src/db_connect_mcp/__init__.py
   ```

2. **Update version in all files:**
   - Edit `pyproject.toml` with the new version
   - Edit `src/db_connect_mcp/__init__.py` with the matching version

3. **Regenerate uv.lock:**
   ```bash
   uv sync
   ```

4. **Verify all versions match** before committing:
   ```bash
   grep -E "^version|__version__" pyproject.toml src/db_connect_mcp/__init__.py
   ```

5. **Commit, tag, and push:**
   ```bash
   git add pyproject.toml src/db_connect_mcp/__init__.py uv.lock
   git commit -m "chore: bump version to X.Y.Z"
   git tag vX.Y.Z
   git push && git push --tags
   ```

## Additional Documentation

- **[Development Guide](docs/guides/DEVELOPMENT.md)** - Development environment setup, testing, and contribution guidelines
- **[Testing Guide](docs/guides/TESTING.md)** - Test structure, fixtures, and running tests
- **[Docker Setup](docs/guides/DOCKER.md)** - Database infrastructure (standalone and devcontainer)
- **[SSH Tunnel Guide](docs/guides/SSH_TUNNEL.md)** - SSH tunnel feature documentation
- **[README.md](README.md)** - User-facing documentation and usage examples
