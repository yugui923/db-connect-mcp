# Remote MCP Server (Streamable HTTP Transport)

The server supports running as a remote MCP server over HTTP using the Streamable HTTP transport, in addition to the default stdio transport. MCP Python SDK 2.2 supports both the 2026-07-28 session-free protocol and older initialize-based clients on the same endpoint. Existing stdio client configurations, database URLs, and SSH settings do not need to change; the server already uses stateless HTTP for older clients.

## Quick Start

```bash
# Set your database URL
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/mydb"

# Start the remote MCP server
python -m db_connect_mcp --transport streamable-http --port 8000
```

The server will be accessible at `http://localhost:8000/mcp`.

## CLI Options

| Flag          | Default   | Description                                      |
| ------------- | --------- | ------------------------------------------------ |
| `--transport` | `stdio`   | Transport protocol: `stdio` or `streamable-http` |
| `--host`      | `0.0.0.0` | Host to bind to (streamable-http only)           |
| `--port`      | `8000`    | Port to listen on (streamable-http only)         |

The HTTP endpoint accepts both client generations without a transport flag. Modern clients send `server/discover` and per-request protocol metadata; older clients continue to send `initialize`. Modern requests carry no `Mcp-Session-Id`. The server still uses a process-wide read-only database connection pool and an optional SSH tunnel; stateless refers to the MCP protocol, not the database lifecycle.

### OAuth 2.0 Options

| Flag               | Environment Variable | Description                                               |
| ------------------ | -------------------- | --------------------------------------------------------- |
| `--oauth-issuer`   | `MCP_OAUTH_ISSUER`   | OAuth issuer URL (e.g., `https://your-tenant.auth0.com/`) |
| `--oauth-audience` | `MCP_OAUTH_AUDIENCE` | Expected audience claim (your API identifier)             |
| `--oauth-scopes`   | `MCP_OAUTH_SCOPES`   | Required scopes (comma-separated)                         |

## Authentication

The server supports three authentication modes:

### 1. No Authentication (Development)

Default when no auth options are set. Suitable for local development.

```bash
python -m db_connect_mcp --transport streamable-http
```

### 2. Simple Bearer Token

Set the `MCP_AUTH_TOKEN` environment variable for static token authentication:

```bash
export MCP_AUTH_TOKEN="my-secret-token"
python -m db_connect_mcp --transport streamable-http
```

- All requests must include `Authorization: Bearer <token>`
- Returns HTTP 401 on missing or invalid tokens
- Simple but suitable for internal services or development

### 3. OAuth 2.0 JWT Verification (Production)

For production environments, use OAuth 2.0 with JWT tokens from an identity provider:

```bash
python -m db_connect_mcp --transport streamable-http \
  --oauth-issuer https://your-tenant.auth0.com/ \
  --oauth-audience https://your-api-identifier
```

Features:

- Validates JWT signatures using JWKS from the identity provider
- Verifies token expiration, issuer, and audience claims
- Supports scope-based authorization
- Compatible with Auth0, Okta, Azure AD, Google, and other OIDC-compliant providers
- Automatic JWKS key rotation handling

## OAuth 2.0 Provider Examples

### Auth0

```bash
python -m db_connect_mcp --transport streamable-http \
  --oauth-issuer https://your-tenant.auth0.com/ \
  --oauth-audience https://your-api-identifier \
  --oauth-scopes "read:database,write:database"
```

In Auth0:

1. Create an API with your audience identifier
2. Define permissions (scopes) like `read:database`, `write:database`
3. Authorize your client applications

### Azure AD

```bash
python -m db_connect_mcp --transport streamable-http \
  --oauth-issuer https://login.microsoftonline.com/{tenant-id}/v2.0 \
  --oauth-audience your-client-id
```

In Azure AD:

1. Register an application
2. Configure API permissions
3. Use the application's client ID as the audience

### Okta

```bash
python -m db_connect_mcp --transport streamable-http \
  --oauth-issuer https://your-domain.okta.com/oauth2/default \
  --oauth-audience api://default
```

### Google Cloud Identity

```bash
python -m db_connect_mcp --transport streamable-http \
  --oauth-issuer https://accounts.google.com \
  --oauth-audience your-client-id.apps.googleusercontent.com
```

## Client Authentication

### With Simple Bearer Token

```bash
# Claude Code
claude mcp add --transport http \
  --header "Authorization: Bearer my-secret-token" \
  db-connect http://localhost:8000/mcp

# curl
curl -H "Authorization: Bearer my-secret-token" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  http://localhost:8000/mcp
```

### With OAuth 2.0 Token

First, obtain an access token from your identity provider:

```bash
# Auth0 example (client credentials flow)
TOKEN=$(curl --request POST \
  --url https://your-tenant.auth0.com/oauth/token \
  --header 'content-type: application/json' \
  --data '{
    "client_id":"your-client-id",
    "client_secret":"your-client-secret",
    "audience":"https://your-api-identifier",
    "grant_type":"client_credentials"
  }' | jq -r '.access_token')

# Then use the token
curl -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  http://localhost:8000/mcp
```

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

## Error Responses

| Status | Error                | Description                                              |
| ------ | -------------------- | -------------------------------------------------------- |
| 401    | `unauthorized`       | Missing bearer token                                     |
| 401    | `invalid_token`      | Token validation failed (expired, wrong signature, etc.) |
| 403    | `insufficient_scope` | Token lacks required scopes                              |

Example error response:

```json
{
  "error": "invalid_token",
  "error_description": "Token validation failed"
}
```

## Architecture

Each server instance connects to a single database (configured via `DATABASE_URL`). To serve multiple databases, run separate instances on different ports and use a reverse proxy for routing:

```
https://mcp.example.com/prod-pg/mcp      -> instance on port 8001
https://mcp.example.com/staging-mysql/mcp -> instance on port 8002
```

## Environment Variables

All existing environment variables (`DATABASE_URL`, `DB_POOL_SIZE`, SSH tunnel config, etc.) work the same regardless of transport. The following are specific to remote mode:

| Variable              | Default | Description                                                                                                     |
| --------------------- | ------- | --------------------------------------------------------------------------------------------------------------- |
| `MCP_AUTH_TOKEN`      | (none)  | Bearer token for simple authentication                                                                          |
| `MCP_OAUTH_ISSUER`    | (none)  | OAuth issuer URL for JWT verification                                                                           |
| `MCP_OAUTH_AUDIENCE`  | (none)  | Expected audience claim                                                                                         |
| `MCP_OAUTH_SCOPES`    | (none)  | Required scopes (comma-separated)                                                                               |
| `MCP_ALLOWED_HOSTS`   | (none)  | Extra comma-separated HTTP Host values allowed by the transport, beyond localhost and loopback hosts with ports |
| `MCP_ALLOWED_ORIGINS` | (none)  | Extra comma-separated Origin values allowed by the transport; requests without an Origin are allowed            |

The transport rejects unexpected Host/Origin headers by default. If a reverse proxy forwards a public `Host`, set `MCP_ALLOWED_HOSTS` to its exact hostname (including the port when forwarded). If a browser client sends an `Origin`, add its exact origin, including scheme and optional port, to `MCP_ALLOWED_ORIGINS`. Do not use wildcard entries or disable DNS rebinding protection. Keep proxy access authenticated and use HTTPS externally. These settings affect HTTP only; existing stdio configurations are unaffected.

## Security Recommendations

1. **Always use HTTPS in production** - Run behind a TLS-terminating reverse proxy (nginx, Caddy, etc.)
2. **Use OAuth 2.0 for production** - Simple bearer tokens should only be used for development or internal services
3. **Limit scopes** - Define and require specific scopes for database access
4. **Rotate tokens** - Use short-lived JWT tokens (e.g., 1 hour expiration)
5. **Monitor access** - Log authentication events and failed attempts
6. **Restrict network access** - Use firewalls to limit which IPs can reach the server

## Token Introspection (Alternative)

For opaque tokens or when JWKS is not available, you can implement token introspection by extending the server. The `IntrospectionTokenVerifier` class is available:

```python
from db_connect_mcp.auth import IntrospectionTokenVerifier

verifier = IntrospectionTokenVerifier(
    introspection_url="https://auth.example.com/oauth/introspect",
    client_id="your-client-id",
    client_secret="your-client-secret",
    required_scopes=["database:read"],
)
```

This calls the authorization server's introspection endpoint (RFC 7662) to validate tokens.
