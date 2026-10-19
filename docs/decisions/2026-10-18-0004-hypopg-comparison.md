# 0004 — Gate hypothetical PostgreSQL index comparisons

**Status:** proposed
**Date:** 2026-10-18
**Author:** Yuri Gui

## Context

Planner estimates can help shortlist candidate indexes, but real index creation is incompatible with read-only exploration. HypoPG creates session-local hypothetical indexes through extension functions; it must not be installed automatically or mistaken for a measured improvement.

## Decision

Hide `compare_hypothetical_index` unless the operator sets `DB_HYPOPG_ENABLED=true` (or configures `hypopg_enabled=True`). Require `opt_in=true` for every call. PostgreSQL only; discover an already installed extension and its schema before calling its qualified functions. Check the table and columns against the catalog. Support only simple identifiers and a deliberately narrow SELECT subset: no functions, CTEs, comments, literals, parameters or multiple statements. Reject unsupported SQL rather than attempting to parse it heuristically. Run two `EXPLAIN (FORMAT JSON)` statements without `ANALYZE` on the same connection, with local statement and lock timeouts, drop the hypothetical index and roll back the transaction. No extension installation or persistent DDL is issued.

## Consequences

- Cost and row estimates are optimizer predictions, not measured latency or proof an index helps. Statistics, concurrent changes and planner settings can change conclusions.
- Operators provision HypoPG and permissions separately; without it, the tool fails with a clear message.
- The constrained SQL subset excludes many useful analytical queries; expanding it requires a real PostgreSQL-aware SQL parser and explicit safety review.
- HypoPG session state is transient, but the database account still requires permission to call extension functions; prefer a dedicated least-privilege role.
