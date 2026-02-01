# Docker Setup

## Summary

The project uses Docker for test database infrastructure. There are two setups: a **standalone** `docker-compose.yml` in `tests/docker/` for quick PostgreSQL-only testing, and a **devcontainer** setup in `.devcontainer/` with 5 containers covering all 4 database access patterns (PostgreSQL direct, PostgreSQL tunneled, MySQL direct, MySQL tunneled) plus an SSH bastion host. See [SSH Tunnel](SSH_TUNNEL.md) for tunnel feature details and [Testing Guide](TESTING.md) for running tests.

---

## Standalone Setup (PostgreSQL Only)

Located in `tests/docker/docker-compose.yml`. This is the minimal setup for running PostgreSQL tests without the full devcontainer.

### Quick Start

```bash
cd tests/docker && docker-compose up -d && cd ../..

# Verify
docker-compose -f tests/docker/docker-compose.yml ps

# Connect
psql -h localhost -U devuser -d devdb  # Password: devpassword

# Run tests
uv run pytest -n 6

# Stop
cd tests/docker && docker-compose down && cd ../..

# Reset (destroy data + recreate)
cd tests/docker && docker-compose down -v && docker-compose up -d && cd ../..
```

### PostgreSQL Database

- **Image**: PostgreSQL 17 Alpine
- **Port**: 5432
- **Credentials**: `devuser` / `devpassword` / `devdb`
- **Data volume**: `db-connect-mcp-postgres-data`

### PostgreSQL Sample Data

| Table | Rows | Description |
|-------|------|-------------|
| categories | 50 | Hierarchical structure |
| products | 2,000 | Diverse types, prices, stock levels |
| users | 5,000 | Varied attributes, NULL testing |
| orders | 10,000 | 2-year history, various statuses |
| order_items | 25,000 | Average 2.5 per order |
| product_reviews | 8,000 | Realistic rating distribution |
| data_type_examples | 100 | Comprehensive PostgreSQL types |

**Views**: product_summary, order_details, active_products, product_statistics (materialized), user_activity_summary (materialized)

Init scripts run in alphabetical order from `tests/docker/postgres/init/`:
- `01-create-schema.sql` -- 7 tables with indexes and constraints
- `02-seed-data.sql` -- ~27,000 rows of sample data
- `03-create-views.sql` -- 5 views (2 materialized)

### MySQL Sample Data

Located in `tests/docker/mysql/init/`:
- `01-create-schema.sql` -- 3 tables (categories, products, users) with InnoDB, utf8mb4
- `02-seed-data.sql` -- 3 categories, 3 users, 5 products

---

## Devcontainer Multi-Database Setup

Located in `.devcontainer/`. This is the full development environment with all 4 database access patterns.

### Container Architecture

| Container | Image | Port | Network | Purpose |
|-----------|-------|------|---------|---------|
| `devcontainer` | Custom | host network | host | Development environment |
| `postgres-direct` | PostgreSQL 17 | **5432** (published) | host | Direct PostgreSQL access |
| `mysql-direct` | MySQL 8.0 | **3306** (published) | host | Direct MySQL access |
| `postgres-tunneled` | PostgreSQL 17 | None (no published ports) | `tunnel-internal` | PostgreSQL reachable only via SSH tunnel |
| `mysql-tunneled` | MySQL 8.0 | None (no published ports) | `tunnel-internal` | MySQL reachable only via SSH tunnel |
| `bastion` | Alpine + OpenSSH | **2222** → 22 | `tunnel-internal` | SSH gateway for tunnel-only databases |

### Network Isolation

```
Host Network                         tunnel-internal (bridge)
┌──────────────────────┐            ┌──────────────────────────┐
│ devcontainer         │            │ bastion (SSH on :2222)    │
│ postgres-direct:5432 │            │ postgres-tunneled:5432   │
│ mysql-direct:3306    │            │ mysql-tunneled:3306      │
└──────────────────────┘            └──────────────────────────┘
         │                                    ▲
         └── SSH tunnel via port 2222 ────────┘
```

The `tunnel-internal` bridge network is **not** connected to the devcontainer. The tunneled databases have no published ports. The only way to reach them from the devcontainer is through the bastion's SSH tunnel.

### Credentials

| Service | Credential | Value |
|---------|-----------|-------|
| PostgreSQL (both) | User / Password / DB | `devuser` / `devpassword` / `devdb` |
| MySQL (both) | User / Password / DB | `testuser` / `testpass` / `testdb` |
| MySQL (both) | Root password | `rootpass` |
| Bastion SSH | User / Password | `tunneluser` / `tunnelpass` |

### Environment Variables

Set automatically in `.devcontainer/devcontainer.json`:

```bash
# Direct access
PG_TEST_DATABASE_URL=postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb
MYSQL_TEST_DATABASE_URL=mysql+aiomysql://testuser:testpass@localhost:3306/testdb

# Tunnel access (hostnames resolve only from bastion's network)
PG_TUNNEL_DATABASE_URL=postgresql+asyncpg://devuser:devpassword@postgres-tunneled:5432/devdb
MYSQL_TUNNEL_DATABASE_URL=mysql+aiomysql://testuser:testpass@mysql-tunneled:3306/testdb

# SSH bastion
SSH_HOST=localhost
SSH_PORT=2222
SSH_USERNAME=tunneluser
SSH_PASSWORD=tunnelpass
```

### Bastion Host

The bastion is an Alpine Linux 3.19 container with OpenSSH server:

- **Dockerfile**: `tests/docker/bastion/Dockerfile`
- **Entrypoint**: `tests/docker/bastion/entrypoint.sh`
- SSH configuration:
  - `PasswordAuthentication yes`
  - `AllowTcpForwarding yes` (required for tunnel)
  - `PermitRootLogin no`
  - `GatewayPorts no`
- Host keys are generated at build time
- Password is set at runtime from `TUNNEL_PASSWORD` env var (default: `tunnelpass`)

### Health Checks and Startup Order

All database containers have health checks. The startup dependency chain ensures proper ordering:

```
postgres-direct ──────────────────────────────> devcontainer
mysql-direct ──────────────────────────────────>
postgres-tunneled ──> bastion ─────────────────>
mysql-tunneled ───────>
```

### Data Persistence

All containers use named Docker volumes:
- `postgres-direct-data`
- `mysql-direct-data`
- `postgres-tunneled-data`
- `mysql-tunneled-data`
- `claude-code-data` (Claude Code settings persistence)

---

## Management Commands

### Standalone (tests/docker)

```bash
docker-compose -f tests/docker/docker-compose.yml up -d      # Start
docker-compose -f tests/docker/docker-compose.yml stop        # Stop (preserve data)
docker-compose -f tests/docker/docker-compose.yml down        # Stop + remove
docker-compose -f tests/docker/docker-compose.yml down -v     # Stop + remove + delete data
docker-compose -f tests/docker/docker-compose.yml logs -f     # Follow logs
```

### Devcontainer

Rebuilding the devcontainer from your IDE restarts all containers. To manage individually:

```bash
# Inside devcontainer (docker compose v2)
docker compose -f .devcontainer/docker-compose.yml ps
docker compose -f .devcontainer/docker-compose.yml logs bastion
docker compose -f .devcontainer/docker-compose.yml restart mysql-direct
```

### Database Operations

```bash
# PostgreSQL
docker exec -it db-connect-mcp-postgres psql -U devuser -d devdb -c "\dt"
docker exec db-connect-mcp-postgres pg_dump -U devuser devdb > backup.sql

# MySQL
docker exec -it mysql-direct mysql -u testuser -ptestpass testdb -e "SHOW TABLES;"
```

## Troubleshooting

### Port already in use

```bash
sudo lsof -i :5432   # Check what's using the port
sudo systemctl stop postgresql   # Stop conflicting service
```

### Container not healthy

```bash
docker compose ps                    # Check status
docker compose logs <service>        # Check logs
docker compose restart <service>     # Restart
```

### Tunneled database unreachable

```bash
# Verify bastion is running
nc -zv localhost 2222

# Verify tunnel-internal network exists
docker network ls | grep tunnel

# Test manual SSH tunnel
ssh -L 15432:postgres-tunneled:5432 tunneluser@localhost -p 2222 -N -o StrictHostKeyChecking=no
```

### Complete reset

```bash
# Standalone
cd tests/docker && docker-compose down -v && docker-compose up -d

# Devcontainer: rebuild from IDE
```

## Security Notes

This configuration is for **local development only**:
- Hardcoded credentials
- No SSL/TLS
- Weak passwords
- Exposed on localhost

Never use this in production or expose to the internet.

## Additional Resources

- [SSH Tunnel](SSH_TUNNEL.md) -- Tunnel feature details
- [Testing Guide](TESTING.md) -- Running tests
- [Development Guide](DEVELOPMENT.md) -- Full dev workflow
