# Database Expansion Recommendations

> Generated: 2026-02-10

## Current Stack

The MCP server uses **SQLAlchemy async** as the core abstraction layer, with these async drivers:

- **PostgreSQL**: `asyncpg`
- **MySQL/MariaDB**: `aiomysql`
- **ClickHouse**: `clickhouse-connect` (via `asynch` driver)

Each adapter is ~350-550 lines implementing the `BaseAdapter` interface (10 abstract methods covering metadata enrichment, statistics, sampling, and EXPLAIN plans).

## Recommended Databases to Add

### Tier 1 — Easy (mature SQLAlchemy async drivers exist)

| Database | Async Driver | SQLAlchemy Dialect | Effort | Notes |
|---|---|---|---|---|
| **SQLite** | `aiosqlite` | `sqlite+aiosqlite://` | **Low** | Very popular for local/embedded use. No schema concept simplifies the adapter. Limited EXPLAIN output. Great for letting users explore local `.db` files. |
| **MariaDB** (dedicated) | `asyncmy` | `mysql+asyncmy://` | **Very low** | The MySQL adapter already handles most MariaDB cases. `asyncmy` is a faster alternative to `aiomysql` and could be offered as an option. Mostly a driver swap, not a new adapter. |
| **CockroachDB** | `asyncpg` | `cockroachdb+asyncpg://` | **Low** | Wire-compatible with PostgreSQL. The Postgres adapter would work with minor tweaks (different `version()` output, no `TABLESAMPLE`, different EXPLAIN format). Needs the `sqlalchemy-cockroachdb` dialect package. |

### Tier 2 — Medium (drivers exist but need more adapter work)

| Database | Async Driver | SQLAlchemy Dialect | Effort | Notes |
|---|---|---|---|---|
| **Microsoft SQL Server** | `aioodbc` | `mssql+aioodbc://` | **Medium** | Very high enterprise demand. Uses `INFORMATION_SCHEMA` like MySQL. Different quoting (`[brackets]`), `TOP N` instead of `LIMIT`, `SET TRANSACTION ISOLATION LEVEL READ ONLY` semantics differ. ~400 lines of adapter code. |
| **Oracle** | `oracledb` (async mode) | `oracle+oracledb://` | **Medium** | High enterprise demand. Has async support in `python-oracledb`. Oracle-specific metadata views (`ALL_TAB_COLUMNS`, `ALL_CONSTRAINTS`). Different quoting and schema model. ~450 lines. |
| **Trino / Presto** | `aiotrino` or `trino` | `trino://` | **Medium** | Popular for data lake querying. SQLAlchemy dialect exists (`sqlalchemy-trino`). Catalog/schema model is different. No foreign keys. Statistics queries differ significantly. |

### Tier 3 — Harder (limited async/SQLAlchemy support)

| Database | Challenge | Notes |
|---|---|---|
| **DuckDB** | No official SQLAlchemy async driver | Very popular for analytics. `duckdb_engine` exists for sync SQLAlchemy. Would need the `AsyncConnectionWrapper` (which already exists). High user demand. |
| **Snowflake** | `snowflake-sqlalchemy` exists but async is limited | Massive enterprise demand. Would need sync-to-async wrapping. Snowflake-specific metadata and EXPLAIN. |
| **BigQuery** | `sqlalchemy-bigquery` is sync-only | High demand for GCP users. Would need sync wrapping. Very different SQL dialect. |

## Ease of Implementation

The architecture makes this relatively straightforward:

1. **Clean adapter interface** — `BaseAdapter` is well-defined with 10 methods. A new database just implements that contract.
2. **Factory pattern** — Adding a new dialect is a 3-line change in `create_adapter()`.
3. **SQLAlchemy abstraction** — The core components (`MetadataInspector`, `QueryExecutor`, `StatisticsAnalyzer`) work through the adapter, so they don't change.
4. **Sync wrapper exists** — `AsyncConnectionWrapper` already handles databases without native async drivers.

**Realistic effort per adapter:**

- ~1-2 days for Tier 1 (SQLite, CockroachDB)
- ~3-5 days for Tier 2 (MSSQL, Oracle, Trino)
- ~5-7 days for Tier 3 (DuckDB, Snowflake, BigQuery) due to driver workarounds

## Top 3 Recommendations

1. **SQLite** — Lowest effort, huge user base, lets people explore local databases instantly without any server setup.
2. **Microsoft SQL Server** — Highest enterprise demand, fills the biggest gap in the current offering.
3. **DuckDB** — Fastest-growing analytics database, natural fit for a read-only MCP server since DuckDB excels at read-heavy analytical queries.
