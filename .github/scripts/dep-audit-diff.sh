#!/usr/bin/env bash
# dep-audit-diff — incremental dependency-vulnerability gate.
#
# Blocks a pull request only on vulnerabilities the PR *introduces*.
# A HIGH/CRITICAL advisory that exists in the merge-base and still exists on the
# head is reported, never blocking: the PR did not create it, and demanding that
# one PR clear the whole backlog is how a security gate teaches people to
# disable it.
#
# Identity is (package, ecosystem, version, advisory id) — never totals, never a
# severity sum. Removing one advisory while adding another is a new finding and
# fails, even when the numbers look better.
#
# Environment:
#   DEP_AUDIT_BASE_SHA    commit to scan as the baseline (required)
#   DEP_AUDIT_HEAD_SHA    commit to scan as the candidate (default: HEAD)
#   DEP_AUDIT_BLOCK       comma list of severities that block when introduced
#                         (default: CRITICAL,HIGH)
#   DEP_AUDIT_SCANNER     scanner image (default: pinned osv-scanner)
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
SCANNER="${DEP_AUDIT_SCANNER:-ghcr.io/google/osv-scanner@sha256:f7ba4be68bac8086b1f88fd598fdca1ca67239c79ad2c2b5c78e03a82e5187c4}"
SUMMARY="${DEP_AUDIT_SUMMARY:-}"
ALLOW_FILE="${DEP_AUDIT_ALLOW_FILE:-}"

# Lockfiles we understand. Add patterns here rather than scanning whole trees:
# a bounded, explicit set keeps the scan fast and its scope reviewable.
LOCK_PATTERN='(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|npm-shrinkwrap\.json|uv\.lock|poetry\.lock|Pipfile\.lock|go\.sum)$'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/base" "$WORK/head" "$WORK/scan/base" "$WORK/scan/head"

log() { printf '%s\n' "$*" >&2; }

# --- collect the exact lockfile set at a commit ------------------------------
# Uses the commit's own tree, not the working tree, so the result depends only
# on the SHA being asked about.
lockfiles_at() {
  git ls-tree -r --name-only "$1" | grep -E "$LOCK_PATTERN" | grep -v -E '(^|/)node_modules/' || true
}

extract_at() {
  local sha="$1" dest="$2"
  local files
  files="$(lockfiles_at "$sha")"
  if [ -z "$files" ]; then
    log "::warning::no recognised lockfiles at ${sha:0:12}; nothing to scan"
    return 0
  fi
  # Path list goes through a file: some repos have spaces, and an argv list of
  # hundreds of paths risks the limit on large monorepos.
  printf '%s\n' "$files" > "$WORK/paths"
  mapfile -t arr < "$WORK/paths"
  git archive --format=tar -o "$WORK/tree.tar" "$sha" -- "${arr[@]}" 2>"$WORK/archive.err" || {
    log "::error::git archive failed for ${sha:0:12}:"
    cat "$WORK/archive.err" >&2
    exit 2
  }
  tar -xf "$WORK/tree.tar" -C "$dest" || { log "::error::tar extract failed"; exit 2; }
  printf '%s\n' "$files" >> "$dest.files"
}

# --- scan -------------------------------------------------------------------
# A scanner failure must never read as "no vulnerabilities": exit 2 closes the
# gate instead of opening it.
scan_dir() {
  local src="$1" out="$2"
  local have
  have="$(find "$src" -type f | wc -l | tr -d ' ')"
  if [ "$have" = "0" ]; then
    printf '{"results":[]}' > "$out"
    return 0
  fi
  # The scanner image runs unprivileged; a host directory owned by the CI user
  # is not writable from inside it. Hand the result back through stdout and let
  # this shell write the file, so no permissions are shared with the container.
  docker run --rm \
    --volume "$src:/src:ro" \
    --cap-drop=ALL \
    --security-opt=no-new-privileges \
    "$SCANNER" scan source \
      --recursive \
      --no-ignore \
      --format json \
      /src >"$out" 2>"$WORK/scan.err"
  local rc=$?
  # osv-scanner exits 1 when it finds vulnerabilities; that is a result, not an
  # error. Anything else is a real failure.
  if [ $rc -ne 0 ] && [ $rc -ne 1 ]; then
    log "::error::scanner failed (exit $rc) scanning $src"
    tail -20 "$WORK/scan.err" >&2
    exit 2
  fi
  [ -s "$out" ] || { log "::error::scanner produced no output for $src"; exit 2; }
  python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$out" 2>/dev/null || {
    log "::error::scanner output is not valid JSON for $src"; exit 2; }
}

# --- normalise ---------------------------------------------------------------
# Emits one line per finding: ecosystem<TAB>package<TAB>version<TAB>advisory<TAB>severity
# Advisory id is reduced to the GHSA/CVE family so aliases don't split identity.
normalise() {
  python3 - "$1" <<'PY'
import json, sys, re

path = sys.argv[1]
try:
    data = json.load(open(path))
except Exception as exc:                                  # malformed output
    print(f"::error::cannot parse scanner output {path}: {exc}", file=sys.stderr)
    sys.exit(2)

SEV_ORDER = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}

def cve_family(adv_id, aliases):
    # Prefer a CVE alias so GHSA and CVE entries for the same issue collapse.
    for a in aliases or []:
        if re.fullmatch(r"CVE-\d{4}-\d+", a or ""):
            return a
    return adv_id or "UNKNOWN"

def severity_of(vuln):
    ds = (vuln.get("database_specific") or {})
    sev = (ds.get("severity") or "").upper()
    if sev in SEV_ORDER:
        return "MODERATE" if sev == "MEDIUM" else sev
    # Fall back to CVSS vector presence: v4/v3 with a score implies at least
    # moderate; without a parsed score we refuse to guess downward.
    if vuln.get("severity"):
        return "UNKNOWN"
    return "UNKNOWN"

seen = set()
for res in data.get("results", []) or []:
    for pkg in res.get("packages", []) or []:
        info = pkg.get("package", {}) or {}
        name = info.get("name") or "?"
        version = info.get("version") or "?"
        eco = info.get("ecosystem") or "?"
        for vuln in pkg.get("vulnerabilities", []) or []:
            adv = cve_family(vuln.get("id"), vuln.get("aliases"))
            sev = severity_of(vuln)
            row = (eco, name, version, adv, sev)
            if row in seen:
                continue
            seen.add(row)
            print("\t".join(row))
PY
}

key_of() { printf '%s\t%s\t%s' "$1" "$2" "$4"; }   # ecosystem, package, advisory

# --- run ---------------------------------------------------------------------
log "dep-audit-diff: baseline ${BASE_SHA:0:12} → head ${HEAD_SHA:0:12}"

merge_base="$(git merge-base "$BASE_SHA" "$HEAD_SHA" 2>/dev/null)" || {
  log "::error::no merge-base between $BASE_SHA and $HEAD_SHA (history may be shallow; use fetch-depth: 0)"
  exit 2
}
log "merge-base: ${merge_base:0:12}"

extract_at "$merge_base" "$WORK/base"
extract_at "$HEAD_SHA"   "$WORK/head"

scan_dir "$WORK/base" "$WORK/scan/base/out.json"
scan_dir "$WORK/head" "$WORK/scan/head/out.json"

normalise "$WORK/scan/base/out.json" > "$WORK/base.tsv" || exit 2
normalise "$WORK/scan/head/out.json" > "$WORK/head.tsv" || exit 2

# Allowed introduced findings (reviewed exceptions), optional.
: > "$WORK/allow.tsv"
if [ -n "$ALLOW_FILE" ] && [ -f "$ALLOW_FILE" ]; then
  grep -vE '^\s*(#|$)' "$ALLOW_FILE" | awk -F'[[:space:]]+' '{print $1"\t"$2"\t"$3}' >> "$WORK/allow.tsv" || true
fi

python3 "$SCRIPT_DIR/diff-logic.py" "$WORK/base.tsv" "$WORK/head.tsv" "$WORK/allow.tsv" "$BLOCK" "$SUMMARY"
rc=$?
exit $rc
