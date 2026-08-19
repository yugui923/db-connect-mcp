# Testing Guide

## Summary

The test suite contains **200+ tests** organized into three layers: **unit** (isolated logic), **module** (core components against real databases), and **integration** (full MCP protocol and SSH tunnels). Tests cover 4 database access patterns: PostgreSQL direct, PostgreSQL via SSH tunnel, MySQL direct, and MySQL via SSH tunnel. Run all tests with `uv run pytest -n 6`. See [Docker Setup](DOCKER.md) for database infrastructure and [SSH Tunnel](SSH_TUNNEL.md) for tunnel-specific details.

---

## Test Structure

### 1. Unit Tests (`tests/unit/`)

Isolated tests for adapters, serialization, utilities, and SSH tunnel logic.

| File | What It Tests |
|------|---------------|
| `adapters/test_postgresql_adapter.py` | PostgreSQL adapter configuration, capabilities, SQL generation |
| `adapters/test_clickhouse_adapter.py` | ClickHouse adapter (skipped if `CH_TEST_DATABASE_URL` not set) |
| `test_serialization.py` | JSON serialization for all database types (temporal, network, UUID, JSONB, arrays, etc.) |
| `test_utils.py` | Test reporters, data type helpers, benchmarking |
| `test_tunnel.py` | SSH tunnel config validation, URL rewriting, mocked tunnel lifecycle, context manager, error handling (~26 tests) |

### 2. Module Tests (`tests/module/`)

Core component tests against real databases -- no MCP protocol overhead.

| File | Database | Access | What It Tests |
|------|----------|--------|---------------|
| `test_inspector.py` | PostgreSQL | Direct | Schema listing, table metadata, relationships |
| `test_executor.py` | PostgreSQL | Direct | Query execution, sampling, read-only enforcement, CTEs |
| `test_analyzer.py` | PostgreSQL | Direct | Column statistics (numeric, text), profiling |
| `test_pg_tunneled.py` | PostgreSQL | SSH tunnel | Inspector, executor, analyzer -- same coverage as direct, via tunnel (~26 tests) |
| `test_mysql_inspector.py` | MySQL | Direct + tunnel | Schema listing, table description, relationships (6 tests each) |
| `test_mysql_executor.py` | MySQL | Direct + tunnel | Queries, sampling, read-only enforcement |
| `test_mysql_analyzer.py` | MySQL | Direct + tunnel | Numeric and text column statistics |

### 3. Integration Tests (`tests/integration/`)

End-to-end tests through the full MCP protocol stack.

| File | What It Tests |
|------|---------------|
| `test_mcp_protocol.py` | MCP tool registration, JSON schema validation, tool calls via ClientSession |
| `test_mcp_workflows.py` | Multi-step workflows (explore → query → analyze), error recovery |
| `test_e2e_client_server.py` | Real subprocess server with stdio transport, server log capture |
| `test_ssh_tunnel.py` | SSH tunnel connectivity, MySQL/PostgreSQL through tunnel, MCP server with tunneled databases (~20 tests) |

## Directory Structure

```
tests/
├── conftest.py                        # All fixtures: 4 database variants, SSH configs
├── integration/
│   ├── test_mcp_protocol.py          # MCP protocol layer
│   ├── test_mcp_workflows.py         # End-to-end workflows
│   ├── test_e2e_client_server.py     # Subprocess server E2E
│   └── test_ssh_tunnel.py            # SSH tunnel integration tests
├── module/
│   ├── test_analyzer.py              # PostgreSQL direct - StatisticsAnalyzer
│   ├── test_executor.py              # PostgreSQL direct - QueryExecutor
│   ├── test_inspector.py             # PostgreSQL direct - MetadataInspector
│   ├── test_pg_tunneled.py           # PostgreSQL via SSH tunnel
│   ├── test_mysql_inspector.py       # MySQL direct + tunneled
│   ├── test_mysql_executor.py        # MySQL direct + tunneled
│   └── test_mysql_analyzer.py        # MySQL direct + tunneled
├── unit/
│   ├── adapters/
│   │   ├── test_postgresql_adapter.py
│   │   └── test_clickhouse_adapter.py
│   ├── test_serialization.py
│   ├── test_utils.py
│   └── test_tunnel.py               # SSH tunnel unit tests
└── docker/                           # Test database infrastructure
```

## Setup

### Install Dependencies

```bash
uv sync --dev
# or
pip install -e ".[dev]"
```

### Start Databases

**Standalone (PostgreSQL only):**
```bash
cd tests/docker && docker-compose up -d && cd ../..
```

**Devcontainer (all 4 access patterns):**
Rebuild the devcontainer -- it starts PostgreSQL direct, MySQL direct, PostgreSQL tunneled, MySQL tunneled, and the SSH bastion automatically. Environment variables are pre-configured in `.devcontainer/devcontainer.json`.

See [Docker Setup](DOCKER.md) for full details.

## Running Tests

**Always use 6 parallel workers** (`-n 6`) for optimal performance.

```bash
# All tests
uv run pytest -n 6

# Verbose
uv run pytest -v -n 6

# By layer
uv run pytest tests/unit/ -v -n 6
uv run pytest tests/module/ -v -n 6
uv run pytest tests/integration/ -v -n 6

# By database
uv run pytest -m postgresql -n 6
uv run pytest -m mysql -n 6

# Specific files
uv run pytest tests/module/test_pg_tunneled.py -v -n 6
uv run pytest tests/integration/test_ssh_tunnel.py -v -n 6

# Coverage (sequential -- coverage doesn't work well with parallel)
uv run pytest --cov=src --cov-report=term-missing
```

## Test Fixtures

Shared fixtures are defined in `tests/conftest.py` using a consistent naming convention:

### Naming Convention

| Prefix | Database | Access |
|--------|----------|--------|
| `pg_*` | PostgreSQL | Direct (localhost:5432) |
| `mysql_*` | MySQL | Direct (localhost:3306) |
| `pg_tunnel_*` | PostgreSQL | SSH tunnel (bastion → postgres-tunneled) |
| `mysql_tunnel_*` | MySQL | SSH tunnel (bastion → mysql-tunneled) |

### Available Fixtures

**URL fixtures** (session scope):
- `pg_database_url`, `mysql_database_url`, `pg_tunnel_database_url`, `mysql_tunnel_database_url`

**SSH config fixtures** (session scope):
- `pg_tunnel_ssh_config`, `mysql_tunnel_ssh_config`

**Component fixtures** (function scope, async):
- `*_config`, `*_adapter`, `*_connection`, `*_inspector`, `*_executor`, `*_analyzer`, `*_mcp_server`

All connection fixtures run `SELECT 1` to verify connectivity and skip the test (rather than fail) if the database is unreachable.

### Helper Function

`_build_ssh_tunnel_config(remote_host, remote_port)` reads `SSH_HOST`, `SSH_USERNAME`, `SSH_PORT`, `SSH_PASSWORD` from environment variables and returns an `SSHTunnelConfig` (or `None` if not configured, causing tests to skip).

## Test Markers

| Marker | Description |
|--------|-------------|
| `postgresql` | PostgreSQL-specific tests |
| `mysql` | MySQL-specific tests |
| `clickhouse` | ClickHouse-specific tests |
| `integration` | Integration tests requiring database |
| `slow` | Tests taking >5 seconds |

```bash
uv run pytest -m "postgresql and integration" -n 6
uv run pytest -m "not slow" -n 6
```

## Best Practices

1. **Use fixtures** for database connections -- never create connections manually in tests
2. **Use descriptive names**: `test_execute_query_enforces_read_only_mode`
3. **Skip when appropriate**: `pytest.skip()` for missing capabilities or databases
4. **Test edge cases**: empty results, NULL values, non-existent resources, invalid inputs

## Troubleshooting

### Tests skip with "URL not set"
The corresponding database URL environment variable is not configured. When running in the devcontainer, these are set automatically. For standalone: set `PG_TEST_DATABASE_URL`, etc.

### Tunnel tests skip
SSH tunnel environment variables (`SSH_HOST`, `SSH_USERNAME`) are not set, or the bastion container is not running. Rebuild the devcontainer to start all containers.

### Windows event loop issues
Handled automatically in `conftest.py` -- sets `WindowsSelectorEventLoopPolicy` on Windows.

## Additional Resources

- [Docker Setup](DOCKER.md) -- Database infrastructure
- [SSH Tunnel](SSH_TUNNEL.md) -- Tunnel feature details
- [Development Guide](DEVELOPMENT.md) -- Full dev workflow
- [CLAUDE.md](../CLAUDE.md) -- Claude Code guidance
