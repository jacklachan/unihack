"""Evaluation against labelled delivery-format rows.

The published pack ships two fully enriched rows. That is a small calibration
set, and this harness says so rather than averaging the fact away -- every
number carries its sample size, and nothing is reported as a guarantee.

Because the delivery format *contains* the six input columns, ground truth is
self-sufficient: the harness reconstructs the input from the labelled file,
runs the pipeline on it, and compares the result column by column. Drop in a
200-row version of the same file and every number below scales up untouched.

Three scores per field, because exact string match is the wrong instrument for
a 300-character description:

* **exact**      -- byte-identical after trimming
* **normalised** -- case, whitespace, punctuation and unit spacing folded
* **token F1**   -- overlap of content tokens, for free-text fields
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..io.tabular import read_table, write_csv
from ..schema import (DELIVERY_COLUMNS, FIELD_RULES, InputSchema, clean,
                      detect_schema)

#: The six columns a supplier actually hands over.
INPUT_ROLE_COLUMNS = ["Mfg_Part_Num", "Part_Desc", "E1_Brand", "Unilog_Brand",
                      "DIB_Brand", "Part_Manuf"]

#: Free-text fields judged on token overlap rather than exact match.
FREE_TEXT = {"LONG_DESC1", "MARKETING_DESCRIPTION", "SHORT_DESC", "RETAIL_DESC",
             "MOBILE_DESC", "Standard/Approvals"}

#: Columns that require retrieval from manufacturer sources. Scored separately
#: so they do not silently drag down the fields the pipeline actually targets.
RETRIEVAL_ONLY = {
    "MFR URL", "Ref URL 1", "Ref URL 2", "Ref URL 3", "Ref URL 4", "Ref URL 5",
    "Product Image", "Alternate Image 1", "Alternate Image 2",
    "Alternate Image 3", "Alternate Image 4", "SDS", "SDS_1",
    "Specification Sheet", "Instruction/Installation Manual", "Service Manual",
    "Owners/User Manual", "Line Drawing", "Catalog", "Warranty Information",
    "Warranty", "UPC", "EAN", "GTIN", "List Price", "Country Of Origin",
    "MARKETING_DESCRIPTION", "Actual Image (Yes/No)", "Discontinued",
}

_WORD = re.compile(r"[a-z0-9]+(?:[./-][a-z0-9]+)*")


def _norm(s: Any) -> str:
    t = str(s or "").strip().lower()
    t = t.replace("®", "").replace("™", "")
    t = re.sub(r"(\d)\s+(in|ft|mm|cm|v|a|w|k|hp|ga|lm|dba|ph)\b", r"\1\2", t)
    t = re.sub(r"[^\w\s./-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _tokens(s: Any) -> List[str]:
    return _WORD.findall(_norm(s))


def token_f1(a: Any, b: Any) -> float:
    ta, tb = Counter(_tokens(a)), Counter(_tokens(b))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    overlap = sum((ta & tb).values())
    if not overlap:
        return 0.0
    p, r = overlap / sum(ta.values()), overlap / sum(tb.values())
    return 2 * p * r / (p + r)


# ---------------------------------------------------------------------------
class FieldScore:
    __slots__ = ("column", "n", "exact", "normalised", "f1_sum",
                 "pred_blank", "truth_blank", "both_blank")

    def __init__(self, column: str):
        self.column = column
        self.n = 0
        self.exact = 0
        self.normalised = 0
        self.f1_sum = 0.0
        self.pred_blank = 0
        self.truth_blank = 0
        self.both_blank = 0

    def add(self, pred: str, truth: str) -> None:
        p, t = str(pred or "").strip(), str(truth or "").strip()
        if not p and not t:
            self.both_blank += 1
            return
        self.n += 1
        if not p:
            self.pred_blank += 1
        if not t:
            self.truth_blank += 1
        if p == t:
            self.exact += 1
        if _norm(p) == _norm(t):
            self.normalised += 1
        self.f1_sum += token_f1(p, t)

    def to_dict(self) -> Dict[str, Any]:
        n = max(1, self.n)
        return {
            "column": self.column, "scored": self.n,
            "exact": round(self.exact / n, 4),
            "normalised": round(self.normalised / n, 4),
            "token_f1": round(self.f1_sum / n, 4),
            "missed_blank": self.pred_blank,
            "over_filled": self.truth_blank,
            "both_blank": self.both_blank,
        }


def extract_input_rows(truth_rows: Sequence[Dict[str, str]]
                       ) -> List[Dict[str, str]]:
    """Recover the supplier's original six columns from a labelled file."""
    out = []
    for r in truth_rows:
        row = {c: r.get(c, "") for c in INPUT_ROLE_COLUMNS if c in r}
        if any(str(v).strip() for v in row.values()):
            out.append(row)
    return out


def evaluate(predicted: Sequence[Dict[str, str]],
             truth: Sequence[Dict[str, str]],
             key: str = "Mfg_Part_Num") -> Dict[str, Any]:
    """Score predicted delivery rows against labelled ones, matched on part number."""
    pred_by = {}
    for r in predicted:
        k = str(r.get(key, "")).strip()
        if k:
            pred_by.setdefault(k, r)

    scores: Dict[str, FieldScore] = {}
    matched = 0
    per_row: List[Dict[str, Any]] = []

    for t in truth:
        k = str(t.get(key, "")).strip()
        p = pred_by.get(k)
        if p is None:
            continue
        matched += 1
        row_exact = row_n = 0
        for col in DELIVERY_COLUMNS:
            if col not in t:
                continue
            fs = scores.setdefault(col, FieldScore(col))
            before = fs.n
            fs.add(p.get(col, ""), t.get(col, ""))
            if fs.n > before:
                if str(p.get(col, "")).strip() == str(t.get(col, "")).strip():
                    row_exact += 1
                if _norm(p.get(col, "")) == _norm(t.get(col, "")):
                    row_n += 1
        scored = sum(1 for c in DELIVERY_COLUMNS
                     if c in t and (str(p.get(c, "")).strip() or str(t.get(c, "")).strip()))
        per_row.append({"key": k, "scored_fields": scored,
                        "exact": row_exact, "normalised": row_n,
                        "exact_rate": round(row_exact / max(1, scored), 4)})

    # Aggregate, splitting out the fields that need retrieval we do not do.
    def agg(cols: Sequence[str]) -> Dict[str, Any]:
        n = sum(scores[c].n for c in cols if c in scores)
        if not n:
            return {"scored": 0, "exact": 0.0, "normalised": 0.0, "token_f1": 0.0}
        return {
            "scored": n,
            "exact": round(sum(scores[c].exact for c in cols if c in scores) / n, 4),
            "normalised": round(sum(scores[c].normalised for c in cols if c in scores) / n, 4),
            "token_f1": round(sum(scores[c].f1_sum for c in cols if c in scores) / n, 4),
        }

    inscope = [c for c in scores if c not in RETRIEVAL_ONLY]
    retrieval = [c for c in scores if c in RETRIEVAL_ONLY]

    return {
        "rows_in_truth": len(truth),
        "rows_matched": matched,
        "overall": agg(list(scores)),
        "in_scope": agg(inscope),
        "retrieval_dependent": agg(retrieval),
        "per_field": sorted(
            (scores[c].to_dict() for c in scores if scores[c].n),
            key=lambda d: (-d["scored"], d["column"])),
        "per_row": per_row,
        "caveat": ("Calibration set is {} labelled row(s). Treat every rate as an "
                   "indication, not a guarantee -- the confidence interval on {} "
                   "samples is wide.".format(len(truth), len(truth))),
    }


def char_limit_report(rows: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    """Compliance with the guideline character limits and casing rules."""
    out: Dict[str, Any] = {}
    for col, rule in FIELD_RULES.items():
        vals = [str(r.get(col, "")).strip() for r in rows]
        vals = [v for v in vals if v]
        if not vals:
            continue
        ok = 0
        for v in vals:
            good = True
            if rule.max_len and len(v) > rule.max_len:
                good = False
            if rule.min_len and len(v) < rule.min_len:
                good = False
            if rule.casing == "upper" and v != v.upper():
                good = False
            ok += good
        out[col] = {
            "rule_id": rule.rule_id, "populated": len(vals),
            "compliant": round(ok / len(vals), 4),
            "limit": "{}-{}".format(rule.min_len or 0, rule.max_len or "-"),
            "casing": rule.casing,
            "mean_len": round(sum(len(v) for v in vals) / len(vals), 1),
        }
    return out


def lov_coverage(rows: Sequence[Dict[str, str]],
                 lov: Optional[Dict[str, set]] = None) -> Dict[str, Any]:
    """Share of emitted attribute values drawn from a controlled vocabulary.

    With no official LOV in the pack, coverage is measured against the
    vocabulary CALIPER induced from the catalogue itself. That is a weaker
    claim than matching Unilog's master list and is labelled as such -- but it
    still answers the real question: are values drawn from a closed, repeated
    set, or invented per row?
    """
    per_label: Dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        for i in range(1, 51):
            lab = str(r.get("ATTRIBUTE_LABEL {}".format(i), "")).strip()
            val = str(r.get("ATTRIBUTE_VALUE {}".format(i), "")).strip()
            if lab and val:
                per_label[lab][val] += 1

    total = sum(sum(c.values()) for c in per_label.values())
    repeated = sum(n for c in per_label.values() for v, n in c.items() if n > 1)
    singletons = sum(1 for c in per_label.values() for v, n in c.items() if n == 1)

    in_lov = None
    if lov:
        hit = 0
        for lab, c in per_label.items():
            allowed = lov.get(lab) or lov.get(lab.lower()) or set()
            for v, n in c.items():
                if not allowed or v in allowed or v.lower() in {a.lower() for a in allowed}:
                    hit += n
        in_lov = round(hit / max(1, total), 4)

    return {
        "attribute_values_emitted": total,
        "distinct_labels": len(per_label),
        "closed_set_rate": round(repeated / max(1, total), 4),
        "singleton_values": singletons,
        "in_official_lov": in_lov,
        "source": "official LOV" if lov else "induced vocabulary (no official LOV shipped)",
        "top_labels": [
            {"label": lab, "distinct": len(c), "emitted": sum(c.values()),
             "examples": [v for v, _ in c.most_common(5)]}
            for lab, c in sorted(per_label.items(),
                                 key=lambda x: -sum(x[1].values()))[:15]],
    }


def run_evaluation(predicted_path: str, truth_path: str, out_dir: str) -> int:
    """CLI entry: score `predicted` against `truth` and write a report."""
    truth_rows, _ = read_table(truth_path)
    if not truth_rows:
        print("no rows in {}".format(truth_path))
        return 1

    if predicted_path and os.path.exists(predicted_path):
        pred_rows, _ = read_table(predicted_path)
    else:
        # No prediction file: run the pipeline on the input recovered from truth.
        from ..pipeline import Pipeline
        inputs = extract_input_rows(truth_rows)
        schema = detect_schema(list(inputs[0].keys()), inputs)
        results, _ = Pipeline().run(inputs, schema)
        pred_rows = [r.delivery for r in results]

    report = evaluate(pred_rows, truth_rows)
    report["char_limits"] = char_limit_report(pred_rows)
    report["lov"] = lov_coverage(pred_rows)

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "evaluation.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    write_csv(os.path.join(out_dir, "evaluation_per_field.csv"),
              ["column", "scored", "exact", "normalised", "token_f1",
               "missed_blank", "over_filled", "both_blank"],
              report["per_field"])

    o, i = report["overall"], report["in_scope"]
    print("=" * 66)
    print("  labelled rows        : {} (matched {})".format(
        report["rows_in_truth"], report["rows_matched"]))
    print("  in-scope fields      : exact {:.1%} · normalised {:.1%} · token-F1 {:.2f}"
          .format(i["exact"], i["normalised"], i["token_f1"]))
    print("  all fields           : exact {:.1%} · normalised {:.1%} · token-F1 {:.2f}"
          .format(o["exact"], o["normalised"], o["token_f1"]))
    r = report["retrieval_dependent"]
    print("  retrieval-dependent  : exact {:.1%} ({} cells; not attempted)"
          .format(r["exact"], r["scored"]))
    print("  LOV closed-set rate  : {:.1%} ({})".format(
        report["lov"]["closed_set_rate"], report["lov"]["source"]))
    print("-" * 66)
    for f in report["per_field"][:18]:
        print("  {:<26} n={:<3} exact {:>6.1%}  norm {:>6.1%}  f1 {:.2f}".format(
            f["column"][:26], f["scored"], f["exact"], f["normalised"], f["token_f1"]))
    print("=" * 66)
    print("  " + report["caveat"])
    print("  report -> {}".format(os.path.join(out_dir, "evaluation.json")))
    return 0
