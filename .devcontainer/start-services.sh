#!/usr/bin/env bash
# Start and initialize the databases used by the in-container test suite.

set -euo pipefail

wait_for() {
    local description="$1"
    shift
    for _ in $(seq 1 90); do
        if "$@" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    echo "Timed out waiting for ${description}" >&2
    return 1
}

mkdir -p /run/sshd /var/run/mysqld
chown mysql:mysql /var/run/mysqld
ssh-keygen -A

if ! id tunneluser >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash tunneluser
fi
echo 'tunneluser:tunnelpass' | chpasswd
cat > /etc/ssh/sshd_config.d/99-db-connect-mcp.conf <<'EOF'
Port 2222
ListenAddress 127.0.0.1
PasswordAuthentication yes
PermitRootLogin no
AllowTcpForwarding yes
GatewayPorts no
UsePAM no
EOF

service postgresql start
service mysql start
service clickhouse-server start
service ssh start

wait_for PostgreSQL pg_isready -h 127.0.0.1 -p 5432
wait_for MySQL mysqladmin ping --user=root
wait_for ClickHouse clickhouse-client --host 127.0.0.1 --query 'SELECT 1'
wait_for SSH nc -z 127.0.0.1 2222

if ! runuser -u postgres -- psql -tAc \
    "SELECT 1 FROM pg_roles WHERE rolname = 'devuser'" | grep -q 1; then
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 \
        -c "CREATE ROLE devuser LOGIN PASSWORD 'devpassword'"
fi
if ! runuser -u postgres -- psql -tAc \
    "SELECT 1 FROM pg_database WHERE datname = 'devdb'" | grep -q 1; then
    runuser -u postgres -- createdb --owner=devuser devdb
    for script in /opt/db-connect-mcp/init/postgres/*.sql; do
        PGPASSWORD=devpassword psql -v ON_ERROR_STOP=1 \
            -h 127.0.0.1 -U devuser -d devdb -f "$script"
    done
fi

mysql --user=root <<'SQL'
CREATE DATABASE IF NOT EXISTS devdb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'testuser'@'%' IDENTIFIED BY 'testpass';
GRANT ALL PRIVILEGES ON devdb.* TO 'testuser'@'%';
FLUSH PRIVILEGES;
SQL
if ! mysql --user=root --batch --skip-column-names -e \
    "SELECT 1 FROM information_schema.tables WHERE table_schema='devdb' AND table_name='products'" \
    | grep -q 1; then
    for script in /opt/db-connect-mcp/init/mysql/*.sql; do
        mysql --user=root devdb < "$script"
    done
fi

clickhouse-client --query 'CREATE DATABASE IF NOT EXISTS testdb'
if ! clickhouse-client --query \
    "EXISTS TABLE testdb.products" | grep -q 1; then
    for script in /opt/db-connect-mcp/init/clickhouse/*.sql; do
        clickhouse-client --multiquery < "$script"
    done
fi

/usr/local/bin/check-dev-services
exec sleep infinity
