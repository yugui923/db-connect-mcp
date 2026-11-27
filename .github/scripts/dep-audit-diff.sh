#!/usr/bin/env bash
# dep-audit-diff — incremental dependency-vulnerability gate.
#
# Blocks a pull request only on vulnerabilities the PR *introduces*.
# A HIGH/CRITICAL advisory that exists in the merge-base and still exists on the
# head is reported, never blocking: the PR did not create it, and demanding that
# one PR clear a whole backlog is how a security gate teaches people to disable
# it.
#
# Identity is (ecosystem, package, advisory) — never a finding total, never a
# severity sum. Removing one advisory while adding another is a new finding and
# fails, even when the numbers look better.
#
# Environment:
#   DEP_AUDIT_BASE_SHA    commit to scan as the baseline (required)
#   DEP_AUDIT_HEAD_SHA    commit to scan as the candidate (default: HEAD)
#   DEP_AUDIT_BLOCK       severities that block when introduced
#                         (default: CRITICAL,HIGH)
#   DEP_AUDIT_VERSION     osv-scanner release (default: 2.2.4)
#   DEP_AUDIT_SHA256      expected sha256 of the linux_amd64 binary
#   DEP_AUDIT_BIN         use an already-present scanner instead of downloading
#                         (caller is responsible for having verified it)
#   DEP_AUDIT_SUMMARY     path for a markdown summary (default: none)
#   DEP_AUDIT_ALLOW_FILE  optional file of allowed (pkg,advisory) introduced
#                         findings, one per line, "#" comments; for reviewed
#                         false positives. Keeps exceptions auditable in-repo.
#
# Exit: 0 = no introduced blocking findings; 1 = introduced blocking findings;
#       2 = scanner/usage error (fail closed).
set -uo pipefail

BASE_SHA="${DEP_AUDIT_BASE_SHA:?DEP_AUDIT_BASE_SHA is required}"
HEAD_SHA="${DEP_AUDIT_HEAD_SHA:-$(git rev-parse HEAD)}"
BLOCK="${DEP_AUDIT_BLOCK:-CRITICAL,HIGH}"
OSV_VERSION="${DEP_AUDIT_VERSION:-2.2.4}"
OSV_SHA256="${DEP_AUDIT_SHA256:-7702cd1e5d9f5059dd9570f4ad967f27d3c5f5391b371ec937b384c238177f55}"
SUMMARY="${DEP_AUDIT_SUMMARY:-}"
ALLOW_FILE="${DEP_AUDIT_ALLOW_FILE:-}"

# Lockfiles we understand. An explicit allowlist rather than a whole-tree scan:
# bounded, fast, and its scope is reviewable in the PR that adds it.
# go.mod is included because osv-scanner needs it alongside go.sum to resolve
# the module graph; without it the scanner reports "No package sources found".
LOCK_PATTERN='(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|npm-shrinkwrap\.json|uv\.lock|poetry\.lock|Pipfile\.lock|go\.mod|go\.sum|requirements\.lock\.txt)$'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)" || exit 2
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/base" "$WORK/head" "$WORK/scan/base" "$WORK/scan/head" "$WORK/bin" || exit 2

log() { printf '%s\n' "$*" >&2; }
die() { log "::error::$*"; exit 2; }

# --- scanner -----------------------------------------------------------------
# A pinned release binary rather than a container: several of these repositories
# run on self-hosted ARC scale sets with no Docker socket, where `docker run`
# exits 127 and would fail the gate on every PR. The checksum is pinned in this
# file and verified before use, so a re-tagged or tampered download cannot pass.
resolve_scanner() {
  if [ -n "${DEP_AUDIT_BIN:-}" ]; then
    [ -x "$DEP_AUDIT_BIN" ] || die "DEP_AUDIT_BIN=$DEP_AUDIT_BIN is not executable"
    printf '%s' "$DEP_AUDIT_BIN"
    return 0
  fi
  if [[ ! "$OSV_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ || ! "$OSV_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    die "missing or invalid scanner version or checksum pin"
  fi
  local dest="$WORK/bin/osv-scanner"
  local url="https://github.com/google/osv-scanner/releases/download/v${OSV_VERSION}/osv-scanner_linux_amd64"
  curl -fsSL --retry 3 --max-time 120 -o "$dest" "$url" \
    || die "could not download osv-scanner v${OSV_VERSION}"
  local got
  got="$(sha256sum "$dest" | awk '{print $1}')"
  [ "$got" = "$OSV_SHA256" ] \
    || die "osv-scanner checksum mismatch: expected $OSV_SHA256, got $got"
  chmod 0755 "$dest"
  printf '%s' "$dest"
}

# --- collect the exact lockfile set at a commit ------------------------------
# Uses the commit's own tree, not the working tree, so the result depends only on
# the SHA being asked about.
extract_at() {
  local sha="$1" dest="$2" path
  local -a arr=()
  git ls-tree -rz --name-only "$sha" > "$WORK/paths" || die "git ls-tree failed for ${sha:0:12}"
  while IFS= read -r -d '' path; do
    if [[ "$path" =~ $LOCK_PATTERN && ! "/$path/" =~ /node_modules/ ]]; then
      arr+=("$path")
    fi
  done < "$WORK/paths"
  if [ "${#arr[@]}" = 0 ]; then
    log "::warning::no recognised lockfiles at ${sha:0:12}; nothing to scan"
    return 0
  fi
  git archive --format=tar -o "$WORK/tree.tar" "$sha" -- "${arr[@]}" 2>"$WORK/archive.err" || {
    cat "$WORK/archive.err" >&2
    die "git archive failed for ${sha:0:12}"
  }
  tar -xf "$WORK/tree.tar" -C "$dest" || die "tar extract failed for ${sha:0:12}"
  for path in "${arr[@]}"; do
    [[ -f "$dest/$path" && ! -L "$dest/$path" ]] \
      || die "lockfile missing or not a regular file: $path"
  done
}

# --- scan --------------------------------------------------------------------
# A scanner failure must never read as "no vulnerabilities": exit 2 closes the
# gate instead of opening it.
npm_lock_is_empty() {
  # Exit 0 only when the lockfile provably installs nothing (root only).
  python3 - "$1" <<'PY'
import json
import sys

try:
    lock = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(2)  # Unprovable: keep requiring scanner coverage.
packages = lock.get("packages") if isinstance(lock, dict) else None
if lock.get("lockfileVersion") not in (2, 3) or not isinstance(packages, dict):
    raise SystemExit(2)
raise SystemExit(0 if not any(packages) else 1)
PY
}

scan_dir() {
  local src="$1" out="$2" scanner="$3" path rc
  local -a extra=() expected=()
  find "$src" -type f -print0 > "$WORK/extracted" || die "cannot enumerate extracted inputs"
  if [ ! -s "$WORK/extracted" ]; then
    printf '{"results":[]}' > "$out"
    return 0
  fi
  while IFS= read -r -d '' path; do
    case "${path##*/}" in
      requirements.lock.txt) extra+=(--lockfile "requirements.txt:$path") ;;
      npm-shrinkwrap.json)
        # Required coverage, but an empty lock has no packages to report and
        # handing it to the scanner makes it exit 128.
        npm_lock_is_empty "$path" || extra+=(--lockfile "package-lock.json:$path") ;;
      package-lock.json)
        npm_lock_is_empty "$path" || extra+=(--lockfile "package-lock.json:$path") ;;
      go.sum)
        [[ -f "${path%/*}/go.mod" ]] || die "go.sum has no companion go.mod: $path"
        continue ;;
      *) extra+=(--lockfile "${path##*/}:$path") ;;
    esac
    expected+=("$path")
  done < "$WORK/extracted"
  if [ "${#extra[@]}" -eq 0 ]; then
    # Nothing is left to hand the scanner. osv-scanner exits 128 on an empty
    # input set; that is a complete, empty result for this tree, not a
    # scanner failure.
    printf '{"results":[]}' > "$out"
    return 0
  fi
  "$scanner" scan source --all-packages --all-vulns --no-resolve --verbosity error \
    --format json "${extra[@]}" >"$out" 2>"$WORK/scan.err"
  rc=$?
  # osv-scanner exits 1 when it finds vulnerabilities; that is a result, not an
  # error. Anything else is a real failure.
  # Some partial lookup failures log errors even when findings cause exit 1.
  if [ -s "$WORK/scan.err" ] || { [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; }; then
    tail -20 "$WORK/scan.err" >&2
    die "scanner failed (exit $rc) scanning $src"
  fi
  [ -s "$out" ] || die "scanner produced no output for $src"
  python3 - "$out" "${expected[@]}" <<'PY' || die "incomplete scanner coverage for $src"
import json
import re
import sys
import tomllib
from pathlib import Path, PurePosixPath


def npm_coordinates(path: Path) -> set[tuple[str, str]]:
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock["lockfileVersion"] not in (2, 3) or not isinstance(lock["packages"], dict):
        raise ValueError(f"unsupported npm lockfile inventory: {path}")
    packages = lock["packages"]
    expected = set()
    for location, package in packages.items():
        if not location:
            continue  # The root project is not an installed dependency.
        if package.get("link") is True:
            target = PurePosixPath(package["resolved"])
            if (
                target.is_absolute() or ".." in target.parts or not target.parts
                or target.as_posix() not in packages
                or packages[target.as_posix()].get("link") is True
            ):
                raise ValueError(f"unresolved npm workspace link: {location}")
            continue  # The versioned target, not its link, is checked below.
        name = package.get("name") or ("/" + location).rsplit("/node_modules/", 1)[-1]
        version = package["version"]
        if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
            raise ValueError(f"invalid npm package coordinate: {location}")
        expected.add((name, version))
    return expected


def python_coordinate(name: str, version: str) -> tuple[str, str]:
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", name):
        raise ValueError("invalid PyPI name in inventory")
    if not isinstance(version, str) or not version or any(c.isspace() for c in version):
        raise ValueError("invalid PyPI version in inventory")
    return re.sub(r"[-_.]+", "-", name).lower(), version


def check_uv_inventory(path: Path, items: list) -> None:
    with path.open("rb") as fh:
        lock = tomllib.load(fh)
    if lock["version"] != 1 or not isinstance(lock["package"], list):
        raise ValueError(f"unsupported uv lockfile inventory: {path}")
    registry, local = set(), set()
    for package in lock["package"]:
        source = package["source"]
        if not isinstance(source, dict) or len(source) != 1:
            raise ValueError(f"ambiguous uv package source in {path}")
        kind, location = next(iter(source.items()))
        if not isinstance(location, str) or not location:
            raise ValueError(f"invalid uv package source in {path}")
        coordinate = python_coordinate(package["name"], package["version"])
        if kind == "registry":
            registry.add(coordinate)
        elif kind in {"editable", "directory", "virtual"}:
            local.add(coordinate)
        else:
            raise ValueError(f"unsupported uv package source kind: {kind}")
    reported = set()
    for item in items:
        identity = item["package"]
        if identity["ecosystem"] != "PyPI":
            raise ValueError(f"non-PyPI inventory entry for {path}")
        reported.add(python_coordinate(identity["name"], identity["version"]))
    missing, unexpected = registry - reported, reported - (registry | local)
    if missing or unexpected:
        raise ValueError(
            f"uv package inventory mismatch for {path}: "
            f"{len(missing)} missing, {len(unexpected)} unexpected"
        )



def requirements_coordinates(path: Path) -> set[tuple[str, str]]:
    """Read a pinned pip requirements lockfile without resolving anything.

    Each logical line (continuations joined) must be an exact ``name==version``
    pin, optionally with extras and an environment marker. Whitespace around
    ``==`` is accepted because pip accepts it. Only sha256 ``--hash=`` options
    are allowed, on either side of a marker; anything else fails closed.
    """
    text = path.read_text(encoding="utf-8").replace(chr(92) + chr(10), " ")
    expected = set()
    pin = re.compile(
        r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[A-Za-z0-9._,-]+\])?"
        r"\s*==\s*([^\s,;]+)$"
    )
    digest = re.compile(r"--hash=sha256:[0-9a-f]{64}")
    for line in text.splitlines():
        line = re.split(r"\s+#", line, 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            raise ValueError(f"unsupported requirements directive in {path}: {line[:40]}")
        requirement, _, marker = line.partition(";")
        # Validate every option token, whether it precedes the marker or trails it.
        for token in requirement.split() + marker.split():
            if token.startswith("-") and not digest.fullmatch(token):
                raise ValueError(
                    f"unsupported requirements option in {path}: {token[:40]}"
                )
        requirement = " ".join(
            token for token in requirement.split() if not token.startswith("-")
        )
        if not requirement:
            continue
        match = pin.fullmatch(requirement)
        if not match:
            raise ValueError(f"unsupported requirements pin in {path}: {requirement[:40]}")
        expected.add(python_coordinate(match.group(1), match.group(2)))
    if not expected:
        raise ValueError(f"empty requirements inventory: {path}")
    return expected


def npm_declares_no_dependencies(path: Path) -> bool:
    """True only when an npm lockfile provably installs nothing (root only)."""
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False  # Unprovable: keep requiring scanner coverage.
    if not isinstance(lock, dict):
        return False
    packages = lock.get("packages")
    if lock.get("lockfileVersion") not in (2, 3) or not isinstance(packages, dict):
        return False
    return not any(location for location in packages)

try:
    result = json.loads(Path(sys.argv[1]).read_text())
    if not isinstance(result["results"], list):
        raise ValueError("invalid results list")
    scanned = set()
    for entry in result["results"]:
        if not isinstance(entry["packages"], list) or not entry["packages"]:
            raise ValueError("source without an inventory")
        source = Path(entry["source"]["path"]).resolve()
        if source in scanned:
            raise ValueError(f"duplicate scanner source: {source}")
        scanned.add(source)
        if source.name in ("package-lock.json", "npm-shrinkwrap.json"):
            expected = npm_coordinates(source)
            actual = set()
            for item in entry["packages"]:
                identity = item["package"]
                if identity["ecosystem"] != "npm":
                    raise ValueError(f"non-npm inventory entry for {source}")
                actual.add((identity["name"], identity["version"]))
            if actual != expected:
                raise ValueError(
                    f"npm package inventory mismatch for {source}: "
                    f"{len(expected - actual)} missing, {len(actual - expected)} unexpected"
                )
        elif source.name == "requirements.lock.txt":
            expected = requirements_coordinates(source)
            actual = set()
            for item in entry["packages"]:
                identity = item["package"]
                if identity["ecosystem"] != "PyPI":
                    raise ValueError(f"non-PyPI inventory entry for {source}")
                actual.add(python_coordinate(identity["name"], identity["version"]))
            if actual != expected:
                raise ValueError(
                    f"pip package inventory mismatch for {source}: "
                    f"{len(expected - actual)} missing, {len(actual - expected)} unexpected"
                )
        elif source.name == "uv.lock":
            check_uv_inventory(source, entry["packages"])
    required = {Path(p).resolve() for p in sys.argv[2:]}
    # A lockfile that declares no dependencies produces no scanner source
    # record. That is complete coverage for an empty expected inventory.
    required = {
        p
        for p in required
        if not (
            p.name in ("package-lock.json", "npm-shrinkwrap.json")
            and npm_declares_no_dependencies(p)
        )
    }
    missing = required - scanned
    if missing:
        raise ValueError("missing inputs: " + ", ".join(map(str, sorted(missing))))
    if scanned - required:
        raise ValueError("unexpected scanner input")
except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
    sys.exit(f"invalid scanner coverage: {exc}")
PY
}

# --- run ---------------------------------------------------------------------
SCANNER="$(resolve_scanner)" || exit 2
log "dep-audit-diff: baseline ${BASE_SHA:0:12} → head ${HEAD_SHA:0:12}"

merge_base="$(git merge-base "$BASE_SHA" "$HEAD_SHA" 2>/dev/null)" || {
  die "no merge-base between $BASE_SHA and $HEAD_SHA (shallow history? use fetch-depth: 0)"
}
log "merge-base: ${merge_base:0:12}"

extract_at "$merge_base" "$WORK/base"
extract_at "$HEAD_SHA"   "$WORK/head"

scan_dir "$WORK/base" "$WORK/scan/base/out.json" "$SCANNER"
scan_dir "$WORK/head" "$WORK/scan/head/out.json" "$SCANNER"

python3 "$SCRIPT_DIR/normalise.py" "$WORK/scan/base/out.json" > "$WORK/base.tsv" \
  || die "could not normalise baseline results"
python3 "$SCRIPT_DIR/normalise.py" "$WORK/scan/head/out.json" > "$WORK/head.tsv" \
  || die "could not normalise head results"

# Allowed introduced findings (reviewed exceptions), optional.
: > "$WORK/allow.tsv"
if [ -n "$ALLOW_FILE" ] && [ -f "$ALLOW_FILE" ]; then
  grep -vE '^[[:space:]]*(#|$)' "$ALLOW_FILE" \
    | awk -F'[[:space:]]+' '{print $1"\t"$2"\t"$3}' >> "$WORK/allow.tsv" || true
fi

python3 "$SCRIPT_DIR/diff-logic.py" \
  "$WORK/base.tsv" "$WORK/head.tsv" "$WORK/allow.tsv" "$BLOCK" "$SUMMARY"
rc=$?
exit $rc
