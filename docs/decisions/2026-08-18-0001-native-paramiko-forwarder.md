# 0001 — Use a native Paramiko SSH forwarder

**Status:** accepted
**Date:** 2026-08-18
**Author:** Yuri Gui

## Context

DB Connect MCP uses `sshtunnel` 0.4.0 for SSH port forwarding. That release is
unmaintained and requires process-wide monkey-patches to work with Paramiko 5.
Production diagnostics also found a bastion where the package's low-level
transport path authenticated successfully but consistently timed out opening a
database channel, while Paramiko's supported `SSHClient.connect()` path opened
the same channel reliably.

The database engine is created with a URL containing the tunnel's local port.
Consequently, SSH recovery must not allocate a different listener port after
the engine has been initialized.

## Decision

Replace `sshtunnel` with a first-party forwarder built on Paramiko's public
`SSHClient`, `Transport`, and `Channel` APIs and Python's standard networking
primitives.

The local TCP listener and SSH connection have independent lifecycles. The
listener keeps one stable port for its lifetime. If the SSH transport becomes
unusable, a serialized recovery operation connects and preflights a replacement
client, then atomically makes that transport available to new local
connections. Existing channels retain a lease on their transport generation so
one connection's recovery does not interrupt unrelated queries.

Startup verifies authentication and a `direct-tcpip` channel to the configured
database target before publishing the listener. Channel creation may be retried
once on a replacement transport before any database bytes are relayed; SQL
operations themselves are never replayed.

## Consequences

- DB Connect owns a small amount of socket relay and lifecycle code that needs
  focused concurrency, backpressure, half-close, and cleanup tests.
- `sshtunnel` and its global compatibility monkey-patches leave the runtime
  dependency graph.
- SSH connection, banner, authentication, and channel timeouts can be tuned
  independently while the legacy timeout remains a compatibility fallback.
- Host-key checking becomes an explicit policy. Compatibility mode warns and
  accepts keys without modifying `known_hosts`; strict mode rejects unknown or
  changed keys from system or configured known-hosts files.
- A failed in-flight query can still surface to its caller. Recovery applies to
  subsequent connections and never guesses whether a query is safe to replay.
