# 0003 — Expose database context as paginated MCP resources

**Status:** accepted
**Date:** 2026-08-18
**Author:** Yuri Gui

## Context

Database metadata is durable context rather than an action, but DB Connect has
historically exposed it only through tools. Current MCP clients can discover,
cache, and attach resources independently of tool execution. Large database
catalogs also require pagination and deterministic ordering so an agent can
traverse them without repeatedly loading the entire catalog or receiving
unstable pages.

Database metadata can vary by authorization context and can change while a
client is paging through it. Shared caching or index-only cursors would risk
serving one user's metadata to another user or silently skipping and repeating
items when a catalog changes.

## Decision

Expose database, schema, and table metadata through `db-connect://` resource
URIs, with schema and table URI templates for direct access. Resource listings
are sorted by URI and divided into pages of 100 items.
The opaque cursor contains an offset and a fingerprint of the ordered catalog
snapshot. A cursor is rejected as stale when that fingerprint changes, causing
the client to restart from the first page instead of consuming inconsistent
pages.

Schema, table, relationship, and search results are sorted at their owning
boundary so tools and resources share deterministic ordering. Tool catalogs
carry a one-hour private cache hint; resource catalogs and reads carry a
30-second private cache hint.

## Consequences

- Agents can attach database context without representing every metadata lookup
  as a tool action.
- Deterministic order makes results, snapshots, tests, and pagination stable.
- Cache scope remains private, preventing metadata reuse across authorization
  contexts.
- Listing resources currently builds the full catalog before slicing a page,
  so very large databases still incur discovery work on each uncached request.
- Catalog mutations invalidate cursors and require clients to restart paging;
  this favors consistency over uninterrupted traversal.
