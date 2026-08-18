# SSH Tunnel Support

This document covers the SSH tunnel feature, which enables secure connections to databases that are not directly reachable (e.g., behind firewalls, in private networks, or on cloud instances without public IPs).

## Overview

The SSH tunnel feature establishes an encrypted SSH connection to a bastion/jump host, then forwards local traffic through that tunnel to the target database. This is transparent to the rest of the application -- once the tunnel is up, the database connection works as if the database were on localhost.

```text
Application                 Bastion Host              Database Server
┌──────────┐   SSH tunnel   ┌──────────┐   private    ┌──────────┐
│ MCP      │───────────────>│ SSH      │─────────────>│ PostgreSQL│
│ Server   │  localhost:N   │ Server   │  db:PORT     │ MySQL, or │
│          │                │          │              │ ClickHouse│
└──────────┘                └──────────┘              └──────────┘
```

## Architecture

### Source Files

| File                                       | Purpose                                                                                                              |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| `src/db_connect_mcp/core/tunnel.py`        | `SSHTunnelManager` class -- lifecycle management (start, stop, health checks, context manager)                       |
| `src/db_connect_mcp/core/ssh_forwarder.py` | Stable listener, SSH transport replacement, channel leasing, and buffered relay                                      |
| `src/db_connect_mcp/models/config.py`      | `SSHTunnelConfig` Pydantic model -- all SSH tunnel configuration fields                                              |
| `src/db_connect_mcp/core/connection.py`    | `DatabaseConnection` integration -- auto-starts tunnel during `initialize()`, rewrites URL, cleans up on `dispose()` |

### How It Works

1. **Configuration**: `SSHTunnelConfig` is set on `DatabaseConfig.ssh_tunnel`
2. **Tunnel startup**: During `DatabaseConnection.initialize()`, if `ssh_tunnel` is configured:
   - `SSHTunnelManager` is created and `start()` is called
   - Paramiko's high-level `SSHClient` establishes and authenticates the bastion connection
   - A `direct-tcpip` preflight proves the bastion can reach the database target
   - A stable local port is bound (auto-assigned or specified)
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

The local listener and SSH transport have independent lifecycles. If a
transport fails, `ensure_active()` replaces only that transport, so the local
port embedded in the SQLAlchemy engine URL does not change. New local
connections also perform one transport-level recovery attempt if channel
creation times out before database bytes are forwarded. In-flight SQL is never
replayed automatically.

**`rewrite_database_url(original_url, local_host, local_port) -> str`**

- Rewrites any database URL (PostgreSQL, MySQL, ClickHouse) to route through the tunnel
- Preserves all other URL components (credentials, database name, query parameters)

**`SSHTunnelError`**

- Custom exception for tunnel-related failures
- Exposes a stable error code: `SSH_CONNECT_FAILED`, `SSH_HOST_KEY_FAILED`,
  `SSH_AUTH_FAILED`, `SSH_CHANNEL_FAILED`, `SSH_LISTENER_FAILED`,
  `SSH_RELAY_FAILED`, or `SSH_UNKNOWN_FAILED`
- Messages exclude passwords, private keys, connection URLs, and raw exception
  text

## Configuration Reference

`SSHTunnelConfig` fields:

| Field                        | Type   | Default          | Description                                                                             |
| ---------------------------- | ------ | ---------------- | --------------------------------------------------------------------------------------- |
| `ssh_host`                   | `str`  | (required)       | SSH server hostname or IP                                                               |
| `ssh_port`                   | `int`  | `22`             | SSH server port                                                                         |
| `ssh_username`               | `str`  | (required)       | SSH login username                                                                      |
| `ssh_password`               | `str`  | (optional)       | Password-based authentication                                                           |
| `ssh_private_key`            | `str`  | (optional)       | SSH private key content (raw PEM or base64-encoded PEM)                                 |
| `ssh_private_key_path`       | `str`  | (optional)       | Path to private key file                                                                |
| `ssh_private_key_passphrase` | `str`  | (optional)       | Passphrase for encrypted private key                                                    |
| `remote_host`                | `str`  | (auto from URL)  | Database host as seen from the SSH server. Auto-derived from `DATABASE_URL` if not set. |
| `remote_port`                | `int`  | (auto from URL)  | Database port as seen from the SSH server. Auto-derived from `DATABASE_URL` if not set. |
| `local_host`                 | `str`  | `127.0.0.1`      | Local address to bind the tunnel                                                        |
| `local_port`                 | `int`  | `None` (auto)    | Local port to bind (auto-assigned if not set)                                           |
| `tunnel_timeout`             | `int`  | `10`             | Legacy fallback for all SSH stage timeouts                                              |
| `connect_timeout`            | `int`  | `tunnel_timeout` | Bastion TCP connection timeout                                                          |
| `banner_timeout`             | `int`  | `tunnel_timeout` | SSH negotiation/banner timeout                                                          |
| `auth_timeout`               | `int`  | `tunnel_timeout` | SSH authentication timeout                                                              |
| `channel_timeout`            | `int`  | `tunnel_timeout` | `direct-tcpip` channel-open timeout                                                     |
| `keepalive_interval`         | `int`  | `30`             | Idle seconds between keepalive packets (`0` disables)                                   |
| `target_preflight`           | `bool` | `true`           | Prove target-channel reachability before publishing the listener                        |
| `strict_host_key`            | `bool` | `false`          | Reject unknown or changed bastion host keys                                             |
| `known_hosts_path`           | `str`  | (optional)       | Additional read-only known-hosts file; requires strict mode                             |

At least one of `ssh_password`, `ssh_private_key`, or `ssh_private_key_path` must be provided. If both `ssh_private_key` (inline) and `ssh_private_key_path` (file) are set, the inline key takes precedence.

## Usage Examples

### Programmatic Usage

```python
from db_connect_mcp.models.config import DatabaseConfig, SSHTunnelConfig

# remote_host and remote_port are auto-derived from the DATABASE_URL
config = DatabaseConfig(
    url="postgresql+asyncpg://user:pass@db-internal:5432/mydb",
    ssh_tunnel=SSHTunnelConfig(
        ssh_host="bastion.example.com",
        ssh_username="deployer",
        ssh_private_key_path="/home/user/.ssh/id_rsa",
    ),
)

# You can override remote_host/remote_port if they differ from the URL
config = DatabaseConfig(
    url="mysql+aiomysql://user:pass@placeholder:3306/mydb",
    ssh_tunnel=SSHTunnelConfig(
        ssh_host="bastion.example.com",
        ssh_username="deployer",
        ssh_password="secret",
        remote_host="mysql-internal",
        remote_port=3306,
    ),
)
```

### MCP Server Configuration (Claude Desktop / Claude Code)

SSH tunnel configuration is passed through environment variables in your MCP config. The application code reads these and builds the `SSHTunnelConfig` internally. See [Development Guide](DEVELOPMENT.md) for the devcontainer setup that demonstrates this pattern.

| Environment variable     | Configuration field  |
| ------------------------ | -------------------- |
| `SSH_TUNNEL_TIMEOUT`     | `tunnel_timeout`     |
| `SSH_CONNECT_TIMEOUT`    | `connect_timeout`    |
| `SSH_BANNER_TIMEOUT`     | `banner_timeout`     |
| `SSH_AUTH_TIMEOUT`       | `auth_timeout`       |
| `SSH_CHANNEL_TIMEOUT`    | `channel_timeout`    |
| `SSH_KEEPALIVE_INTERVAL` | `keepalive_interval` |
| `SSH_TARGET_PREFLIGHT`   | `target_preflight`   |
| `SSH_STRICT_HOST_KEY`    | `strict_host_key`    |
| `SSH_KNOWN_HOSTS_PATH`   | `known_hosts_path`   |

Boolean environment variables accept `true`, `false`, `1`, `0`, `yes`, `no`,
`on`, or `off` (case-insensitive). Invalid values fail configuration instead of
silently changing policy.

### Host-Key Policy

The default compatibility mode accepts a bastion host key for the current
process and emits a warning. It does not read or modify a user's `known_hosts`
file. Set `SSH_STRICT_HOST_KEY=true` to load system host keys and reject unknown
or changed bastion keys. `SSH_KNOWN_HOSTS_PATH` can add a read-only OpenSSH
known-hosts file and is only valid when strict mode is enabled.

## Dependencies

| Package    | Version          | Purpose                     |
| ---------- | ---------------- | --------------------------- |
| `paramiko` | `>=5.0.0,<6.0.0` | SSH client and channel APIs |

The forwarding listener and relay are first-party code built exclusively on
Paramiko's public APIs and Python's standard library. DSA keys are not supported
because Paramiko removed that obsolete algorithm.

## Devcontainer Test Infrastructure

The project includes a complete devcontainer setup that exercises all 4 database access patterns (2 databases x 2 access methods). See [Docker Setup](DOCKER.md#devcontainer-multi-database-setup) for the full container architecture.

### Container Architecture

```text
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
PG_TEST_DATABASE_URL=postgresql+asyncpg://devuser:devpassword@127.0.0.1:5432/devdb
MYSQL_TEST_DATABASE_URL=mysql+aiomysql://testuser:testpass@127.0.0.1:3306/devdb

# Tunnel test database URLs
PG_TUNNEL_DATABASE_URL=postgresql+asyncpg://devuser:devpassword@127.0.0.1:5432/devdb
MYSQL_TUNNEL_DATABASE_URL=mysql+aiomysql://testuser:testpass@127.0.0.1:3306/devdb

# SSH bastion credentials
SSH_HOST=127.0.0.1
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

- Ensure Paramiko satisfies `>=5.0.0,<6.0.0`
- Convert obsolete DSA keys to RSA, ECDSA, or Ed25519
- In strict mode, ensure the bastion key exists in the system or configured
  known-hosts file and has not changed
