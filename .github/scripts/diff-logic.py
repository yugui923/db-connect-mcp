#!/usr/bin/env python3
"""Compare two normalized vulnerability sets and decide whether to block.

Identity is (ecosystem, package, advisory). Never a total, never a severity sum.
Kept as a separate file so the semantics can be unit-tested without Docker or a
Git checkout — the failure mode we care about is a comparison bug that turns a
new critical into a pass.
"""
import sys
from pathlib import Path


def load(path):
    rows = []
    if not Path(path).is_file():
        return rows
    with Path(path).open() as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = (line.split("\t") + ["?"] * 5)[:5]
            rows.append(
                dict(
                    eco=parts[0],
                    name=parts[1],
                    ver=parts[2],
                    adv=parts[3],
                    sev=parts[4],
                )
            )
    return rows


def ident(r):
    return (r["eco"], r["name"], r["adv"])


def load_allow(path):
    allowed = set()
    if not Path(path).is_file():
        return allowed
    with Path(path).open() as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3 and not line.lstrip().startswith("#"):
                allowed.add((parts[0], parts[1], parts[2]))
    return allowed


def table(rows):
    out, seen = [], set()
    for r in sorted(rows, key=lambda x: (x["eco"], x["name"], x["adv"])):
        k = (r["eco"], r["name"], r["adv"], r["ver"], r["sev"])
        if k in seen:
            continue
        seen.add(k)
        out.append(
            f"| {r['sev']} | `{r['name']}` {r['ver']} "
            f"| {r['eco']} | {r['adv']} |"
        )
    return out


def main(argv):
    base_p, head_p, allow_p, block_spec = argv[1:5]
    summary_p = argv[5] if len(argv) > 5 else ""
    block = {s.strip().upper() for s in block_spec.split(",") if s.strip()}

    base, head = load(base_p), load(head_p)
    allow = load_allow(allow_p)

    base_ids = {ident(r) for r in base}
    head_ids = {ident(r) for r in head}

    introduced = [r for r in head if ident(r) not in base_ids and ident(r) not in allow]
    inherited = [r for r in head if ident(r) in base_ids]
    resolved = [r for r in base if ident(r) not in head_ids]
    allowed_hits = [r for r in head if ident(r) in allow and ident(r) not in base_ids]
    blocking = [r for r in introduced if r["sev"] in block]

    L = ["## Dependency vulnerability delta", ""]
    L.append(
        f"Baseline (merge-base) findings: **{len(base)}** "
        f"· head findings: **{len(head)}**"
    )
    L.append("")
    L.append(f"- Introduced by this PR: **{len(introduced)}**")
    L.append(f"- Inherited from base, does not block: **{len(inherited)}**")
    L.append(f"- Resolved by this PR: **{len(resolved)}**")
    L.append("")

    if blocking:
        L.append(f"### ❌ Introduced {', '.join(sorted(block))} findings")
        L.append("")
        L.extend(["| Severity | Package | Ecosystem | Advisory |", "|---|---|---|---|"])
        L.extend(table(blocking))
        L.append("")
    else:
        L.append(f"### ✅ No {', '.join(sorted(block))} findings introduced by this PR")
        L.append("")

    def detail(title, rows):
        if not rows:
            return
        L.append(f"<details><summary>{title} ({len(rows)})</summary>")
        L.append("")
        L.extend(["| Severity | Package | Ecosystem | Advisory |", "|---|---|---|---|"])
        L.extend(table(rows))
        L.append("")
        L.append("</details>")
        L.append("")

    detail("Resolved by this PR", resolved)
    detail("Inherited and still present — allowed, not introduced here", inherited)
    detail("Introduced but explicitly allowed", allowed_hits)

    report = "\n".join(L)
    print(report)
    if summary_p:
        with open(summary_p, "w") as fh:
            fh.write(report + "\n")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
