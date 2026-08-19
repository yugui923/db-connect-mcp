#!/usr/bin/env python3
"""Verify that all release metadata uses one version."""

from __future__ import annotations

import argparse
import ast
import json
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        return tomllib.load(file)


def _package_version() -> str:
    module = ast.parse((ROOT / "src/db_connect_mcp/__init__.py").read_text())
    for statement in module.body:
        if (
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__version__"
                for target in statement.targets
            )
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            return statement.value.value
    raise ValueError("src/db_connect_mcp/__init__.py does not define __version__")


def collect_versions() -> dict[str, str]:
    """Collect every release version that must remain synchronized."""
    project = _load_toml(ROOT / "pyproject.toml")
    lock = _load_toml(ROOT / "uv.lock")
    server = json.loads((ROOT / "server.json").read_text())
    manifest = json.loads((ROOT / "manifest.json").read_text())

    locked_project = next(
        package
        for package in lock["package"]
        if package["name"] == project["project"]["name"]
    )
    package_entry = next(
        package
        for package in server["packages"]
        if package["identifier"] == project["project"]["name"]
    )

    return {
        "pyproject.toml": project["project"]["version"],
        "uv.lock": locked_project["version"],
        "src/db_connect_mcp/__init__.py": _package_version(),
        "server.json": server["version"],
        "server.json package": package_entry["version"],
        "manifest.json": manifest["version"],
    }


def verify_release_metadata(tag: str | None = None) -> str:
    """Return the canonical version or raise when metadata differs."""
    versions = collect_versions()
    unique_versions = set(versions.values())
    if len(unique_versions) != 1:
        details = ", ".join(
            f"{source}={version}" for source, version in versions.items()
        )
        raise ValueError(f"release versions are inconsistent: {details}")

    version = unique_versions.pop()
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"tag {tag!r} does not match metadata version v{version}")
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag", help="Optional release tag to validate, such as v1.2.3"
    )
    args = parser.parse_args()
    version = verify_release_metadata(args.tag)
    print(f"Release metadata is synchronized at v{version}")


if __name__ == "__main__":
    main()
