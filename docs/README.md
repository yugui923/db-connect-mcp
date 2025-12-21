# Documentation Index

This directory contains documentation for db-connect-mcp developers and contributors.

## For Users

📖 **[Main README](../README.md)** - User documentation for installing and using db-connect-mcp

## For Contributors

📚 **[Development Guide](DEVELOPMENT.md)** - Complete guide for setting up development environment, running tests, and contributing

## For MCP Developers

🔧 **[Claude Code Integration](CLAUDE_CODE_INTEGRATION.md)** - Testing MCP servers with Claude Code during development

## Test Documentation

✅ **[Test Guide](../tests/README.md)** - Detailed testing documentation
✅ **[MCP Capability Test Summary](MCP_CAPABILITY_TEST_SUMMARY.md)** - Results from comprehensive MCP tool testing

## Technical References

🔍 **[Console Script vs Module Execution](CONSOLE_SCRIPT_VS_MODULE.md)** - Understanding `db-connect-mcp` vs `python -m db_connect_mcp`

## Quick Links

### Getting Started
1. [Installation](../README.md#installation) - Install via pip
2. [Configuration](../README.md#configuration) - Set up DATABASE_URL
3. [Usage Examples](../README.md#usage) - Basic usage

### Development Setup
1. [Prerequisites](DEVELOPMENT.md#prerequisites) - Python, uv, databases
2. [Installation](DEVELOPMENT.md#quick-setup) - Clone and install
3. [Running Tests](DEVELOPMENT.md#running-tests) - Test with pytest

### Testing with Claude Code
1. [Setup](CLAUDE_CODE_INTEGRATION.md#development-setup) - Configure .mcp.json
2. [Workflow](CLAUDE_CODE_INTEGRATION.md#development-testing-workflow) - Development testing cycle
3. [Troubleshooting](CLAUDE_CODE_INTEGRATION.md#development-specific-troubleshooting) - Common issues

## Architecture

For understanding the codebase architecture:

- [Adapter Pattern](DEVELOPMENT.md#adapter-pattern) - Database-specific adapters
- [Core Components](DEVELOPMENT.md#core-components) - Connection, inspector, executor, analyzer
- [MCP Integration](DEVELOPMENT.md#mcp-server-integration) - How MCP tools are registered
- [Project Structure](DEVELOPMENT.md#project-structure) - Directory layout

## Contributing

See [Development Guide - Contributing](DEVELOPMENT.md#contributing) for:
- Pull request process
- Commit message format
- Code style guidelines
- Adding new features

## External Resources

- [MCP Protocol](https://modelcontextprotocol.io/) - Model Context Protocol specification
- [Claude Code](https://code.claude.com/docs) - Official Claude Code documentation
- [SQLAlchemy](https://docs.sqlalchemy.org/) - Database toolkit documentation
- [Pydantic](https://docs.pydantic.dev/) - Data validation documentation
