# PostgreSQL 17 DevContainer Feature

A local DevContainer feature that installs PostgreSQL 17 server and client tools.

## Security

This feature provides a secure alternative to Docker-in-Docker:

- **No Docker socket exposure**: PostgreSQL runs natively in the container
- **Non-root execution**: PostgreSQL runs as unprivileged `postgres` user
- **Localhost only**: Database only listens on 127.0.0.1
- **Container isolation**: Host machine is protected by container boundary

## Usage

Add to your `devcontainer.json`:

```json
{
    "features": {
        "./features/postgresql-17": {
            "installClient": true,
            "installServer": true,
            "createTestDb": true,
            "testDbUser": "dbconnect",
            "testDbPassword": "dbconnect_dev_password",
            "testDbName": "db_connect_test"
        }
    },
    "postStartCommand": "sudo service postgresql start && /usr/local/bin/init-test-database.sh"
}
```

## Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `installClient` | boolean | `true` | Install PostgreSQL client tools (psql, pg_dump, etc.) |
| `installServer` | boolean | `true` | Install PostgreSQL server |
| `createTestDb` | boolean | `true` | Create test database on first start |
| `testDbUser` | string | `dbconnect` | Username for test database |
| `testDbPassword` | string | `dbconnect_dev_password` | Password for test database user |
| `testDbName` | string | `db_connect_test` | Name of test database |

## What Gets Installed

- PostgreSQL 17 from the official PostgreSQL apt repository
- PostgreSQL client tools (psql, pg_dump, pg_restore, etc.)
- PostgreSQL contrib package (additional utilities)
- Development-optimized configuration (faster writes, more memory)
- Initialization script at `/usr/local/bin/init-test-database.sh`

## Configuration

The feature creates a development-optimized PostgreSQL configuration:

- `listen_addresses = 'localhost'` - Only local connections
- `shared_buffers = 256MB` - Reasonable memory allocation
- `fsync = off` - Faster writes (development only!)
- `synchronous_commit = off` - Faster commits (development only!)

**Note**: These settings prioritize speed over durability. Do not use in production.

## Connection

After the container starts:

```bash
# Connect with psql
psql -h localhost -U dbconnect -d db_connect_test

# Connection string for applications
postgresql://dbconnect:dbconnect_dev_password@localhost:5432/db_connect_test

# Async connection string (for asyncpg)
postgresql+asyncpg://dbconnect:dbconnect_dev_password@localhost:5432/db_connect_test
```

## Files Created

| Path | Description |
|------|-------------|
| `/etc/postgresql/17/main/conf.d/development.conf` | Development configuration |
| `/usr/local/bin/init-test-database.sh` | Database initialization script |

## Troubleshooting

### PostgreSQL not starting

Check the service status:
```bash
sudo service postgresql status
sudo tail -f /var/log/postgresql/postgresql-17-main.log
```

### Database not initialized

Run the initialization script manually:
```bash
sudo service postgresql start
/usr/local/bin/init-test-database.sh
```

### Permission issues

Ensure PostgreSQL data directory has correct ownership:
```bash
sudo chown -R postgres:postgres /var/lib/postgresql/17/main
```
