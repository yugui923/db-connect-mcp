# Plan: Add MySQL + SSH Bastion to Devcontainer for Tunnel Testing

## Goal
Add a MySQL database that's **only reachable via SSH tunnel** through a bastion container, to test the project's existing tunnel support (`src/db_connect_mcp/core/tunnel.py`).

## Architecture
```
devcontainer (host network)
  └─ ssh -L 3306:mysql:3306 tunneluser@localhost -p 2222
       └─ bastion (port 2222 on host + tunnel-internal network)
            └─ mysql (tunnel-internal network only, no published ports)
```

## Implementation Status: DONE

### Files Created

| File | Purpose |
|------|---------|
| `tests/docker/bastion/Dockerfile` | Alpine SSH server with TCP forwarding enabled |
| `tests/docker/bastion/entrypoint.sh` | Sets tunneluser password from env, starts sshd |
| `tests/docker/mysql/init/01-create-schema.sql` | Tables: categories, products, users |
| `tests/docker/mysql/init/02-seed-data.sql` | 3 categories, 3 users, 5 products |

### Files Modified

| File | Changes |
|------|---------|
| `.devcontainer/docker-compose.yml` | Added `mysql` (internal network only), `bastion` (SSH on 2222), `tunnel-internal` network, `mysql-tunnel-data` volume |
| `.devcontainer/devcontainer.json` | Added `MYSQL_TEST_DATABASE_URL`, SSH tunnel env vars, port 2222 to forwardPorts |

## Credentials

| Service | Key | Value |
|---------|-----|-------|
| MySQL | URL | `mysql+aiomysql://testuser:testpass@localhost:3306/testdb` |
| MySQL | Root password | `rootpass` |
| Bastion SSH | Host:Port | `localhost:2222` |
| Bastion SSH | Username | `tunneluser` |
| Bastion SSH | Password | `tunnelpass` |
| PostgreSQL | URL | `postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb` |

## Environment Variables (set in devcontainer.json)

```
PG_TEST_DATABASE_URL=postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb
MYSQL_TEST_DATABASE_URL=mysql+aiomysql://testuser:testpass@localhost:3306/testdb
SSH_HOST=localhost
SSH_PORT=2222
SSH_USERNAME=tunneluser
SSH_PASSWORD=tunnelpass
SSH_REMOTE_HOST=mysql
SSH_REMOTE_PORT=3306
```

## Verification Steps (after rebuilding devcontainer)

```bash
# 1. Confirm MySQL is NOT directly accessible
nc -zv localhost 3306
# Expected: Connection refused

# 2. Confirm bastion SSH is up
nc -zv localhost 2222
# Expected: Connection succeeded

# 3. Manual SSH tunnel test
ssh -L 3306:mysql:3306 tunneluser@localhost -p 2222 -N -o StrictHostKeyChecking=no &
mysql -h 127.0.0.1 -u testuser -ptestpass testdb -e "SELECT * FROM users;"

# 4. Test with project's Python tunnel support
export DATABASE_URL=mysql+aiomysql://testuser:testpass@mysql:3306/testdb
python -m db_connect_mcp
```

## Key Design Decisions

- **MySQL has no published ports** — only reachable via the bastion on the `tunnel-internal` Docker network
- **Bastion publishes port 2222** to the host, so the devcontainer (which uses `network_mode: host`) can reach it on localhost
- **Password auth** used for simplicity; can add SSH key auth later
- **Devcontainer depends on bastion health** which depends on mysql health, ensuring proper startup order
