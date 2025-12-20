#!/bin/bash
# ==============================================================================
# PostgreSQL 17 DevContainer Feature Installation Script
# ==============================================================================
# This script installs PostgreSQL 17 from the official apt repository.
# It runs during container build as root.
#
# Security:
# - PostgreSQL runs as 'postgres' user (non-root)
# - Only listens on localhost by default
# - No elevated privileges after installation
# ==============================================================================

set -e

# Feature options (passed from devcontainer-feature.json)
INSTALL_CLIENT="${INSTALLCLIENT:-true}"
INSTALL_SERVER="${INSTALLSERVER:-true}"
CREATE_TEST_DB="${CREATETESTDB:-true}"
TEST_DB_USER="${TESTDBUSER:-dbconnect}"
TEST_DB_PASSWORD="${TESTDBPASSWORD:-dbconnect_dev_password}"
TEST_DB_NAME="${TESTDBNAME:-db_connect_test}"

echo "=== Installing PostgreSQL 17 ==="
echo "  Install Client: $INSTALL_CLIENT"
echo "  Install Server: $INSTALL_SERVER"
echo "  Create Test DB: $CREATE_TEST_DB"

# ==============================================================================
# Add PostgreSQL Official APT Repository
# ==============================================================================

apt-get update
apt-get install -y curl ca-certificates gnupg lsb-release

# Add PostgreSQL signing key
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-keyring.gpg

# Add repository
echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list

apt-get update

# ==============================================================================
# Install PostgreSQL Components
# ==============================================================================

PACKAGES=""

if [ "$INSTALL_CLIENT" = "true" ]; then
    PACKAGES="$PACKAGES postgresql-client-17"
fi

if [ "$INSTALL_SERVER" = "true" ]; then
    PACKAGES="$PACKAGES postgresql-17 postgresql-contrib-17"
fi

if [ -n "$PACKAGES" ]; then
    apt-get install -y $PACKAGES
fi

# ==============================================================================
# Configure PostgreSQL for Development
# ==============================================================================

if [ "$INSTALL_SERVER" = "true" ]; then
    echo "=== Configuring PostgreSQL for development ==="

    # Ensure run directory exists
    mkdir -p /var/run/postgresql
    chown postgres:postgres /var/run/postgresql

    # Create development configuration
    mkdir -p /etc/postgresql/17/main/conf.d

    cat > /etc/postgresql/17/main/conf.d/development.conf << 'PGCONF'
# ==============================================================================
# Development Configuration for PostgreSQL 17
# ==============================================================================
# Optimized for development, NOT for production!
# ==============================================================================

# Connection settings
listen_addresses = 'localhost'
port = 5432
max_connections = 100

# Memory settings (tuned for dev container)
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 16MB
maintenance_work_mem = 128MB

# WAL settings (relaxed for development speed)
wal_level = minimal
max_wal_senders = 0
fsync = off
synchronous_commit = off
full_page_writes = off
checkpoint_timeout = 30min

# Logging
logging_collector = on
log_directory = 'pg_log'
log_filename = 'postgresql-%Y-%m-%d.log'
log_statement = 'none'
log_min_duration_statement = 1000
PGCONF

    # Configure authentication (trust local, password for TCP)
    cat > /etc/postgresql/17/main/pg_hba.conf << 'PGHBA'
# PostgreSQL Client Authentication Configuration
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     trust
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256
PGHBA

    chown postgres:postgres /etc/postgresql/17/main/conf.d/development.conf
    chown postgres:postgres /etc/postgresql/17/main/pg_hba.conf

    echo "PostgreSQL configured for development use"
fi

# ==============================================================================
# Create Database Initialization Script
# ==============================================================================

if [ "$CREATE_TEST_DB" = "true" ] && [ "$INSTALL_SERVER" = "true" ]; then
    echo "=== Creating database initialization script ==="

    cat > /usr/local/bin/init-test-database.sh << INITSCRIPT
#!/bin/bash
# Initialize test database for db-connect-mcp
# Run this after PostgreSQL service is started

set -e

echo "=== Initializing test database ==="

# Wait for PostgreSQL to be ready
MAX_RETRIES=30
RETRY_COUNT=0
until pg_isready -h localhost -p 5432 -U postgres 2>/dev/null; do
    RETRY_COUNT=\$((RETRY_COUNT + 1))
    if [ \$RETRY_COUNT -ge \$MAX_RETRIES ]; then
        echo "Error: PostgreSQL did not start within expected time"
        exit 1
    fi
    echo "Waiting for PostgreSQL... (\$RETRY_COUNT/\$MAX_RETRIES)"
    sleep 1
done

echo "PostgreSQL is ready!"

# Check if database already exists
if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw ${TEST_DB_NAME}; then
    echo "Database '${TEST_DB_NAME}' already exists. Skipping."
    exit 0
fi

# Create user and database
echo "Creating user '${TEST_DB_USER}' and database '${TEST_DB_NAME}'..."
sudo -u postgres psql << EOF
CREATE USER ${TEST_DB_USER} WITH PASSWORD '${TEST_DB_PASSWORD}';
CREATE DATABASE ${TEST_DB_NAME}
    WITH OWNER = ${TEST_DB_USER}
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.UTF-8'
    LC_CTYPE = 'en_US.UTF-8';
GRANT ALL PRIVILEGES ON DATABASE ${TEST_DB_NAME} TO ${TEST_DB_USER};
EOF

echo "Database created successfully!"

# Run initialization scripts if they exist
INIT_DIR="/workspaces/db-connect-mcp/tests/docker/postgres/init"
if [ -d "\$INIT_DIR" ]; then
    echo "Running initialization scripts from \$INIT_DIR..."
    for sql_file in \$(ls -1 "\$INIT_DIR"/*.sql 2>/dev/null | sort); do
        echo "  Running: \$(basename \$sql_file)"
        sudo -u postgres psql -d ${TEST_DB_NAME} -f "\$sql_file"
    done
    echo "Schema and data initialized!"
else
    echo "Note: No init scripts found at \$INIT_DIR"
fi

echo ""
echo "=== Test database ready! ==="
echo "Connection: postgresql+asyncpg://${TEST_DB_USER}:${TEST_DB_PASSWORD}@localhost:5432/${TEST_DB_NAME}"
INITSCRIPT

    chmod +x /usr/local/bin/init-test-database.sh
    echo "Created /usr/local/bin/init-test-database.sh"
fi

# ==============================================================================
# Cleanup
# ==============================================================================

apt-get clean
rm -rf /var/lib/apt/lists/*

echo "=== PostgreSQL 17 installation complete ==="
