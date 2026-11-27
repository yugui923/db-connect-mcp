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

    def test_pip_tab_before_inline_comment_is_accepted(self):
        # A tab before an inline comment is valid pip; the comment must not be
        # mistaken for an unsupported option.
        result = self.run_scan("pip-tab", "scripts/math/requirements.lock.txt")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pip_spaces_around_operator_is_accepted(self):
        # pip accepts `name == 1.0`; rejecting it would be a false failure.
        result = self.run_scan("pip-spaces", "scripts/math/requirements.lock.txt")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pip_unsupported_option_after_marker_fails(self):
        # A marker must not become a place to hide options from validation.
        result = self.run_scan("pip-option", "scripts/math/requirements.lock.txt")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("unsupported requirements option", result.stderr)

    def test_only_dependency_free_lockfile_is_not_a_scanner_failure(self):
        # osv-scanner 2.2.4 exits 128 when every lockfile declares no
        # dependencies. That is an empty result for the tree, not a failure.
        result = self.run_scan("empty-npm-none", "empty/package-lock.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("scanner failed", result.stderr)

    def test_only_dependency_free_lockfile_does_not_fail(self):
        # osv-scanner exits 128 on an empty input set; a tree with nothing to
        # scan must be a complete empty result, not a scanner failure.
        result = self.run_scan("empty-npm", "empty/package-lock.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("scanner failed", result.stderr)

    def test_pip_sha256_continuation_is_accepted(self):
        result = self.run_scan("pip-complete", "scripts/math/requirements.lock.txt")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dependency_free_npm_lockfile_is_complete(self):
        # A lockfile declaring no dependencies yields no scanner source record;
        # that is complete coverage, not a missing input.
        result = self.run_scan("empty-npm", "empty/package-lock.json")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pip_omitted_package_fails(self):
        result = self.run_scan("pip-missing", "scripts/math/requirements.lock.txt")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("pip package inventory mismatch", result.stderr)

    def test_pip_complete_inventory_passes(self):
        result = self.run_scan("pip-complete", "scripts/math/requirements.lock.txt")
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
                if "empty/" in lock:
                    file.write_text(
                        json.dumps(
                            {
                                "lockfileVersion": 3,
                                "packages": {"": {"name": "root", "version": "1.0.0"}},
                            }
                        ),
                        encoding="utf-8",
                    )
                elif lock.endswith("requirements.lock.txt") and mode == "pip-tab":
                    # Tab before an inline comment, as some generators emit.
                    file.write_text(
                        "alpha==1.0.0" + chr(9) + "# note" + chr(10), encoding="utf-8"
                    )
                elif lock.endswith("requirements.lock.txt") and mode == "pip-spaces":
                    # pip tolerates whitespace around the operator.
                    file.write_text("alpha == 1.0.0" + chr(10), encoding="utf-8")
                elif lock.endswith("requirements.lock.txt") and mode == "pip-option":
                    # An option hidden after the marker must still be rejected.
                    file.write_text(
                        "alpha==1.0.0 ; python_version >= '3.11' "
                        "--config-settings=x" + chr(10),
                        encoding="utf-8",
                    )
                elif lock.endswith("requirements.lock.txt"):
                    # uv-pip-compile style: exact pins with --hash continuations.
                    lines = [
                        "alpha==1.0.0 " + chr(92),
                        "    --hash=sha256:" + "0" * 64,
                        "beta==2.0.0 ; python_version >= '3.11' " + chr(92),
                        "    --hash=sha256:" + "1" * 64,
                    ]
                    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
                elif file.name == "package-lock.json":
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
  pip-tab)
    python3 - "$@" <<'PY'
import json, sys
paths = [a.split(":", 1)[1] for a in sys.argv[1:] if a.startswith("requirements.txt:")]
inventory = [{"package": {"ecosystem": "PyPI", "name": "alpha", "version": "1.0.0"}}]
print(
    json.dumps(
        {"results": [{"source": {"path": p}, "packages": inventory} for p in paths]}
    )
)
PY
    exit 0 ;;
  pip-spaces)
    python3 - "$@" <<'PY'
import json, sys
paths = [a.split(":", 1)[1] for a in sys.argv[1:] if a.startswith("requirements.txt:")]
inventory = [{"package": {"ecosystem": "PyPI", "name": "alpha", "version": "1.0.0"}}]
print(
    json.dumps(
        {"results": [{"source": {"path": p}, "packages": inventory} for p in paths]}
    )
)
PY
    exit 0 ;;
  pip-option)
    python3 - "$@" <<'PY'
import json, sys
paths = [a.split(":", 1)[1] for a in sys.argv[1:] if a.startswith("requirements.txt:")]
inventory = [{"package": {"ecosystem": "PyPI", "name": "alpha", "version": "1.0.0"}}]
print(
    json.dumps(
        {"results": [{"source": {"path": p}, "packages": inventory} for p in paths]}
    )
)
PY
    exit 0 ;;
  empty-npm-none)
    # Mirrors osv-scanner 2.2.4: an input set of only dependency-free locks
    # produces no results file content at all and exits 128.
    echo 'No package sources found, --help for usage information.' >&2
    echo '{"results":[]}'
    exit 128 ;;
  empty-npm) echo '{"results":[]}'; exit 0 ;;
  pip-missing|pip-complete)
    python3 - "$@" <<'PY'
import json, os, sys
paths = [a.split(":", 1)[1] for a in sys.argv[1:] if a.startswith("requirements.txt:")]
inventory = [{"package": {"ecosystem": "PyPI", "name": "alpha", "version": "1.0.0"}}]
if os.environ["FIXTURE_MODE"] == "pip-complete":
    inventory.append(
        {"package": {"ecosystem": "PyPI", "name": "beta", "version": "2.0.0"}}
    )
print(
    json.dumps(
        {"results": [{"source": {"path": p}, "packages": inventory} for p in paths]}
    )
)
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
