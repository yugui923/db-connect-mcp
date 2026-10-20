# 0001 — Evidence-based EXPLAIN interpretation

**Status:** accepted
**Date:** 2026-10-18
**Author:** Yuri Gui

## Context

EXPLAIN reports different evidence by engine and mode. PostgreSQL JSON plans can contain measured rows removed by a filter with ANALYZE; MySQL FORMAT=JSON contains estimates, while MySQL ANALYZE and ClickHouse EXPLAIN return text in this integration. A scan node alone does not establish a performance problem or justify an index. PostgreSQL drivers can return either serialized JSON or decoded JSON objects.

## Decision

Retain the existing `plan` text and `plan_json` structured/text response contracts. Interpret PostgreSQL nested scan nodes only when ANALYZE supplies observed filtered/returned rows and loops; use a conservative minimum of 1,000 removed rows and 90% filtered before suggesting review of the filter and existing indexes. For MySQL JSON, report estimated selective scans (at least 1,000 estimated rows examined and at most 10% retained) as warnings, not index recommendations. Do not infer performance problems from ClickHouse or MySQL text plan keywords. Preserve parsed PostgreSQL JSON arrays as structured plan data and serialize driver-decoded JSON before adapter parsing.

## Consequences

- Advice is tied to node-specific evidence and labels measured versus estimated values.
- A threshold-based heuristic can miss costly plans and is not a substitute for workload measurements or table statistics.
- Text-only plan formats receive no automatic optimization advice until a reliable parser and evidence model exist.
- EXPLAIN ANALYZE executes the read-only query and may still be expensive; callers choose whether to enable it.
