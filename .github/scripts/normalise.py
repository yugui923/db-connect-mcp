#!/usr/bin/env python3
"""Normalise osv-scanner JSON into a flat TSV of findings.

Output columns: ecosystem, package, version, advisory, severity

The advisory is reduced to its CVE family where one exists, so a GHSA record and
its CVE alias collapse to one identity instead of counting twice. Use the higher
of the database rating and the scanner's computed maximum CVSS score for the
advisory group. A record without usable severity is marked UNKNOWN.
"""

import json
import re
import sys

SEV_ORDER = ("UNKNOWN", "LOW", "MODERATE", "HIGH", "CRITICAL")


def score_rating(value):
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if not 0 <= score <= 10:
        return "UNKNOWN"
    if score >= 9:
        return "CRITICAL"
    if score >= 7:
        return "HIGH"
    if score >= 4:
        return "MODERATE"
    return "LOW" if score > 0 else "UNKNOWN"


def cve_family(adv_id, aliases):
    for alias in aliases or []:
        if re.fullmatch(r"CVE-\d{4}-\d+", alias or ""):
            return alias
    return adv_id or "UNKNOWN"


def severity_of(vuln, group_ratings):
    ds = vuln.get("database_specific") or {}
    sev = (ds.get("severity") or "").strip().upper()
    if sev == "MEDIUM":
        sev = "MODERATE"
    if sev not in SEV_ORDER:
        sev = "UNKNOWN"
    return max((sev, *group_ratings), key=SEV_ORDER.index)


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
            ratings = {}
            for group in pkg.get("groups") or []:
                rating = score_rating(group.get("max_severity"))
                for advisory in group.get("ids") or []:
                    ratings.setdefault(advisory, []).append(rating)
            for vuln in pkg.get("vulnerabilities") or []:
                advisory = vuln.get("id")
                adv = cve_family(advisory, vuln.get("aliases"))
                row = (
                    eco,
                    name,
                    version,
                    adv,
                    severity_of(vuln, ratings.get(advisory, ())),
                )
                if row in seen:
                    continue
                seen.add(row)
                print("\t".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
