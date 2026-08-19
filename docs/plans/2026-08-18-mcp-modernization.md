# Plan — MCP modernization

**Status:** in-progress
**Date:** 2026-08-18
**Author:** Yuri Gui

## Goal

Modernize db-connect-mcp for the 2026 MCP protocol and current agent workflows
without sacrificing compatibility with existing clients or the project's
read-only database safety guarantees.

## Scope

The work is split into independently reviewable and releasable changes:

1. `0.7.1`: synchronize release metadata and public documentation.
2. `0.8.0`: add typed tool outputs, annotations, and protocol conformance.
3. `0.9.0`: add resources, cursor pagination, stable ordering, and cache-aware
   database context.
4. `0.9.1`: strengthen live HTTP coverage, agent evaluations, and telemetry.

Semantic-layer integrations, additional database engines, multi-tenant routing,
and MCP Apps remain out of scope for this sequence.

## Approach

Each phase is delivered as a separate pull request. Later pull requests are
stacked on the preceding phase until the earlier work is reviewed and merged.
Every phase retains text output for older clients, exercises supported database
dialects, and passes the repository's formatter, linter, type checker, tests,
build, and secret scan before review.

## Open Questions

None. Product-level choices for semantic metadata and interactive applications
will be evaluated after the protocol and context foundations are released.
