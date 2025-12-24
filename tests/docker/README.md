# Docker Test Database Setup

This directory contains Docker Compose configuration for running a local PostgreSQL 17 database with comprehensive sample data for testing the db-connect-mcp server.

## Quick Start

1. **Start the database**:

   ```bash
   cd tests/docker
   docker-compose up -d
   ```

2. **Verify it's running**:

   ```bash
   docker-compose ps
   docker-compose logs postgres
   ```

3. **Connect to database**:

   ```bash
   # Using docker exec
   docker exec -it db-connect-mcp-postgres psql -U devuser -d devdb

   # Using local psql client
   psql -h localhost -U devuser -d devdb
   # Password: devpassword
   ```

4. **Update your .env file** (optional, uses this by default):

   ```bash
   DATABASE_URL=postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb
   ```

5. **Run tests**:
   ```bash
   cd ../..
   pytest tests/
   ```

## Database Schema

The database includes:

- **7 tables**: categories, products, users, orders, order_items, product_reviews, data_type_examples
- **Sample data**:
  - 50 categories (hierarchical structure)
  - 2,000 products (diverse types, prices, stock levels)
  - 5,000 users (varied attributes, NULL testing)
  - 10,000 orders (2-year history, various statuses)
  - 25,000 order items (average 2.5 per order)
  - 8,000 product reviews (realistic rating distribution)
  - 100 data type examples (comprehensive PostgreSQL types)

- **5 views**: product_summary, order_details, active_products, product_statistics (materialized), user_activity_summary (materialized)

See [../../docs/TESTING_DATABASE.md](../../docs/TESTING_DATABASE.md) for complete schema reference and testing scenarios.

## Management Commands

### Start/Stop

```bash
# Start database
docker-compose up -d

# Stop database (preserves data)
docker-compose stop

# Stop and remove (destroys data)
docker-compose down

# Stop and remove including volumes (complete reset)
docker-compose down -v
```

### Logs and Monitoring

```bash
# View logs
docker-compose logs -f postgres

# Check health
docker-compose ps
docker-compose exec postgres pg_isready -U devuser
```

### Database Operations

```bash
# Run SQL file
docker exec -i db-connect-mcp-postgres psql -U devuser -d devdb < your_file.sql

# Backup database
docker exec db-connect-mcp-postgres pg_dump -U devuser devdb > backup.sql

# Restore database
docker exec -i db-connect-mcp-postgres psql -U devuser -d devdb < backup.sql

# Refresh materialized views
docker exec db-connect-mcp-postgres psql -U devuser -d devdb -c "REFRESH MATERIALIZED VIEW product_statistics; REFRESH MATERIALIZED VIEW user_activity_summary;"

# List tables
docker exec -it db-connect-mcp-postgres psql -U devuser -d devdb -c "\dt"

# Get row counts
docker exec -it db-connect-mcp-postgres psql -U devuser -d devdb -c "
SELECT
  schemaname || '.' || tablename AS table,
  n_live_tup AS rows
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC;"
```

### Reset Database

```bash
# Complete reset (destroys all data and recreates from init scripts)
docker-compose down -v
docker-compose up -d

# Wait for initialization (check logs)
docker-compose logs -f postgres
# Look for: "database system is ready to accept connections"
```

## Accessing from Devcontainer

The devcontainer uses `--network=host`, so the PostgreSQL database on `localhost:5432` is directly accessible.

Connection string:

```
postgresql+asyncpg://devuser:devpassword@localhost:5432/devdb
```

## Customization

### Change Port

Edit `docker-compose.yml`:

```yaml
ports:
  - "5433:5432" # Maps host 5433 to container 5432
```

Then update connection URLs to use port 5433.

### Change Credentials

Edit `docker-compose.yml` environment variables:

```yaml
environment:
  POSTGRES_DB: your_db_name
  POSTGRES_USER: your_user
  POSTGRES_PASSWORD: your_password
```

**Important**: Also update connection strings in tests and documentation!

### Add Custom Initialization

Add SQL files to `postgres/init/` directory. They run in alphabetical order:

- `01-*.sql`: Schema creation
- `02-*.sql`: Data seeding
- `03-*.sql`: Views and indexes
- `99-*.sql`: Custom scripts

Example:

```bash
# Create custom initialization script
cat > postgres/init/99-custom.sql << 'EOF'
-- Add custom tables or data here
CREATE TABLE custom_table (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100)
);
EOF

# Restart to apply
docker-compose down -v && docker-compose up -d
```

## Data Persistence

Database data is stored in a **Docker-managed named volume** (`db-connect-mcp-postgres-data`). This persists across container restarts but doesn't clutter your project directory.

**Advantages:**

- ✅ No local directory clutter
- ✅ No gitignore needed
- ✅ Docker manages storage location
- ✅ No permission issues

**To view volume info:**

```bash
docker volume inspect db-connect-mcp-postgres-data
```

**To completely reset:**

```bash
docker-compose down -v  # -v flag removes volumes
docker-compose up -d
```

## Troubleshooting

### Port already in use

```bash
# Check what's using port 5432
sudo lsof -i :5432

# Stop conflicting service
sudo systemctl stop postgresql
```

### Connection refused

```bash
# Check if container is running
docker-compose ps

# Check logs for errors
docker-compose logs postgres

# Verify health
docker-compose exec postgres pg_isready -U devuser -d devdb

# Test connection manually
docker exec -it db-connect-mcp-postgres psql -U devuser -d devdb -c "SELECT version();"
```

### Database not initializing

```bash
# Check init script logs
docker-compose logs postgres | grep -A 20 "init"

# Verify scripts are readable
ls -la postgres/init/

# Try manual initialization
docker-compose down -v
docker-compose up -d
docker-compose logs -f postgres
# Wait for "database system is ready to accept connections"
```

### Slow initialization

The initialization process inserts ~27,000 rows across multiple tables. On most systems this takes 10-30 seconds. Factors affecting speed:

- Disk I/O performance
- Available RAM
- CPU speed

To check progress:

```bash
# Monitor logs
docker-compose logs -f postgres

# Check if initialization is complete
docker exec -it db-connect-mcp-postgres psql -U devuser -d devdb -c "SELECT COUNT(*) FROM products;"
# Should return 2000
```

### Tests fail with "relation does not exist"

Ensure database initialization completed:

```bash
docker-compose logs postgres | grep "database system is ready"

# Verify tables exist
docker exec -it db-connect-mcp-postgres psql -U devuser -d devdb -c "\dt"
```

### Stale or incorrect data

Reset the database:

```bash
docker-compose down -v
docker-compose up -d
```

## Performance Tuning

For development, the default settings are optimized for quick startup and moderate performance. For production-like testing, edit `docker-compose.yml`:

```yaml
environment:
  POSTGRES_SHARED_BUFFERS: 512MB
  POSTGRES_EFFECTIVE_CACHE_SIZE: 2GB
  POSTGRES_WORK_MEM: 32MB
  POSTGRES_MAINTENANCE_WORK_MEM: 128MB
```

**Note**: Higher values require more RAM. Ensure your system has sufficient resources.

## Security Notes

**WARNING**: This configuration is for LOCAL DEVELOPMENT ONLY.

- Credentials are hardcoded (not suitable for production)
- Database is exposed on localhost (accessible to all local processes)
- No SSL/TLS encryption
- Weak password (`devpassword`)

Never use this configuration in production or expose it to the internet.

## CI/CD Integration

For GitHub Actions or other CI systems, use service containers instead:

```yaml
# .github/workflows/test.yml
services:
  postgres:
    image: postgres:17-alpine
    env:
      POSTGRES_DB: devdb
      POSTGRES_USER: devuser
      POSTGRES_PASSWORD: devpassword
    ports:
      - 5432:5432
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
```

Then initialize manually in workflow steps:

```yaml
steps:
  - name: Initialize database
    run: |
      PGPASSWORD=devpassword psql -h localhost -U devuser -d devdb -f tests/docker/postgres/init/01-create-schema.sql
      PGPASSWORD=devpassword psql -h localhost -U devuser -d devdb -f tests/docker/postgres/init/02-seed-data.sql
      PGPASSWORD=devpassword psql -h localhost -U devuser -d devdb -f tests/docker/postgres/init/03-create-views.sql
```

## Additional Resources

- [PostgreSQL 17 Documentation](https://www.postgresql.org/docs/17/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Testing Database Schema Reference](../../docs/TESTING_DATABASE.md)
- [Development Guide](../../docs/DEVELOPMENT.md)
