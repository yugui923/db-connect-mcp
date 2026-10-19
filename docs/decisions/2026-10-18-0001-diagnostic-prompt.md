# 0001 — Offer diagnosis as an opt-in MCP prompt

**Status:** proposed
**Date:** 2026-10-18
**Author:** Yuri Gui

## Context

Agents need a reproducible path from object discovery through workload, schema, plan, and evidence. The available telemetry differs by database engine and authorization context. Automatic orchestration would risk expensive queries, unsupported cross-engine assumptions, and unintended disclosure of result data.

## Decision

Expose a `diagnose_query` MCP prompt requiring a user-provided problem. It returns guidance only: no database calls, external LLM requests, or automatic plan execution. Agents discover existing typed tools and resources independently, use only available read-only workload tools, and explicitly distinguish observations from hypotheses. Keep existing tool contracts and legacy text outputs unchanged.

## Consequences

Clients with MCP prompt support get an opt-in workflow without a new database permission surface. Clients without prompt support continue using tools and resources as before. The server does not enforce the suggested sequence: clients remain responsible for consent, tool selection, and evidence quality. Richer PostgreSQL-specific workload/health and plan interpretation can be integrated when separately shipped; this prompt does not require them.
