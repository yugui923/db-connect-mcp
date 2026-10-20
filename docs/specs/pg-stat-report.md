# Spec — PostgreSQL top-query report

**Status:** implemented
**Date:** 2026-10-18
**Author:** Yuri Gui

## Overview

An explicitly enabled MCP tool reports bounded, aggregated statistics for the configured PostgreSQL database and current database user. It is not advertised for other engines or when disabled.

## Interface

Set `ENABLE_PG_STAT_STATEMENTS=true` (default false), or `DatabaseConfig(enable_pg_stat_statements=True)`. `get_top_queries` takes `limit` (1–50, default 10), `include_query_text` (default false), and `query_text_limit` (1–2000 characters, default 200). Calls must be initiated by the MCP client; nothing is collected or sent automatically. The output is an object in both legacy JSON text and typed `structuredContent`, with `status` and `queries`.

## Data models

Each query contains `query_id`, `calls`, `total_exec_time_ms`, `mean_exec_time_ms`, `rows`, and `query` (null unless text is requested). Ordered by total execution time descending, limited in SQL. The serialized JSON text response is capped at 50,000 UTF-8 bytes: if it would exceed the cap, all query text is omitted and `truncated=true`; if metrics alone exceed it, the tail is dropped. The same bounded payload is used for structured content. Metrics are cumulative since the extension's last reset, not live measurements; `query_id` may be null. Text can contain sensitive literals or identifiers even when normalized, so request it only when appropriate. Returned text is bounded; `pg_stat_statements` stores representative texts separately and may discard texts under storage pressure. `track_activity_query_size` applies to `pg_stat_activity.query`, not to `pg_stat_statements` texts. Without text opt-in, the report calls the extension function with `showtext := false` to avoid loading stored query texts; if that overload is unavailable, it returns `unsupported_version` rather than reading the view. Sorting tracked statements happens before LIMIT and may be expensive; this report sets a transaction-local 5-second statement timeout for that query. A timeout is an ordinary tool error, not an unavailable-extension status.

## Error handling

`status` is `available`, `extension_not_installed`, `extension_not_loaded`, `permission_denied`, or `unsupported_version`. An absent extension returns an empty result, never installs or enables it. Other unexpected database failures return normal MCP tool errors. PostgreSQL administrators must preload `pg_stat_statements` and install the extension separately; no elevated privileges are requested by this tool. The query only selects rows for the current database and user. SQLSTATE-based errors expose no statement contents in the availability result.

## Dependencies

Uses existing SQLAlchemy and PostgreSQL system catalogs. Supports both `total_exec_time` (PG 13+) and legacy `total_time` columns. No new packages.
