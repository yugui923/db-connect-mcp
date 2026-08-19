# 0004 — Instrument the MCP boundary with privacy-conscious spans

**Status:** accepted

**Date:** 2026-08-18

**Author:** Yuri Gui

## Context

db-connect-mcp serves requests over both stdio and Streamable HTTP. Existing
logs show individual events but do not preserve the relationships between MCP
operations, tools, resources, and failures. OpenTelemetry now defines GenAI MCP
semantic conventions for those relationships.

Database tool inputs and results can contain credentials, SQL, schema details,
or business data. General-purpose telemetry must not copy those payloads into a
second system by default.

## Decision

Create OpenTelemetry server spans at the MCP request boundary for tool and
resource operations. Use the current MCP semantic attributes for the method,
protocol version, tool name, and resource URI, plus low-cardinality error types.

Depend only on the OpenTelemetry API. Do not bundle or configure an SDK,
processor, or exporter. Applications that embed or launch db-connect-mcp remain
responsible for their telemetry provider and destination.

Do not record tool arguments, query results, exception messages, or MCP message
bodies. Error telemetry records only the exception class or a generic tool
error classification.

## Consequences

- With no SDK configured, instrumentation is a no-op and performs no network
  communication.
- Operators can connect spans to their existing OpenTelemetry pipeline without
  changing db-connect-mcp internals.
- Default spans remain useful for latency and failure analysis while avoiding
  database payload disclosure.
- Exporter choice, sampling, and trace storage remain deployment concerns.
- MCP semantic conventions are still evolving, so attribute names may require
  a compatibility update in a future release.
