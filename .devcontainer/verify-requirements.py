#!/usr/bin/env python3
"""Verify every documented DevContainer requirement statically and at runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEVCONTAINER_DIR = Path(__file__).resolve().parent
REQUIREMENTS_PATH = DEVCONTAINER_DIR / "REQUIREMENTS.md"
COMPOSE_PATH = DEVCONTAINER_DIR / "docker-compose.yml"
POST_CREATE_PATH = DEVCONTAINER_DIR / "post-create.sh"
POST_CREATE_MARKER = "/home/vscode/.local/state/yg-devcontainer/post-create.sha256"
GIB = 1024**3
LIFECYCLE_HOOKS = (
    "initializeCommand",
    "onCreateCommand",
    "updateContentCommand",
    "postCreateCommand",
    "postStartCommand",
    "postAttachCommand",
)


class VerificationError(RuntimeError):
    """Raised when a DevContainer requirement is not met."""


def run(*args: str, timeout: int = 120) -> str:
    """Run a command and return stripped standard output."""
    try:
        result = subprocess.run(
            args,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise VerificationError(
            f"command timed out after {timeout}s: {' '.join(args)}"
        ) from exc
    if result.returncode != 0:
        raise VerificationError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{result.stdout}"
        )
    return result.stdout.strip()


def require(condition: bool, message: str) -> None:
    """Raise a verification error unless condition is true."""
    if not condition:
        raise VerificationError(message)


def is_docker_socket_path(value: object) -> bool:
    """Return whether a mount endpoint exposes a Docker socket path."""
    path = str(value or "").rstrip("/")
    return path.startswith("/") and path.rsplit("/", 1)[-1] == "docker.sock"


def mounts_by_target(
    mounts: list[dict[str, Any]], target_key: str
) -> dict[str, dict[str, Any]]:
    """Index mounts by target and fail on duplicate targets."""
    indexed = {str(mount[target_key]): mount for mount in mounts}
    require(len(indexed) == len(mounts), "duplicate mount target found")
    return indexed


def shell_commands_outside_heredocs(script: str) -> tuple[str, ...]:
    """Return executable lines while ignoring comments and quoted heredoc data."""
    commands: list[str] = []
    terminator: str | None = None
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if terminator:
            if line == terminator:
                terminator = None
            continue
        if not line or line.startswith("#"):
            continue
        commands.append(line)
        match = re.fullmatch(r"cat <<'([A-Z][A-Z0-9_]*)'", line)
        if match:
            terminator = match.group(1)
    require(terminator is None, "unterminated lifecycle heredoc")
    return tuple(commands)


def load_static_context() -> dict[str, Any]:
    """Load generated configuration used by static checks."""
    devcontainer = json.loads((DEVCONTAINER_DIR / "devcontainer.json").read_text())
    compose = json.loads(
        run("docker", "compose", "-f", str(COMPOSE_PATH), "config", "--format", "json")
    )
    return {
        "devcontainer": devcontainer,
        "compose": compose,
        "service": compose["services"]["devcontainer"],
        "dockerfile": (DEVCONTAINER_DIR / "Dockerfile").read_text(),
        "post_create": POST_CREATE_PATH.read_text(),
    }


def static_dev_001(ctx: dict[str, Any]) -> str:
    require(
        "FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04" in ctx["dockerfile"],
        "Ubuntu 24.04 base image is missing",
    )
    require(
        ctx["devcontainer"].get("remoteUser") == "vscode", "remoteUser is not vscode"
    )
    require(
        ctx["devcontainer"].get("workspaceFolder") == "/workspace",
        "workspaceFolder is not /workspace",
    )
    return "Ubuntu 24.04, vscode user, and /workspace configured"


def static_dev_002(ctx: dict[str, Any]) -> str:
    require(ctx["service"].get("network_mode") == "host", "network mode is not host")
    return "host network configured"


def static_dev_003(ctx: dict[str, Any]) -> str:
    service = ctx["service"]
    require(int(service.get("mem_limit", 0)) == 12 * GIB, "RAM limit is not 12 GiB")
    require(
        int(service.get("memswap_limit", 0)) == 24 * GIB,
        "combined RAM and swap limit is not 24 GiB",
    )
    require(float(service.get("cpus", 0)) == 6.0, "CPU limit is not 6 cores")
    require(int(service.get("pids_limit", 0)) == 4096, "PID limit is not 4,096")
    require(int(service.get("shm_size", 0)) == 4 * GIB, "shared memory is not 4 GiB")
    return "12 GiB RAM + 12 GiB swap, 6 CPUs, 4,096 PIDs, and 4 GiB SHM configured"


def static_dev_004(ctx: dict[str, Any]) -> str:
    mounts = ctx["service"].get("volumes", [])
    by_target = mounts_by_target(mounts, "target")
    targets = set(by_target)
    expected = {"/workspace", "/home/vscode/.claude", "/home/vscode/.codex"}
    require(
        expected <= targets, f"expected mounts missing: {sorted(expected - targets)}"
    )
    require(
        by_target["/workspace"].get("type") == "bind", "workspace is not a bind mount"
    )
    agent_mounts = [by_target["/home/vscode/.claude"], by_target["/home/vscode/.codex"]]
    require(
        all(mount.get("type") == "volume" for mount in agent_mounts),
        "agent state is not stored in named volumes",
    )
    agent_sources = {str(mount.get("source", "")) for mount in agent_mounts}
    require("" not in agent_sources, "agent-state volume source is missing")
    require(len(agent_sources) == 2, "Claude and Codex must use separate volumes")
    require(
        not any(
            is_docker_socket_path(mount.get(key))
            for mount in mounts
            for key in ("source", "target")
        ),
        "Docker socket must not be mounted at any path",
    )
    return "workspace bind and separate agent-state volumes configured without Docker socket"


def static_dev_005(ctx: dict[str, Any]) -> str:
    dockerfile = ctx["dockerfile"]
    markers = (
        "mise use --global python@",
        "node@",
        "uv/0.",
        "npm config set min-release-age 7",
        'exclude-newer = "7 days"',
    )
    require(
        all(marker in dockerfile for marker in markers),
        "runtime or cooldown marker missing",
    )
    return "mise, Python, Node, uv, npm, and cooldown policies declared"


def static_dev_006(ctx: dict[str, Any]) -> str:
    dockerfile = ctx["dockerfile"]
    markers = (
        "build-essential",
        "git-lfs",
        "gh",
        "sqlite3 mysql-client postgresql-client",
        "zsh",
        "tmux",
        "htop procps lsof strace",
        "gitleaks",
        "typescript@",
        "prettier@",
        "eslint@",
        "ruff==",
        "mypy==",
        "pytest==",
    )
    require(
        all(marker in dockerfile for marker in markers),
        "required tooling marker missing",
    )
    return "required development-tool groups declared"


def static_dev_007(ctx: dict[str, Any]) -> str:
    dockerfile = ctx["dockerfile"]
    require(
        "https://claude.ai/install.sh" in dockerfile, "Claude Code installer missing"
    )
    require(
        "https://chatgpt.com/codex/install.sh" in dockerfile, "Codex installer missing"
    )
    return "Claude Code and Codex installers declared"


def static_dev_008(ctx: dict[str, Any]) -> str:
    require(
        ctx["service"].get("command") == ["sleep", "infinity"],
        "container command differs from the audited keep-alive command",
    )
    configured_hooks = {
        hook: ctx["devcontainer"][hook]
        for hook in LIFECYCLE_HOOKS
        if hook in ctx["devcontainer"]
    }
    require(
        configured_hooks == {"postCreateCommand": "bash .devcontainer/post-create.sh"},
        f"unexpected lifecycle hooks configured: {configured_hooks}",
    )
    expected_commands = (
        "set -euo pipefail",
        "git config --global --add safe.directory /workspace",
        'mkdir -p "$HOME/.local/state/yg-devcontainer"',
        "sha256sum .devcontainer/post-create.sh | cut -d ' ' -f 1 > "
        '"$HOME/.local/state/yg-devcontainer/post-create.sha256"',
        "cat <<'BANNER'",
    )
    require(
        shell_commands_outside_heredocs(ctx["post_create"]) == expected_commands,
        "post-create lifecycle differs from the audited command allowlist",
    )
    return "only the exact audited post-create lifecycle is configured"


STATIC_CHECKS: dict[str, Callable[[dict[str, Any]], str]] = {
    "DEV-001": static_dev_001,
    "DEV-002": static_dev_002,
    "DEV-003": static_dev_003,
    "DEV-004": static_dev_004,
    "DEV-005": static_dev_005,
    "DEV-006": static_dev_006,
    "DEV-007": static_dev_007,
    "DEV-008": static_dev_008,
}


def inspect_container(container: str) -> dict[str, Any]:
    return json.loads(run("docker", "inspect", container))[0]


def runtime_dev_001(container: str, info: dict[str, Any]) -> str:
    output = run(
        "docker",
        "exec",
        "--workdir",
        "/workspace",
        container,
        "bash",
        "-lc",
        '. /etc/os-release; printf \'%s|%s|%s\' "$VERSION_ID" "$(id -un)" "$PWD"',
    )
    require(output == "24.04|vscode|/workspace", f"unexpected environment: {output}")
    return output


def runtime_dev_002(container: str, info: dict[str, Any]) -> str:
    mode = info["HostConfig"]["NetworkMode"]
    require(mode == "host", f"runtime network mode is {mode!r}, not host")
    return "NetworkMode=host"


def runtime_dev_003(container: str, info: dict[str, Any]) -> str:
    host = info["HostConfig"]
    require(host["Memory"] == 12 * GIB, f"runtime RAM limit is {host['Memory']}")
    require(
        host["MemorySwap"] == 24 * GIB,
        f"runtime combined limit is {host['MemorySwap']}",
    )
    require(
        host["NanoCpus"] == 6_000_000_000,
        f"runtime CPU limit is {host['NanoCpus']}",
    )
    require(host["PidsLimit"] == 4096, f"runtime PID limit is {host['PidsLimit']}")
    require(host["ShmSize"] == 4 * GIB, f"runtime SHM is {host['ShmSize']}")

    cgroup_version = run(
        "docker",
        "exec",
        container,
        "bash",
        "-lc",
        "if test -f /sys/fs/cgroup/cgroup.controllers; then printf v2; else printf v1; fi",
    )
    if cgroup_version == "v2":
        cgroup_output = run(
            "docker",
            "exec",
            container,
            "bash",
            "-lc",
            "paste -sd ' ' /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.swap.max "
            "/sys/fs/cgroup/cpu.max /sys/fs/cgroup/pids.max",
        )
        cgroup_values = cgroup_output.split()
        require(len(cgroup_values) == 5, f"unexpected cgroup values: {cgroup_output}")
        require(cgroup_values[0] == str(12 * GIB), "cgroup RAM limit is not 12 GiB")
        require(cgroup_values[1] == str(12 * GIB), "cgroup swap limit is not 12 GiB")
        require(
            cgroup_values[2:4] == ["600000", "100000"],
            "cgroup CPU limit is not 6 cores",
        )
        require(cgroup_values[4] == "4096", "cgroup PID limit is not 4,096")
    else:
        require(cgroup_version == "v1", f"unknown cgroup version: {cgroup_version}")
        cgroup_output = run(
            "docker",
            "exec",
            container,
            "bash",
            "-lc",
            "set -euo pipefail; "
            'read_first() { for path in "$@"; do if test -f "$path"; then '
            'command cat "$path"; return 0; fi; done; return 1; }; '
            "printf '%s ' \"$(read_first /sys/fs/cgroup/memory/memory.limit_in_bytes "
            '/sys/fs/cgroup/memory.limit_in_bytes)"; '
            "printf '%s ' \"$(read_first /sys/fs/cgroup/memory/memory.memsw.limit_in_bytes "
            '/sys/fs/cgroup/memory.memsw.limit_in_bytes)"; '
            "printf '%s ' \"$(read_first /sys/fs/cgroup/cpu/cpu.cfs_quota_us "
            "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us "
            '/sys/fs/cgroup/cpu.cfs_quota_us)"; '
            "printf '%s ' \"$(read_first /sys/fs/cgroup/cpu/cpu.cfs_period_us "
            "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us "
            '/sys/fs/cgroup/cpu.cfs_period_us)"; '
            "read_first /sys/fs/cgroup/pids/pids.max /sys/fs/cgroup/pids.max",
        )
        cgroup_values = cgroup_output.split()
        require(len(cgroup_values) == 5, f"unexpected cgroup values: {cgroup_output}")
        require(cgroup_values[0] == str(12 * GIB), "cgroup RAM limit is not 12 GiB")
        require(
            cgroup_values[1] == str(24 * GIB),
            "cgroup combined RAM and swap limit is not 24 GiB",
        )
        require(
            cgroup_values[2:4] == ["600000", "100000"],
            "cgroup CPU limit is not 6 cores",
        )
        require(cgroup_values[4] == "4096", "cgroup PID limit is not 4,096")
    return (
        "RAM=12GiB Swap=12GiB Combined=24GiB CPUs=6 PIDs=4096 SHM=4GiB "
        f"Cgroup={cgroup_version}"
    )


def runtime_dev_004(container: str, info: dict[str, Any]) -> str:
    mounts = info.get("Mounts", [])
    by_target = mounts_by_target(mounts, "Destination")
    targets = set(by_target)
    expected = {"/workspace", "/home/vscode/.claude", "/home/vscode/.codex"}
    require(
        expected <= targets, f"runtime mounts missing: {sorted(expected - targets)}"
    )
    require(
        by_target["/workspace"].get("Type") == "bind",
        "runtime workspace is not a bind mount",
    )
    agent_mounts = [by_target["/home/vscode/.claude"], by_target["/home/vscode/.codex"]]
    require(
        all(mount.get("Type") == "volume" for mount in agent_mounts),
        "runtime agent state is not stored in named volumes",
    )
    agent_sources = {str(mount.get("Source", "")) for mount in agent_mounts}
    require("" not in agent_sources, "runtime agent-state volume source is missing")
    require(
        len(agent_sources) == 2, "runtime Claude and Codex volumes are not separate"
    )
    require(
        not any(
            is_docker_socket_path(mount.get(key))
            for mount in mounts
            for key in ("Source", "Destination")
        ),
        "Docker socket is mounted at runtime",
    )
    return "workspace bind and separate runtime agent-state volumes present; Docker socket absent"


def runtime_dev_005(container: str, info: dict[str, Any]) -> str:
    output = run(
        "docker",
        "exec",
        container,
        "bash",
        "-lc",
        'set -euo pipefail; eval "$(mise activate bash)"; python --version; node --version; npm --version; uv --version; mise --version; npm config get min-release-age; grep -F \'exclude-newer = "7 days"\' ~/.config/uv/uv.toml',
    )
    require(
        output.splitlines()[-2:] == ["7", 'exclude-newer = "7 days"'],
        "release cooldowns are not effective",
    )
    return "; ".join(output.splitlines()[:5]) + "; cooldowns=7 days"


def runtime_dev_006(container: str, info: dict[str, Any]) -> str:
    commands = (
        "git gh jq curl gcc g++ make sqlite3 mysql psql zsh tmux htop lsof strace "
        "tree file gitleaks ruff black mypy pytest tsc tsx prettier eslint"
    )
    run(
        "docker",
        "exec",
        container,
        "bash",
        "-lc",
        f'eval "$(mise activate bash)"; for command in {commands}; do command -v "$command" >/dev/null || exit 1; done',
    )
    return "all documented tool groups resolve on PATH"


def runtime_dev_007(container: str, info: dict[str, Any]) -> str:
    output = run(
        "docker",
        "exec",
        container,
        "bash",
        "-lc",
        "set -euo pipefail; claude --version; codex --version",
    )
    return "; ".join(output.splitlines())


def runtime_dev_008(container: str, info: dict[str, Any]) -> str:
    safe_directories = run(
        "docker",
        "exec",
        container,
        "bash",
        "-lc",
        "git config --global --get-all safe.directory",
    )
    require(
        "/workspace" in safe_directories.splitlines(),
        "audited post-create lifecycle did not configure /workspace",
    )
    marker = run("docker", "exec", container, "cat", POST_CREATE_MARKER)
    expected_marker = hashlib.sha256(POST_CREATE_PATH.read_bytes()).hexdigest()
    require(
        marker == expected_marker,
        "running container did not complete the audited lifecycle script",
    )
    return "the exact audited post-create lifecycle completed without an automatic install command"


RUNTIME_CHECKS: dict[str, Callable[[str, dict[str, Any]], str]] = {
    "DEV-001": runtime_dev_001,
    "DEV-002": runtime_dev_002,
    "DEV-003": runtime_dev_003,
    "DEV-004": runtime_dev_004,
    "DEV-005": runtime_dev_005,
    "DEV-006": runtime_dev_006,
    "DEV-007": runtime_dev_007,
    "DEV-008": runtime_dev_008,
}


def discover_requirement_ids() -> list[str]:
    """Search the requirements document for every requirement ID."""
    return re.findall(r"`(DEV-\d{3})`", REQUIREMENTS_PATH.read_text())


def verify_check_coverage(requirement_ids: list[str]) -> None:
    require(
        len(requirement_ids) == len(set(requirement_ids)),
        "duplicate requirement ID found",
    )
    documented = set(requirement_ids)
    require(
        documented == set(STATIC_CHECKS), "static checks do not match documented IDs"
    )
    require(
        documented == set(RUNTIME_CHECKS), "runtime checks do not match documented IDs"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", help="running container ID or name")
    args = parser.parse_args()

    requirement_ids = discover_requirement_ids()
    verify_check_coverage(requirement_ids)
    print(f"Discovered {len(requirement_ids)} requirements in {REQUIREMENTS_PATH.name}")

    ctx = load_static_context()
    for requirement_id in requirement_ids:
        evidence = STATIC_CHECKS[requirement_id](ctx)
        print(f"[PASS] {requirement_id} static: {evidence}")

    if args.container:
        info = inspect_container(args.container)
        for requirement_id in requirement_ids:
            evidence = RUNTIME_CHECKS[requirement_id](args.container, info)
            print(f"[PASS] {requirement_id} runtime: {evidence}")
    else:
        print(
            "Runtime checks skipped: pass --container for a running generated DevContainer"
        )
        print(
            "All discovered static requirement checks passed; runtime checks were not run"
        )
        return 0

    print("All discovered static and runtime requirement checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
