# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please use [GitHub's private vulnerability reporting](https://github.com/yugui923/db-connect-mcp/security/advisories/new) to submit a report. Include:

- A description of the vulnerability
- Steps to reproduce the issue
- Any potential impact

## What to Expect

- You will receive an acknowledgment within **one week**
- A fix will be prioritized based on severity
- You will be credited in the fix (unless you prefer otherwise)

## Scope

This project is a **read-only** database MCP server. Security concerns include but are not limited to:

- Bypass of read-only query enforcement
- SQL injection through MCP tool inputs
- Credential exposure (database URLs, SSH keys)
- Unauthorized access to database metadata
