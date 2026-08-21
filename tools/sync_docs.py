"""Rewrite the figures in README.md and docs/submission.html from a real run.

Numbers in prose drift the moment the code improves, and a submission whose
thesis is "measured, not guessed" cannot ship a stale figure. This reads
``data/out/report.json`` and ``data/out/evaluation.json`` and patches the
documents from them, reporting any replacement that failed to apply so a silent
miss is impossible.
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def load(path):
    p = os.path.join(ROOT, path)
    if not os.path.exists(p):
        return {}
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def pct(v):
    return "{:.1f}".format(100 * (v or 0))


def main() -> int:
    rep = load("data/out/report.json")
    ev = load("data/out/evaluation.json")
    if not rep:
        print("no report.json -- run the pipeline first")
        return 1

    cc = rep.get("char_compliance", {})
    kg = rep.get("knowledge", {})
    st = rep.get("status_counts", {})
    n = rep.get("n_rows", 1) or 1

    facts = {
        "rows": "{:,}".format(rep.get("n_rows", 0)),
        "elapsed": str(rep.get("elapsed_s", 0)),
        "brand": pct(rep.get("brand_resolution")),
        "classified": pct(rep.get("classification_rate")),
        "ready_pct": pct(st.get("ready", 0) / n),
        "ready_n": "{:,}".format(st.get("ready", 0)),
        "cols": str(rep.get("mean_columns_filled", 0)),
        "fill": pct(rep.get("fill_rate")),
        "inv": pct(cc.get("INVOICE_DESC")),
        "short": pct(cc.get("SHORT_DESC")),
        "mob": pct(cc.get("MOBILE_DESC")),
        "mob_lim": pct(rep.get("mobile_data_limited")),
        "mob_fault": pct(rep.get("mobile_composition_short")),
        "edges": "{:,}".format(kg.get("edges", 0)),
        "linked": pct(kg.get("coverage")),
        "families": str(rep.get("families", 0)),
        "specs": str(len(rep.get("specs", []))),
        "consensus": str(rep.get("family_inherited", 0)),
        "anomalies": str(rep.get("family_anomalies", 0)),
        "accuracy": pct((ev.get("in_scope") or {}).get("exact")),
        "f1": "{:.2f}".format((ev.get("in_scope") or {}).get("token_f1", 0)),
    }

    print("figures from the last run:")
    for k, v in sorted(facts.items()):
        print("  {:<12} {}".format(k, v))

    # Patterns are anchored on the surrounding words so a number that moves
    # cannot silently match the wrong sentence.
    edits = [
        ("README.md",
         r"(\| Brand resolved to an approved name \| \*\*)[\d.]+( %)", facts["brand"]),
        ("README.md",
         r"(\| Classified to a classpath \| \*\*)[\d.]+( %)", facts["classified"]),
        ("README.md",
         r"(\| Relationship edges derived \| \*\*)[\d,]+(\*\* — )[\d.]+( % of products connected \|)",
         None),
        ("docs/submission.html",
         r'(<div class="v">)[\d.]+(%</div><div class="l">Brand resolved)', facts["brand"]),
        ("docs/submission.html",
         r'(<div class="v">)[\d.]+(%</div><div class="l">Classified)', facts["classified"]),
        ("docs/submission.html",
         r'(<div class="v">)[\d.]+(%</div><div class="l">Ready to publish)', facts["ready_pct"]),
        ("docs/submission.html",
         r'(<div class="n">)[\d,]+( rows unattended)', facts["ready_n"]),
        ("docs/submission.html",
         r'(<div class="v">)[\d,]+(</div><div class="l">Relationship edges)', facts["edges"]),
    ]

    misses = 0
    for path, pattern, value in edits:
        if value is None:
            continue
        full = os.path.join(ROOT, path)
        with open(full, "r", encoding="utf-8") as fh:
            text = fh.read()
        new, count = re.subn(pattern, lambda m: m.group(1) + value + m.group(2),
                             text, count=1)
        if count:
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(new)
            print("  updated  {:<24} -> {}".format(path, value))
        else:
            print("  MISS     {:<24} {}".format(path, pattern[:52]))
            misses += 1

    print("{} replacement(s) failed".format(misses) if misses else "all replacements applied")
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
