# Documentation

All project documentation is organized in this directory.

## Guides

Step-by-step guides for development, testing, and infrastructure:

- **[Development Guide](guides/DEVELOPMENT.md)** -- Setup, workflow, architecture, contributing
- **[Testing Guide](guides/TESTING.md)** -- Test structure, fixtures, running tests, 200+ tests across 4 database access patterns
- **[Docker Setup](guides/DOCKER.md)** -- Standalone PostgreSQL and full devcontainer with 5 containers
- **[SSH Tunnel](guides/SSH_TUNNEL.md)** -- SSH tunnel feature, configuration, bastion host, network isolation
- **[Claude Code Integration](guides/CLAUDE_CODE_INTEGRATION.md)** -- MCP server development and testing with Claude Code

## Reference

Historical test results and planning documents:

- **[MCP Capability Test Summary](reference/MCP_CAPABILITY_TEST_SUMMARY.md)** -- Comprehensive MCP tool test results against PostgreSQL 17
- **[Tunnel Testing Plan](reference/TUNNEL_TESTING_PLAN.md)** -- Original implementation plan for SSH tunnel test infrastructure

## Quick Links

| I want to... | Go to |
|---------------|-------|
| Set up my dev environment | [Development Guide](guides/DEVELOPMENT.md#quick-setup) |
| Run the tests | [Testing Guide](guides/TESTING.md#running-tests) |
| Start the test databases | [Docker Setup](guides/DOCKER.md#standalone-setup-postgresql-only) |
| Understand the SSH tunnel feature | [SSH Tunnel](guides/SSH_TUNNEL.md) |
| Use the devcontainer | [Docker Setup](guides/DOCKER.md#devcontainer-multi-database-setup) |
| Test with Claude Code | [Claude Code Integration](guides/CLAUDE_CODE_INTEGRATION.md) |
