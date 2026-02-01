# Tests

This directory contains the pytest test suite for db-connect-mcp.

For full documentation -- test structure, fixtures, running commands, markers, and troubleshooting -- see the **[Testing Guide](../docs/guides/TESTING.md)**.

## Quick Start

```bash
# Install dev dependencies
uv sync --dev

# Start test databases (standalone PostgreSQL)
cd tests/docker && docker-compose up -d && cd ../..

# Run all tests (6 parallel workers)
uv run pytest -n 6
```

For the full devcontainer with all 4 database access patterns (PostgreSQL/MySQL, direct/tunneled), see **[Docker Setup](../docs/guides/DOCKER.md)**.
