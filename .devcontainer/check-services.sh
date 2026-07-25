#!/usr/bin/env bash
# Return success when every in-container development service is healthy.

set -euo pipefail

PGPASSWORD=devpassword pg_isready -h 127.0.0.1 -p 5432 -U devuser -d devdb >/dev/null
mysqladmin ping --host=127.0.0.1 --user=testuser --password=testpass --silent
clickhouse-client --host 127.0.0.1 --query 'SELECT 1' >/dev/null
nc -z 127.0.0.1 2222
