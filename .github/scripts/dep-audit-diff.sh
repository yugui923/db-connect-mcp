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
LOCK_PATTERN='(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|npm-shrinkwrap\.json|uv\.lock|poetry\.lock|Pipfile\.lock|go\.sum)$'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/base" "$WORK/head" "$WORK/scan/base" "$WORK/scan/head" "$WORK/bin"

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
lockfiles_at() {
  git ls-tree -r --name-only "$1" | grep -E "$LOCK_PATTERN" | grep -v -E '(^|/)node_modules/' || true
}

extract_at() {
  local sha="$1" dest="$2" files
  files="$(lockfiles_at "$sha")"
  if [ -z "$files" ]; then
    log "::warning::no recognised lockfiles at ${sha:0:12}; nothing to scan"
    return 0
  fi
  printf '%s\n' "$files" > "$WORK/paths"
  mapfile -t arr < "$WORK/paths"
  git archive --format=tar -o "$WORK/tree.tar" "$sha" -- "${arr[@]}" 2>"$WORK/archive.err" || {
    cat "$WORK/archive.err" >&2
    die "git archive failed for ${sha:0:12}"
  }
  tar -xf "$WORK/tree.tar" -C "$dest" || die "tar extract failed for ${sha:0:12}"
}

# --- scan --------------------------------------------------------------------
# A scanner failure must never read as "no vulnerabilities": exit 2 closes the
# gate instead of opening it.
scan_dir() {
  local src="$1" out="$2" scanner="$3" have rc
  have="$(find "$src" -type f | wc -l | tr -d ' ')"
  if [ "$have" = "0" ]; then
    printf '{"results":[]}' > "$out"
    return 0
  fi
  "$scanner" scan source --recursive --format json "$src" >"$out" 2>"$WORK/scan.err"
  rc=$?
  # osv-scanner exits 1 when it finds vulnerabilities; that is a result, not an
  # error. Anything else is a real failure.
  if [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then
    tail -20 "$WORK/scan.err" >&2
    die "scanner failed (exit $rc) scanning $src"
  fi
  [ -s "$out" ] || die "scanner produced no output for $src"
  python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$out" 2>/dev/null \
    || die "scanner output is not valid JSON for $src"
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
