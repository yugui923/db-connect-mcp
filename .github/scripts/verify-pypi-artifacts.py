#!/usr/bin/env python3
"""Verify that a package index serves the exact locally built artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_ATTEMPTS = 24
DEFAULT_RETRY_DELAY_SECONDS = 5.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fetch_release(
    repository_url: str,
    package_name: str,
    version: str,
) -> dict[str, Any] | None:
    url = f"{repository_url.rstrip('/')}/pypi/{package_name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def verify_artifacts(
    repository_url: str,
    package_name: str,
    version: str,
    dist_dir: Path,
    attempts: int = DEFAULT_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> None:
    """Wait for a release and verify its filenames and SHA-256 digests."""
    expected = {
        artifact.name: _sha256(artifact)
        for artifact in sorted(dist_dir.iterdir())
        if artifact.is_file()
    }
    if not expected:
        raise ValueError(f"no distribution artifacts found in {dist_dir}")

    for attempt in range(1, attempts + 1):
        release = _fetch_release(repository_url, package_name, version)
        if release is not None:
            published = {
                item["filename"]: item["digests"]["sha256"] for item in release["urls"]
            }
            if published == expected:
                print(
                    f"Verified {len(expected)} {package_name} {version} artifact(s) "
                    f"on {repository_url}"
                )
                return
            if set(published) == set(expected):
                raise RuntimeError(
                    f"artifact digest mismatch: expected {expected}, got {published}"
                )

        if attempt < attempts:
            time.sleep(retry_delay_seconds)

    raise RuntimeError(
        f"{package_name} {version} artifacts did not appear on {repository_url} "
        f"after {attempts} attempts"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-url", required=True)
    parser.add_argument("--package-name", default="db-connect-mcp")
    parser.add_argument("--version", required=True)
    parser.add_argument("--dist-dir", type=Path, required=True)
    args = parser.parse_args()

    verify_artifacts(
        repository_url=args.repository_url,
        package_name=args.package_name,
        version=args.version,
        dist_dir=args.dist_dir,
    )


if __name__ == "__main__":
    main()
