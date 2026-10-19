# 0001 — PostgreSQL health as an aggregate snapshot

**Status:** accepted
**Date:** 2026-10-18
**Author:** Yuri Gui

## Context

Read-only agents need actionable PostgreSQL health clues without unfettered access to catalog rows or monitoring privileges. Existing MCP tools return structured content alongside JSON text. A single check can be unavailable even when the others work.

## Decision

Add a PostgreSQL-only `postgres_health` tool that collects six aggregate catalog/statistics values, returns five typed findings, and explicitly distinguishes observed, insufficient, and permission-unavailable states. Thresholds are fixed advisory defaults; the result is a timestamped snapshot, not alerting. Cap query result rows regardless of a caller-supplied SQL LIMIT, and reject unbounded programmatic calls.

## Consequences

No new dependency, persistent monitoring state, extension installation, or exposure of slot names is needed. Catalog aggregates can still be costly on enormous installations, and the default thresholds are not a substitute for local operational policy. The SQL text validator is not a full SQL parser; database read-only roles remain essential. Existing callers using `limit=None` must now supply a bounded positive limit. Raw SHOW, DESCRIBE and EXPLAIN calls through `execute_query` are rejected; use dedicated metadata/explain tools. Only PostgreSQL permission-denied errors are represented as unavailable; operational failures surface as errors.
