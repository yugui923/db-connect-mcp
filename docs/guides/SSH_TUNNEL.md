# SSH Tunnel Support

This document covers the SSH tunnel feature, which enables secure connections to databases that are not directly reachable (e.g., behind firewalls, in private networks, or on cloud instances without public IPs).

## Overview

The SSH tunnel feature establishes an encrypted SSH connection to a bastion/jump host, then forwards local traffic through that tunnel to the target database. This is transparent to the rest of the application -- once the tunnel is up, the database connection works as if the database were on localhost.

```
Application                 Bastion Host              Database Server
┌──────────┐   SSH tunnel   ┌──────────┐   private    ┌──────────┐
│ MCP      │───────────────>│ SSH      │─────────────>│ PostgreSQL│
│ Server   │  localhost:N   │ Server   │  db:5432     │ or MySQL  │
└──────────┘                └──────────┘              └──────────┘
```

## Architecture

### Source Files

| File | Purpose |
|------|---------|
| `src/db_connect_mcp/core/tunnel.py` | `SSHTunnelManager` class -- lifecycle management (start, stop, health checks, context manager) |
| `src/db_connect_mcp/models/config.py` | `SSHTunnelConfig` Pydantic model -- all SSH tunnel configuration fields |
| `src/db_connect_mcp/core/connection.py` | `DatabaseConnection` integration -- auto-starts tunnel during `initialize()`, rewrites URL, cleans up on `dispose()` |

### How It Works

1. **Configuration**: `SSHTunnelConfig` is set on `DatabaseConfig.ssh_tunnel`
2. **Tunnel startup**: During `DatabaseConnection.initialize()`, if `ssh_tunnel` is configured:
   - `SSHTunnelManager` is created and `start()` is called
   - An SSH connection is established to the bastion host
   - A local port is bound (auto-assigned or specified)
   - Traffic to the local port is forwarded to the remote database
3. **URL rewriting**: `rewrite_database_url()` replaces the database host/port in the connection string with `localhost:<local_port>`
4. **Normal operation**: SQLAlchemy connects to the rewritten URL, unaware of the tunnel
5. **Cleanup**: On `dispose()`, the tunnel is stopped and SSH resources released

### Key Classes and Functions

**`SSHTunnelManager`**
- `start() -> int`: Establishes tunnel, returns local port
- `stop()`: Tears down tunnel
- `ensure_active() -> bool`: Health check, restarts if needed
- `is_active` (property): Check tunnel status
- `local_bind_port` (property): Get the local port
- Context manager support (`with SSHTunnelManager(config) as mgr:`)

**`rewrite_database_url(original_url, local_host, local_port) -> str`**
- Rewrites any database URL (PostgreSQL, MySQL, ClickHouse) to route through the tunnel
- Preserves all other URL components (credentials, database name, query parameters)

**`SSHTunnelError`**
- Custom exception for tunnel-related failures

## Configuration Reference

`SSHTunnelConfig` fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ssh_host` | `str` | (required) | SSH server hostname or IP |
| `ssh_port` | `int` | `22` | SSH server port |
| `ssh_username` | `str` | (required) | SSH login username |
| `ssh_password` | `str` | (optional) | Password-based authentication |
| `ssh_private_key_path` | `str` | (optional) | Path to private key file |
| `ssh_private_key_passphrase` | `str` | (optional) | Passphrase for encrypted private key |
| `remote_host` | `str` | `127.0.0.1` | Database host as seen from the SSH server |
| `remote_port` | `int` | `5432` | Database port as seen from the SSH server |
| `local_host` | `str` | `127.0.0.1` | Local address to bind the tunnel |
| `local_port` | `int` | `None` (auto) | Local port to bind (auto-assigned if not set) |
| `tunnel_timeout` | `int` | `10` | SSH connection timeout in seconds |

At least one of `ssh_password` or `ssh_private_key_path` must be provided.

## Usage Examples

### Programmatic Usage

```python
from db_connect_mcp.models.config import DatabaseConfig, SSHTunnelConfig

config = DatabaseConfig(
    database_url="postgresql+asyncpg://user:pass@db-internal:5432/mydb",
    ssh_tunnel=SSHTunnelConfig(
        ssh_host="bastion.example.com",
        ssh_port=22,
        ssh_username="deployer",
        ssh_private_key_path="/home/user/.ssh/id_rsa",
        remote_host="db-internal",
        remote_port=5432,
    ),
)
```

### MCP Server Configuration (Claude Desktop / Claude Code)

SSH tunnel configuration is passed through environment variables in your MCP config. The application code reads these and builds the `SSHTunnelConfig` internally. See [Development Guide](DEVELOPMENT.md) for the devcontainer setup that demonstrates this pattern.

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `sshtunnel` | `>=0.4.0` | SSH tunnel management (wraps paramiko) |
| `paramiko` | `>=3.0.0,<4.0.0` | SSH protocol implementation |

The `paramiko<4` pin is required because `sshtunnel` has compatibility issues with paramiko 4.x.

## Devcontainer Test Infrastructure

The project includes a complete devcontainer setup that exercises all 4 database access patterns (2 databases x 2 access methods). See [Docker Setup](DOCKER.md#devcontainer-multi-database-setup) for the full container architecture.

### Container Architecture

```
┌─────────────────────────────────────────────────────────┐
│ devcontainer (host network)                             │
│   Can reach: postgres-direct:5432, mysql-direct:3306,   │
│              bastion:2222                                │
│   Cannot reach: postgres-tunneled, mysql-tunneled       │
└─────────────────────────────────────────────────────────┘
        │ direct              │ SSH tunnel (port 2222)
        ▼                     ▼
┌───────────────┐    ┌──────────────────────────────────┐
│ postgres-     │    │ tunnel-internal network (bridge)  │
│ direct:5432   │    │  ┌─────────┐                     │
│ mysql-        │    │  │ bastion │─── postgres-tunneled │
│ direct:3306   │    │  │ (SSH)   │─── mysql-tunneled    │
└───────────────┘    │  └─────────┘                     │
                     └──────────────────────────────────┘
```

### Environment Variables

These are set automatically in `.devcontainer/devcontainer.json`:

```bash
# Direct access databases
PG_TEST_DATABASE_URL=postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb
MYSQL_TEST_DATABASE_URL=mysql+aiomysql://testuser:testpass@localhost:3306/testdb

# Tunnel-only databases (hostnames resolve only from bastion's network)
PG_TUNNEL_DATABASE_URL=postgresql+asyncpg://devuser:devpassword@postgres-tunneled:5432/devdb
MYSQL_TUNNEL_DATABASE_URL=mysql+aiomysql://testuser:testpass@mysql-tunneled:3306/testdb

# SSH bastion credentials
SSH_HOST=localhost
SSH_PORT=2222
SSH_USERNAME=tunneluser
SSH_PASSWORD=tunnelpass
```

### Bastion Host Details

The bastion is an Alpine Linux container with OpenSSH:

- **Dockerfile**: `tests/docker/bastion/Dockerfile`
- **Entrypoint**: `tests/docker/bastion/entrypoint.sh` (sets password, starts sshd)
- **SSH config**: Password auth enabled, TCP forwarding enabled, root login disabled, gateway ports disabled
- **User**: `tunneluser` / `tunnelpass` (configurable via `TUNNEL_PASSWORD` env var)

## Troubleshooting

### Tunnel connection refused
- Verify the bastion SSH service is running: `nc -zv localhost 2222`
- Check bastion logs: `docker compose logs bastion`
- Ensure `AllowTcpForwarding yes` is set in the bastion's sshd_config

### Tunnel connects but database unreachable
- Verify the tunneled database is on the same Docker network as the bastion
- Check that `remote_host` matches the Docker service name (e.g., `postgres-tunneled`, not `localhost`)
- Verify database health: `docker compose ps`

### paramiko errors
- Ensure paramiko is pinned to `<4.0.0` (sshtunnel compatibility)
- Check SSH host key acceptance (the test fixtures use `set_missing_host_key_policy`)
