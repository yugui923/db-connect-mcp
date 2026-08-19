# 0002 — Publish structured tool contracts alongside JSON text

**Status:** accepted
**Date:** 2026-08-18
**Author:** Yuri Gui

## Context

DB Connect MCP tool results have historically been JSON serialized into MCP
text content. That representation works with older clients, but current MCP
clients can use a tool's `outputSchema` and the corresponding
`structuredContent` result to validate data, render it consistently, and pass
it between agents without reparsing text.

The MCP protocol versions supported by MCP SDK 2.0 require structured tool
outputs to have an object at the root for compatibility with pre-2026 clients.
Three existing tools naturally return lists, and changing their text response
shape would break current consumers.

## Decision

Every tool publishes a JSON Schema output contract and returns matching
structured content. Object results retain their natural shape. List results use
an `items` object envelope only in structured content; their legacy JSON text
remains an array. When a handler supplies truncation metadata, structured
results expose it as `_truncation_info` without the legacy `data` wrapper.

Tool calls continue to include the existing JSON text content. Tool errors add
a stable machine-readable `error.code` and `error.message` while retaining a
human-readable text message. All tools are annotated as read-only,
non-destructive, idempotent with respect to external state, and limited to the
configured database rather than the open world.

## Consequences

- Modern clients can validate and consume results without parsing JSON text.
- Older clients keep the response representation they already consume.
- List results deliberately have different root shapes in text and structured
  content, which must remain covered by compatibility tests.
- Schemas and runtime serialization now form a public contract and must be
  updated together whenever result models change.
- Returning both representations duplicates response bytes until support for
  legacy text-only clients is intentionally retired.
