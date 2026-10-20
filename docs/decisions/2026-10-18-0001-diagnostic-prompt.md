# 0001 — Offer diagnosis as an opt-in MCP prompt

**Status:** proposed
**Date:** 2026-10-18
**Author:** Yuri Gui

## Context

Agents need a reproducible path from object discovery through workload, schema, plan, and evidence. The available telemetry differs by database engine and authorization context. Automatic orchestration would risk expensive queries, unsupported cross-engine assumptions, and unintended disclosure of result data.

## Decision

Expose a `diagnose_query` MCP prompt requiring a user-provided problem. It returns guidance only: the server makes no database calls or external model requests to construct it, and never automatically executes plans. Agents inspect tools exposed by their MCP host (requesting a host discovery refresh if needed), use only available read-only workload tools, and explicitly distinguish observations from hypotheses. A hosted model may receive tool results through ordinary MCP host operation; users must verify host/model data egress before sensitive retrieval. Keep existing tool contracts and legacy text outputs unchanged.

## Consequences

Clients with MCP prompt support get an opt-in workflow without a new database permission surface. Clients without prompt support continue using tools and resources as before. The server does not enforce the suggested sequence: clients remain responsible for consent, tool selection, and evidence quality. Richer PostgreSQL-specific workload/health and plan interpretation can be integrated when separately shipped; this prompt does not require them.
