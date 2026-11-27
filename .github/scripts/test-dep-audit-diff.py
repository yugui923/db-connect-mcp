"""Offline behavioral fixtures for the dependency comparison and scanner driver."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


class DependencyDeltaTests(unittest.TestCase):
    def test_severity_from_osv_cvss_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scan = root / "scan.json"
            scan.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "packages": [
                                    {
                                        "package": {
                                            "ecosystem": "PyPI",
                                            "name": "fixture",
                                            "version": "1",
                                        },
                                        "vulnerabilities": [
                                            {
                                                "id": "GHSA-fixture",
                                                "database_specific": {
                                                    "severity": "MEDIUM"
                                                },
                                            }
                                        ],
                                        "groups": [
                                            {
                                                "ids": ["GHSA-fixture"],
                                                "max_severity": "9.8",
                                            }
                                        ],
                                    }
                                ]
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            rows = subprocess.check_output(
                [sys.executable, SCRIPTS / "normalise.py", scan],
                text=True,
            )
            self.assertEqual(rows.strip().split("\t")[-1], "CRITICAL")
            candidate = root / "candidate.tsv"
            candidate.write_text(rows, encoding="utf-8")
            baseline = root / "baseline.tsv"
            baseline.touch()
            args = [
                sys.executable,
                SCRIPTS / "diff-logic.py",
                baseline,
                candidate,
                os.devnull,
                "CRITICAL,HIGH",
            ]
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 1)
            baseline.write_text(rows, encoding="utf-8")
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 0)

    def test_partial_scanner_lookup_is_not_a_pass(self):
        self.assertEqual(self.run_scan("partial").returncode, 2)

    def test_invalid_json_schema_is_not_a_pass(self):
        self.assertEqual(self.run_scan("schema").returncode, 2)

    def test_missing_source_is_not_a_pass(self):
        self.assertEqual(
            self.run_scan(
                "missing", "package-lock.json", "other/package-lock.json"
            ).returncode,
            2,
        )

    def test_incomplete_package_inventory_is_not_a_pass(self):
        result = self.run_scan("missing-package")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("npm package inventory mismatch", result.stderr)

    def test_uv_omitted_registry_package_fails(self):
        result = self.run_scan("uv-missing", "uv.lock")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("uv package inventory mismatch", result.stderr)

    def test_uv_normalized_registry_with_local_package_passes(self):
        result = self.run_scan("uv-complete", "uv.lock")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_math_requirements_lock_is_scanned(self):
        result = self.run_scan("math", "scripts/math/requirements.lock.txt")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("fixture observed math lockfile", result.stderr)

    def test_clean_complete_scan_passes(self):
        self.assertEqual(
            self.run_scan(
                "clean", "package-lock.json", "other/package-lock.json"
            ).returncode,
            0,
        )

    def run_scan(self, mode, *locks):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()

            def git(*args):
                command = [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    *args,
                ]
                return subprocess.check_output(command, cwd=repo, text=True).strip()

            git("init", "-q")
            for lock in locks or ("package-lock.json",):
                file = repo / lock
                file.parent.mkdir(parents=True, exist_ok=True)
                if file.name == "package-lock.json":
                    data = {
                        "lockfileVersion": 3,
                        "packages": {
                            "": {"name": "root", "version": "1.0.0"},
                            "node_modules/fixture": {"version": "1.0.0"},
                            "node_modules/alias": {
                                "name": "@test/actual",
                                "version": "2.0.0",
                            },
                            "node_modules/workspace": {
                                "link": True,
                                "resolved": "packages/workspace",
                            },
                            "packages/workspace": {
                                "name": "workspace",
                                "version": "1.0.0",
                            },
                        },
                    }
                    file.write_text(json.dumps(data), encoding="utf-8")
                elif file.name == "uv.lock":
                    file.write_text(
                        "version = 1\n"
                        '[[package]]\nname = "some-package"\nversion = "1.0"\n'
                        'source = { registry = "https://example.invalid/simple" }\n'
                        '[[package]]\nname = "another"\nversion = "2.0"\n'
                        'source = { registry = "https://example.invalid/simple" }\n'
                        '[[package]]\nname = "local-project"\nversion = "1.0"\n'
                        'source = { editable = "." }\n',
                        encoding="utf-8",
                    )
                else:
                    file.write_text("fixture\n", encoding="utf-8")
                git("add", lock)
            git("commit", "-qm", "fixture")
            sha = git("rev-parse", "HEAD")
            scanner = root / "scanner"
            scanner.write_text(
                """#!/usr/bin/env bash
case "$FIXTURE_MODE" in
  partial) echo 'error when retrieving vulns: fixture lookup incomplete' >&2
           echo '{"results":[]}'; exit 1 ;;
  schema)  echo '{}'; exit 0 ;;
  missing|missing-package|clean)
    python3 - "$@" <<'PY'
import json, os, sys
paths = [arg.split(":", 1)[1] for arg in sys.argv[1:] if arg.startswith("package-lock.json:")]
if os.environ["FIXTURE_MODE"] == "missing":
    paths = paths[:1]
coordinates = [("fixture", "1.0.0"), ("@test/actual", "2.0.0"), ("workspace", "1.0.0")]
if os.environ["FIXTURE_MODE"] == "missing-package":
    coordinates = coordinates[:1]
inventory = [{"package": {"ecosystem": "npm", "name": n, "version": v}}
             for n, v in coordinates]
print(json.dumps({"results": [{"source": {"path": p}, "packages": inventory} for p in paths]}))
PY
    exit 0 ;;
  uv-missing|uv-complete)
    python3 - "$@" <<'PY'
import json, os, sys
paths = [arg.split(":", 1)[1] for arg in sys.argv[1:] if arg.startswith("uv.lock:")]
coordinates = [("Some_Package", "1.0"), ("local-project", "1.0")]
if os.environ["FIXTURE_MODE"] == "uv-complete":
    coordinates.append(("another", "2.0"))
inventory = [{"package": {"ecosystem": "PyPI", "name": n, "version": v}}
             for n, v in coordinates]
print(json.dumps({"results": [{"source": {"path": p}, "packages": inventory} for p in paths]}))
PY
    exit 0 ;;
  math)    for arg in "$@"; do
             if [[ "$arg" == requirements.txt:*/scripts/math/requirements.lock.txt ]]; then
               echo 'fixture observed math lockfile' >&2
               echo '{"results":[]}'; exit 7
             fi
           done
           echo '{"results":[]}' ;;
esac
""",
                encoding="utf-8",
            )
            scanner.chmod(0o700)
            env = dict(
                os.environ,
                FIXTURE_MODE=mode,
                DEP_AUDIT_BASE_SHA=sha,
                DEP_AUDIT_HEAD_SHA=sha,
                DEP_AUDIT_BIN=str(scanner),
            )
            env.pop("DEP_AUDIT_SUMMARY", None)
            return subprocess.run(
                ["bash", SCRIPTS / "dep-audit-diff.sh"],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
            )


if __name__ == "__main__":
    unittest.main()
