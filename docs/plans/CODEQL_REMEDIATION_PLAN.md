# CodeQL Remediation Plan

Plan to resolve ~35 CodeQL code scanning alerts in the repository.

## Alert Breakdown

### 1. SQL Injection via f-strings (~14 alerts) — CRITICAL

f-strings embedding identifiers (table names, column names) directly into SQL `text()` calls. CodeQL flags these even though the identifiers are validated, because it cannot prove the sanitization is sufficient.

**Files:**

- `src/db_connect_mcp/adapters/postgresql.py` — ~7 instances (regclass casts, column references, `FROM {table_ref}`)
- `src/db_connect_mcp/adapters/mysql.py` — ~4 instances (backtick-quoted column names)
- `src/db_connect_mcp/adapters/clickhouse.py` — ~4 instances (backtick-quoted column names)
- `src/db_connect_mcp/core/executor.py` — `f"EXPLAIN {query}"` on line 307, `f"{query} LIMIT {limit}"` on line 290

**Fix strategy:** These are identifier injections (table/column names), not value injections, so parameterized queries won't work directly. The approach would be:

- Add a strict identifier validation/quoting utility that uses the adapter's native quoting mechanism
- For PostgreSQL: use `quote_ident()` equivalent
- For MySQL/ClickHouse: validate against `^[a-zA-Z_][a-zA-Z0-9_]*$` and double-quote/backtick-wrap
- Mark validated usages with a CodeQL suppression comment where the validation is demonstrably safe

### 2. Log Injection (~14 alerts) — MEDIUM

User-influenced data (hostnames, ports, error messages, OAuth issuer URLs, scopes) written to log statements via f-strings without sanitization of newline/control characters.

**Files:**

- `src/db_connect_mcp/server.py` — lines 1090, 1092, 1107, 1324
- `src/db_connect_mcp/auth/jwt_verifier.py` — lines 92, 147-148, 176, 179, 182
- `src/db_connect_mcp/models/config.py` — lines 392, 465
- `src/db_connect_mcp/core/tunnel.py` — lines 80-83, 109, 320
- `src/db_connect_mcp/core/connection.py` — lines 267, 270
- `src/db_connect_mcp/core/analyzer.py` — line 110

**Fix strategy:** Create a small `sanitize_log_value(value: str) -> str` helper that strips/replaces newlines and control characters (`\n`, `\r`, `\x00`, etc.), then wrap user-influenced values in log calls with it.

### 3. Clear-text Logging of Exceptions (~4 alerts) — MEDIUM

Exception messages that may contain sensitive info (schema names, table names, connection details) logged in warning messages.

**Files:**

- `src/db_connect_mcp/adapters/postgresql.py` — lines 135, 180-181
- `src/db_connect_mcp/adapters/mysql.py` — lines 131-132
- `src/db_connect_mcp/adapters/clickhouse.py` — lines 166-167

**Fix strategy:** Sanitize or truncate exception messages before logging, or log at `debug` level instead of `warning` for messages that could contain sensitive context.

### 4. Binding to 0.0.0.0 (2 alerts) — MEDIUM

Default host `0.0.0.0` binds to all network interfaces.

**Files:**

- `src/db_connect_mcp/server.py` — line 1114 (function default), line 1262 (CLI argparse default)

**Fix strategy:** Change the default to `127.0.0.1` (localhost only). Users who need external access can explicitly pass `--host 0.0.0.0`.

### 5. Password Not Hidden in URL Processing (2 alerts) — MEDIUM

`render_as_string(hide_password=False)` explicitly exposes credentials during URL manipulation.

**Files:**

- `src/db_connect_mcp/models/config.py` — lines 284, 469

**Fix strategy:** These are used for internal URL rewriting (not logging), but CodeQL flags them. Either pass `hide_password=True` when possible, or if the raw URL is needed for connection purposes, add a suppression comment explaining why.

### 6. Hardcoded Credentials (~4 alerts) — LOW

Test fixtures with embedded passwords.

**Files:**

- `tests/conftest.py` — line 71
- `tests/unit/test_tunnel.py` — line 26
- `tests/docker/docker-compose.yml` — line 10

**Fix strategy:** These are intentional test-only credentials. Add CodeQL suppression comments or move to environment variables with defaults.

### 7. Insecure Protocol (1 alert) — LOW

No HTTPS enforcement when constructing the JWKS URI from the issuer URL.

**Files:**

- `src/db_connect_mcp/auth/jwt_verifier.py` — line 82

**Fix strategy:** Add validation that the issuer URL starts with `https://`.

## Implementation Order

| Phase | Category                                             | Alerts Fixed | Effort  |
| ----- | ---------------------------------------------------- | ------------ | ------- |
| 1     | Default bind `127.0.0.1`                             | 2            | ~5 min  |
| 2     | HTTPS enforcement on JWKS URI                        | 1            | ~5 min  |
| 3     | Log injection sanitizer + apply                      | ~14          | ~30 min |
| 4     | Clear-text exception logging                         | ~4           | ~15 min |
| 5     | SQL identifier quoting utility + apply across adapters | ~14        | ~1 hr   |
| 6     | Password URL handling                                | 2            | ~10 min |
| 7     | Test credential suppressions                         | ~4           | ~10 min |

Phases 1-4 are straightforward. Phase 5 (SQL identifiers) is the bulk of the work since it touches all three database adapters and the executor.
