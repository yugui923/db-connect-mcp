# Docker Test Infrastructure

This directory contains Docker Compose configuration and init scripts for test databases.

For full documentation -- container architecture, credentials, management commands, and troubleshooting -- see the **[Docker Setup Guide](../../docs/guides/DOCKER.md)**.

## Quick Start

```bash
# Start PostgreSQL (standalone)
docker-compose up -d

# Verify
docker-compose ps

# Connect
psql -h localhost -U devuser -d devdb  # Password: devpassword

# Reset
docker-compose down -v && docker-compose up -d
```

For the full devcontainer with PostgreSQL + MySQL + SSH tunnel, rebuild the devcontainer from `.devcontainer/`.
