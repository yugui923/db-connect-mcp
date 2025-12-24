# Claude Code Integration Guide for Development

This guide is for **developers** testing the `db_connect_mcp` server using Claude Code. For end-user setup instructions, see the [README](../README.md#using-with-claude-code).

## Why Use Claude Code for MCP Development?

When developing MCP servers, Claude Code provides significant advantages:

- **Real-time debugging**: See MCP protocol messages and server errors immediately
- **Fast iteration**: Modify code, restart server, test - all without leaving the terminal
- **Protocol inspection**: Use `/mcp` to verify tools are registered correctly
- **Development workflow**: Test MCP integration while developing

## Development Setup

### 1. Start Test Database

```bash
cd tests/docker && docker compose up -d && cd ../..
```

This starts PostgreSQL 17 with 50K+ rows of sample data for testing.

### 2. Configure for Development

Create `.mcp.json` in project root with `uv run` for editable install:

```json
{
  "mcpServers": {
    "db-connect-mcp": {
      "command": "uv",
      "args": ["run", "python", "-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb"
      }
    }
  }
}
```

**Key difference from production**: Uses `uv run` to ensure dev dependencies are available and code changes are immediately reflected.

### 3. Start Claude Code

```bash
claude
```

The server auto-loads. Any code changes require restarting Claude Code to take effect.

## Verifying the MCP Server

### 1. Check MCP Server Status

In Claude Code, run:

```
/mcp
```

You should see:

- `db-connect-mcp` listed as a connected server
- Status showing available tools
- List of tools like `get_database_info`, `list_tables`, `execute_query`, etc.

### 2. Test with Natural Language

Try asking Claude Code to interact with your database:

```
What tables are in my database?
```

```
Show me sample data from the users table
```

```
What are the column statistics for the email column in the users table?
```

### 3. Check Available Tools

The following MCP tools should be available:

- `get_database_info` - Get database version and capabilities
- `list_schemas` - List all database schemas
- `list_tables` - List tables with metadata
- `describe_table` - Get detailed table structure
- `analyze_column` - Get column statistics and distribution
- `sample_data` - Preview table data with sampling
- `execute_query` - Execute read-only SQL queries
- `get_table_relationships` - Get foreign key relationships

## Development-Specific Troubleshooting

### Code Changes Not Reflected

**Issue**: Modified code but server behaves the same

**Solution**: Restart Claude Code (Ctrl+D, then `claude`)

The `uv run` command uses editable install, but Claude Code caches the server process.

### Database Connection Fails

**Check test database**:

```bash
cd tests/docker && docker compose ps
```

**Verify connection in dev container**:
If running in a dev container, use `postgres` hostname instead of `localhost`:

```json
"DATABASE_URL": "postgresql+asyncpg://devuser:devpassword@postgres:5432/devdb"
```

### MCP Tools Missing

**Verify installation**:

```bash
uv run python -c "import db_connect_mcp; print('OK')"
```

**Check server output**:
Start the server manually to see error messages:

```bash
DATABASE_URL=postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb \
  uv run python -m db_connect_mcp
```

Press Ctrl+C to stop, then check for import or initialization errors.

## Development Testing Workflow

### 1. Make Code Changes

Edit files in `src/db_connect_mcp/`

### 2. Run Unit Tests

```bash
uv run pytest -n 6
```

### 3. Test with Claude Code

```bash
# Restart Claude Code to load changes
claude
```

Try the feature interactively:

```
/mcp
```

Then test with natural language queries.

### 4. Test MCP Protocol Directly (Advanced)

For protocol-level debugging:

```bash
# Run server manually
DATABASE_URL=postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb \
  uv run python -m db_connect_mcp

# Send MCP messages (JSON-RPC)
{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
```

## Integration Testing Checklist

- [ ] MCP server appears in `/mcp` output
- [ ] All expected tools are listed
- [ ] Can query database information (`get_database_info`)
- [ ] Can list tables (`list_tables`)
- [ ] Can describe table structure (`describe_table`)
- [ ] Can sample data (`sample_data`)
- [ ] Can execute SELECT queries (`execute_query`)
- [ ] Can get column statistics (`analyze_column`)
- [ ] Can get table relationships (`get_table_relationships`)
- [ ] Write operations are correctly rejected
- [ ] Large result sets are automatically limited
- [ ] Error messages are clear and helpful

## Testing Different Scenarios

### Testing with Different Databases

Update `DATABASE_URL` in `.mcp.json`:

```json
"DATABASE_URL": "mysql+aiomysql://user:pass@localhost:3306/testdb"
```

or

```json
"DATABASE_URL": "clickhouse+asynch://default:@localhost:9000/default"
```

Then restart Claude Code.

### Docker/Dev Container Testing

If testing in a dev container with PostgreSQL sidecar:

```json
{
  "mcpServers": {
    "db-connect-mcp": {
      "command": "uv",
      "args": ["run", "python", "-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://devuser:devpass@postgres:5432/devdb"
      }
    }
  }
}
```

**Note**: Use service name (`postgres`) not `localhost` when inside containers.

## Resources

- [Main README](../README.md) - User documentation
- [Development Guide](DEVELOPMENT.md) - Full development setup
- [Test Guide](../tests/README.md) - Testing documentation
- [Claude Code Docs](https://code.claude.com/docs/en/mcp) - Official MCP documentation
