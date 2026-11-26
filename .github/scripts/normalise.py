#!/usr/bin/env python3
"""Normalise osv-scanner JSON into a flat TSV of findings.

Output columns: ecosystem, package, version, advisory, severity

The advisory is reduced to its CVE family where one exists, so a GHSA record and
its CVE alias collapse to one identity instead of counting twice. Severity comes
from the advisory's own `database_specific.severity`; a record with no usable
severity is reported as UNKNOWN rather than assumed harmless.
"""

import json
import re
import sys

SEV_ORDER = {"CRITICAL", "HIGH", "MODERATE", "MEDIUM", "LOW"}


def cve_family(adv_id, aliases):
    for alias in aliases or []:
        if re.fullmatch(r"CVE-\d{4}-\d+", alias or ""):
            return alias
    return adv_id or "UNKNOWN"


def severity_of(vuln):
    ds = vuln.get("database_specific") or {}
    sev = (ds.get("severity") or "").strip().upper()
    if sev == "MEDIUM":
        return "MODERATE"
    if sev in SEV_ORDER:
        return sev
    return "UNKNOWN"


def main(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception as exc:
        print(f"cannot parse scanner output {path}: {exc}", file=sys.stderr)
        return 2

    seen = set()
    for res in data.get("results") or []:
        for pkg in res.get("packages") or []:
            info = pkg.get("package") or {}
            name = info.get("name") or "?"
            version = info.get("version") or "?"
            eco = info.get("ecosystem") or "?"
            for vuln in pkg.get("vulnerabilities") or []:
                adv = cve_family(vuln.get("id"), vuln.get("aliases"))
                row = (eco, name, version, adv, severity_of(vuln))
                if row in seen:
                    continue
                seen.add(row)
                print("\t".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
