#!/usr/bin/env bash
# Runs once after the dev container is created.
#
# Intentionally does NOT install project dependencies (npm install,
# uv sync, pip install, etc.). Dev containers may be applied to repos
# with untrusted or compromised dependencies, and dependency installs
# execute arbitrary install hooks. Run them yourself after reviewing
# the lockfile and the codebase.

set -euo pipefail

git config --global --add safe.directory /workspace

cat <<'BANNER'

========================================
  Dev Container Ready
========================================
  Base:    Ubuntu 24.04
  User:    vscode
  Shell:   zsh (autosuggestions, syntax-highlighting)
----------------------------------------
  Runtime Manager: mise (Python 3.14.6, Node 24.18.0 LTS)
  Package Managers: uv (7-day cooldown), npm 11.18.0 (7-day cooldown)
  Python Tools:  ruff, black, mypy, pytest
  Node Tools:    typescript, tsx, prettier, eslint
  DB Clients:    sqlite3, mysql-client, postgresql-client
  AI:            Claude Code, OpenAI Codex
========================================

Note: project dependencies are NOT installed automatically.
Review the lockfile, then run `uv sync` / `npm install` yourself.
BANNER
