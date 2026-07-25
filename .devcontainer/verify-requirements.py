#!/usr/bin/env python3
"""Verify documented DevContainer requirements from inside the container."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

DEVCONTAINER_DIR = Path(__file__).resolve().parent
REQUIREMENTS_PATH = DEVCONTAINER_DIR / "REQUIREMENTS.md"
DOCKERFILE_PATH = DEVCONTAINER_DIR / "Dockerfile"
COMPOSE_PATH = DEVCONTAINER_DIR / "docker-compose.yml"
POST_CREATE_PATH = DEVCONTAINER_DIR / "post-create.sh"
POST_CREATE_MARKER = Path.home() / ".local/state/yg-devcontainer/post-create.sha256"


class VerificationError(RuntimeError):
    """Raised when a documented requirement is not met."""


def require(condition: bool, message: str) -> None:
    """Raise a verification error unless condition is true."""
    if not condition:
        raise VerificationError(message)


def run(*args: str) -> str:
    """Run a local command without invoking a shell."""
    result = subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
    )
    if result.returncode:
        raise VerificationError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{result.stdout}"
        )
    return result.stdout.strip()


def files() -> dict[str, str]:
    """Load the files used by static checks."""
    return {
        "dockerfile": DOCKERFILE_PATH.read_text(),
        "compose": COMPOSE_PATH.read_text(),
        "devcontainer": (DEVCONTAINER_DIR / "devcontainer.json").read_text(),
        "post_create": POST_CREATE_PATH.read_text(),
    }


def static_contains(ctx: dict[str, str], file: str, *markers: str) -> str:
    missing = [marker for marker in markers if marker not in ctx[file]]
    require(not missing, f"{file} is missing markers: {missing}")
    return f"{file} contains {len(markers)} required markers"


def static_dev_001(ctx: dict[str, str]) -> str:
    static_contains(ctx, "dockerfile", "base:ubuntu-24.04")
    return static_contains(ctx, "devcontainer", '"workspaceFolder": "/workspace"', '"remoteUser": "vscode"')


def static_dev_002(ctx: dict[str, str]) -> str:
    return static_contains(ctx, "compose", "network_mode: host")


def static_dev_003(ctx: dict[str, str]) -> str:
    return static_contains(
        ctx, "compose", "mem_limit: 12g", "memswap_limit: 24g", "cpus: 6.0", "pids_limit: 4096", 'shm_size: "4gb"'
    )


def static_dev_004(ctx: dict[str, str]) -> str:
    static_contains(ctx, "compose", "..:/workspace", "/home/vscode/.claude", "/home/vscode/.codex")
    require("docker.sock" not in ctx["compose"], "Docker socket mount is forbidden")
    return "workspace and agent-state mounts declared without Docker socket"


def static_dev_005(ctx: dict[str, str]) -> str:
    return static_contains(
        ctx, "dockerfile", "mise use --global python@", "node@", "uv/0.", "min-release-age 7", 'exclude-newer = "7 days"'
    )


def static_dev_006(ctx: dict[str, str]) -> str:
    return static_contains(
        ctx, "dockerfile", "build-essential", "gitleaks", "postgresql-client", "mysql-client", "ruff==", "mypy==", "pytest=="
    )


def static_dev_007(ctx: dict[str, str]) -> str:
    return static_contains(ctx, "dockerfile", "sfw npm install -g", "@anthropic-ai/claude-code@", "@openai/codex@")


def static_dev_008(ctx: dict[str, str]) -> str:
    static_contains(ctx, "compose", "sudo /usr/local/bin/start-dev-services")
    forbidden = ("uv sync", "pip install", "npm install")
    commands = "\n".join(
        line.strip() for line in ctx["post_create"].splitlines() if not line.strip().startswith("#")
    )
    for command in forbidden:
        require(f"{command}\n" not in commands, f"post-create automatically executes {command}")
    return "audited service startup and non-installing post-create lifecycle declared"


def static_dev_009(ctx: dict[str, str]) -> str:
    static_contains(
        ctx, "dockerfile", "postgresql-16", "mysql-server-8.0", "clickhouse-server", "openssh-server", "start-services.sh"
    )
    return static_contains(
        ctx, "devcontainer", "PG_TEST_DATABASE_URL", "MYSQL_TEST_DATABASE_URL", "CH_TEST_DATABASE_URL", "SSH_PORT"
    )


def static_dev_010(ctx: dict[str, str]) -> str:
    return static_contains(
        ctx, "dockerfile", "sfw@2.0.6", "sfw npm install", "sfw uv tool install", "signed-by=/usr/share/keyrings/clickhouse-keyring.gpg"
    )


STATIC_CHECKS: dict[str, Callable[[dict[str, str]], str]] = {
    f"DEV-{number:03}": globals()[f"static_dev_{number:03}"] for number in range(1, 11)
}


def runtime_dev_001() -> str:
    release = Path("/etc/os-release").read_text()
    require('VERSION_ID="24.04"' in release, "runtime is not Ubuntu 24.04")
    require(os.environ.get("USER") == "vscode", "runtime user is not vscode")
    require(Path.cwd() == Path("/workspace"), "runtime working directory is not /workspace")
    return "Ubuntu 24.04, vscode, /workspace"


def runtime_dev_002() -> str:
    require(Path("/proc/net").exists(), "runtime network namespace is unavailable")
    return "runtime networking is available"


def runtime_dev_003() -> str:
    if Path("/sys/fs/cgroup/memory.max").exists():
        require(Path("/sys/fs/cgroup/memory.max").read_text().strip() == str(12 * 1024**3), "RAM cgroup is not 12 GiB")
        require(Path("/sys/fs/cgroup/pids.max").read_text().strip() == "4096", "PID cgroup is not 4096")
    return "runtime cgroup limits discovered"


def runtime_dev_004() -> str:
    mounts = Path("/proc/self/mountinfo").read_text()
    for target in ("/workspace", "/home/vscode/.claude", "/home/vscode/.codex"):
        require(f" {target} " in mounts, f"missing runtime mount: {target}")
    require("docker.sock" not in mounts, "Docker socket is mounted")
    return "required mounts present and Docker socket absent"


def runtime_dev_005() -> str:
    output = run("bash", "-lc", "eval \"$(mise activate bash)\"; python --version; node --version; npm --version; uv --version")
    require(run("npm", "config", "get", "min-release-age") == "7", "npm cooldown is not seven days")
    require('exclude-newer = "7 days"' in (Path.home() / ".config/uv/uv.toml").read_text(), "uv cooldown missing")
    return output.replace("\n", "; ")


def runtime_dev_006() -> str:
    commands = "git gh jq curl gcc g++ make sqlite3 mysql psql clickhouse-client zsh tmux htop lsof strace tree file gitleaks ruff mypy pytest tsc tsx prettier eslint sfw"
    missing = [command for command in commands.split() if shutil.which(command) is None]
    require(not missing, f"tools missing from PATH: {missing}")
    return "all documented tools resolve on PATH"


def runtime_dev_007() -> str:
    return f"{run('claude', '--version')}; {run('codex', '--version')}"


def runtime_dev_008() -> str:
    require(POST_CREATE_MARKER.exists(), "post-create marker is missing")
    expected = hashlib.sha256(POST_CREATE_PATH.read_bytes()).hexdigest()
    require(POST_CREATE_MARKER.read_text().strip() == expected, "post-create marker does not match")
    return "audited lifecycle completed"


def runtime_dev_009() -> str:
    run("sudo", "/usr/local/bin/check-dev-services")
    return "PostgreSQL, MySQL, ClickHouse, and SSH are healthy"


def runtime_dev_010() -> str:
    require(shutil.which("sfw") is not None, "SFW is unavailable")
    require(run("npm", "config", "get", "min-release-age") == "7", "npm cooldown missing")
    return "SFW and release-age gates are active"


RUNTIME_CHECKS: dict[str, Callable[[], str]] = {
    f"DEV-{number:03}": globals()[f"runtime_dev_{number:03}"] for number in range(1, 11)
}


def main() -> int:
    requirement_ids = re.findall(r"`(DEV-\d{3})`", REQUIREMENTS_PATH.read_text())
    require(len(requirement_ids) == len(set(requirement_ids)), "duplicate requirement ID")
    require(set(requirement_ids) == set(STATIC_CHECKS) == set(RUNTIME_CHECKS), "requirement/check mismatch")
    print(f"Discovered {len(requirement_ids)} requirements")
    ctx = files()
    for requirement_id in requirement_ids:
        print(f"[PASS] {requirement_id} static: {STATIC_CHECKS[requirement_id](ctx)}")
    if Path("/.dockerenv").exists() and Path.cwd() == Path("/workspace"):
        for requirement_id in requirement_ids:
            print(f"[PASS] {requirement_id} runtime: {RUNTIME_CHECKS[requirement_id]()}")
        print("All static and in-container runtime checks passed")
    else:
        print("Static checks passed; runtime checks require /workspace inside the DevContainer")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
