# Claude Code Integration Guide

This guide explains how to test the `db_connect_mcp` server using Claude Code instead of Claude Desktop.

## Why Claude Code for Testing?

Claude Code provides several advantages over Claude Desktop for MCP development:

1. **Better debugging visibility**: See detailed error messages and tool outputs
2. **Faster iteration**: Restart and reconfigure servers quickly
3. **Direct CLI access**: Test your server from the command line
4. **Integration with your development workflow**: Use the same environment you code in

## Prerequisites

1. **Start the local test database**:
   ```bash
   cd tests/docker && docker compose up -d && cd ../..
   ```

   This starts a PostgreSQL 17 database with:
   - Database: `devdb`
   - User: `devuser`
   - Password: `devpassword`
   - Port: `5432`
   - Pre-loaded with 50K+ rows of sample data

2. **Install dependencies**:
   ```bash
   uv sync
   ```

## Configuration

The MCP server is configured in `.mcp.json` (project-scoped configuration):

```json
{
  "mcpServers": {
    "db-connect-mcp": {
      "command": "python",
      "args": ["-m", "db_connect_mcp"],
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb"
      }
    }
  }
}
```

**Note**: This configuration uses the local test database. To test with a different database, update the `DATABASE_URL` environment variable.

## Restarting Claude Code

After creating or modifying `.mcp.json`, you need to restart Claude Code:

```bash
# Exit current Claude Code session (Ctrl+D or type 'exit')
# Then restart
claude
```

The MCP server will be automatically loaded on startup.

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

## Troubleshooting

### MCP Server Not Loading

**Check the configuration file**:
```bash
cat .mcp.json
```

**Verify Python can run the module**:
```bash
python -m db_connect_mcp --help
```

**Check for syntax errors**:
```bash
uv run python -m db_connect_mcp
```

### Database Connection Issues

**Verify the database is running**:
```bash
docker compose ps
# or
docker ps | grep postgres
```

**Test the connection string directly**:
```bash
DATABASE_URL=postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb \
  python -m db_connect_mcp
```

**Check database logs**:
```bash
cd tests/docker && docker compose logs postgres
```

### MCP Tools Not Appearing

If tools don't appear in `/mcp`:

1. **Check for errors in Claude Code startup**:
   - Look for error messages when Claude Code starts
   - Check if the server process started successfully

2. **Verify asyncpg is installed**:
   ```bash
   uv pip list | grep asyncpg
   ```

3. **Test the server standalone**:
   ```bash
   # Should start and wait for stdio input
   DATABASE_URL=postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb \
     python -m db_connect_mcp
   ```

### Permission Errors

If you see "permission denied" or "read-only" errors:

- This is **expected behavior** - the MCP server enforces read-only access
- Only SELECT queries are allowed
- INSERT, UPDATE, DELETE, and DDL statements will be rejected

## Testing Workflow

### 1. Automated Testing (Recommended)

Run the full test suite:
```bash
uv run pytest -n 6
```

This tests the MCP server functionality programmatically.

### 2. Interactive Testing with Claude Code

Use Claude Code as an interactive testing environment:

1. **Start Claude Code** with the MCP server loaded
2. **Ask natural language questions** about your database
3. **Verify the responses** match expected behavior
4. **Test edge cases** like large result sets, complex queries, etc.

### 3. Manual MCP Protocol Testing

For low-level protocol testing, you can communicate with the server directly via stdin/stdout:

```bash
# Start the server
DATABASE_URL=postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb \
  python -m db_connect_mcp

# Send MCP protocol messages (JSON-RPC format)
# Example: list available tools
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

## Comparing with Claude Desktop

### Claude Desktop Issues

Common issues when testing with Claude Desktop:
- Limited error visibility
- Difficult to debug server startup issues
- No direct access to server logs
- Slower iteration cycle (requires app restart)

### Claude Code Advantages

- See server stdout/stderr directly
- Quick configuration changes
- Better error messages
- Integration with development environment
- Can combine MCP testing with code editing

## Next Steps

1. **Test with different databases**: Update `DATABASE_URL` to test MySQL or ClickHouse
2. **Test with production data**: Use a read-only replica connection string
3. **Performance testing**: Test with large tables and complex queries
4. **Error handling**: Verify error messages are helpful and accurate
5. **Security testing**: Verify write operations are blocked

## Additional Resources

- [Claude Code MCP Documentation](https://code.claude.com/docs/en/mcp)
- [MCP Protocol Specification](https://spec.modelcontextprotocol.io/)
- [Project README](/workspace/README.md)
- [Development Guide](/workspace/docs/DEVELOPMENT.md)
