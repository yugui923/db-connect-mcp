# Remote MCP Server (Streamable HTTP Transport)

The server supports running as a remote MCP server over HTTP using the Streamable HTTP transport, in addition to the default stdio transport.

## Quick Start

```bash
# Set your database URL
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/mydb"

# Start the remote MCP server
python -m db_connect_mcp --transport streamable-http --port 8000
```

The server will be accessible at `http://localhost:8000/mcp`.

## CLI Options

| Flag | Default | Description |
| ---- | ------- | ----------- |
| `--transport` | `stdio` | Transport protocol: `stdio` or `streamable-http` |
| `--host` | `0.0.0.0` | Host to bind to (streamable-http only) |
| `--port` | `8000` | Port to listen on (streamable-http only) |

## Authentication

When running as a remote server, you can enable bearer token authentication by setting the `MCP_AUTH_TOKEN` environment variable:

```bash
export MCP_AUTH_TOKEN="my-secret-token"
python -m db_connect_mcp --transport streamable-http
```

- If `MCP_AUTH_TOKEN` is set, all requests must include `Authorization: Bearer <token>`
- If not set, no authentication is required (suitable for development/local use)
- Returns HTTP 401 on missing or invalid tokens

## Connecting Clients

### Claude Code

```bash
claude mcp add --transport http db-connect http://localhost:8000/mcp
```

### MCP Inspector

```bash
npx -y @modelcontextprotocol/inspector
# Then connect to http://localhost:8000/mcp in the UI
```

## Architecture

Each server instance connects to a single database (configured via `DATABASE_URL`). To serve multiple databases, run separate instances on different ports and use a reverse proxy for routing:

```
https://mcp.example.com/prod-pg/mcp      -> instance on port 8001
https://mcp.example.com/staging-mysql/mcp -> instance on port 8002
```

## Environment Variables

All existing environment variables (`DATABASE_URL`, `DB_POOL_SIZE`, SSH tunnel config, etc.) work the same regardless of transport. The following are specific to remote mode:

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `MCP_AUTH_TOKEN` | (none) | Bearer token for authentication. If unset, auth is disabled |
