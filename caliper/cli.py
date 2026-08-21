"""Command line interface.

    python -m caliper run  data/input/sample_1000_items.csv -o data/out
    python -m caliper serve
    python -m caliper eval data/out/delivery.csv --truth ground_truth.xlsx

Runs with no API key and no third-party packages. An LLM provider, if
configured, is an upgrade rather than a dependency.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

from .io.tabular import read_table, write_csv, write_xlsx
from .pipeline import Pipeline, RowResult
from .schema import DELIVERY_COLUMNS, detect_schema


def _progress(done: int, total: int) -> None:
    pct = 100.0 * done / max(1, total)
    bar = "#" * int(pct / 2.5)
    sys.stderr.write("\r  enriching [{:<40}] {:>5.1f}%  {}/{}".format(bar, pct, done, total))
    sys.stderr.flush()
    if done >= total:
        sys.stderr.write("\n")


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------
AUDIT_COLUMNS = ["row", "part_number", "column", "value", "method", "confidence",
                 "rule_id", "evidence_source", "evidence_text", "detail"]

REVIEW_COLUMNS = ["row", "part_number", "status", "score", "family_id",
                  "issue_kind", "severity", "message", "affects_family_rows",
                  "review_value"]


def export_audit(results: Sequence[RowResult]) -> List[Dict[str, Any]]:
    """One row per populated cell: the provenance ledger.

    This is the artefact that makes the output explainable -- every value in
    the delivery file can be traced back to the rule that produced it and the
    characters of the input that justified it.
    """
    out: List[Dict[str, Any]] = []
    for r in results:
        pn = r.delivery.get("Mfg_Part_Num", "")
        for col, p in r.provenance.items():
            ev = (p.get("evidence") or [{}])[0]
            out.append({
                "row": r.index + 1, "part_number": pn, "column": col,
                "value": p.get("value", ""), "method": p.get("method", ""),
                "confidence": p.get("confidence", ""),
                "rule_id": p.get("rule_id", ""),
                "evidence_source": ev.get("source", ""),
                "evidence_text": ev.get("text", ""),
                "detail": p.get("detail", ""),
            })
    return out


def export_review_queue(results: Sequence[RowResult]) -> List[Dict[str, Any]]:
    """Rows needing a human, ranked by how much the fix is worth.

    Ranking is uncertainty multiplied by family size: a decision that
    propagates to twenty sibling SKUs is worth twenty times one that does not.
    """
    fam_sizes: Dict[str, int] = {}
    for r in results:
        fam_sizes[r.graph.family_id] = fam_sizes.get(r.graph.family_id, 0) + 1

    out: List[Dict[str, Any]] = []
    for r in results:
        if r.status == "ready":
            continue
        n = fam_sizes.get(r.graph.family_id, 1)
        issues = ([{"kind": v["rule_id"], "severity": v["severity"],
                    "message": v["message"], "column": v.get("column", "")}
                   for v in r.violations] +
                  [{"kind": f.get("kind", "flag"),
                    "severity": f.get("severity", "review"),
                    "message": f.get("message", ""), "column": ""}
                   for f in r.flags])
        for iss in issues or [{"kind": "low_confidence", "severity": "review",
                               "message": "Row confidence below threshold.",
                               "column": ""}]:
            out.append({
                "row": r.index + 1,
                "part_number": r.delivery.get("Mfg_Part_Num", ""),
                "status": r.status, "score": round(r.graph.score(), 4),
                "family_id": r.graph.family_id,
                "issue_kind": iss["kind"], "severity": iss["severity"],
                "message": iss["message"], "affects_family_rows": n,
                "review_value": round((1.0 - r.graph.score()) * n, 3),
            })
    out.sort(key=lambda x: -x["review_value"])
    return out


def cmd_run(args: argparse.Namespace) -> int:
    rows, header = read_table(args.input, sheet=args.sheet)
    if not rows:
        print("No rows found in {}".format(args.input), file=sys.stderr)
        return 1
    if args.limit:
        rows = rows[:args.limit]

    schema = detect_schema(header, rows)
    print("input      : {} ({} rows)".format(args.input, len(rows)))
    print("schema     : " + ", ".join(
        "{}={}".format(k, v) for k, v in schema.roles.items()))

    llm = None
    if args.llm:
        from .llm.provider import get_provider
        llm = get_provider(args.llm)
        if llm:
            print("llm        : {}".format(getattr(llm, "name", args.llm)))
        else:
            print("llm        : no provider key found -- running deterministic only")

    auditor = None
    if args.audit:
        from .llm.provider import get_auditor
        auditor = get_auditor(args.llm)
        if auditor:
            print("audit      : {}".format(getattr(auditor, "name", "on")))

    pipe = Pipeline(llm=llm, auditor=auditor,
                    emit_asset_conventions=args.asset_conventions)
    results, report = pipe.run(rows, schema, progress=_progress)

    os.makedirs(args.out, exist_ok=True)
    delivery = [r.delivery for r in results]

    csv_path = os.path.join(args.out, "delivery.csv")
    write_csv(csv_path, DELIVERY_COLUMNS, delivery)
    xlsx_path = os.path.join(args.out, "delivery.xlsx")
    write_xlsx(xlsx_path, DELIVERY_COLUMNS, delivery)

    audit = export_audit(results)
    write_csv(os.path.join(args.out, "audit_provenance.csv"), AUDIT_COLUMNS, audit)
    queue = export_review_queue(results)
    write_csv(os.path.join(args.out, "review_queue.csv"), REVIEW_COLUMNS, queue)

    from .core.knowledge import EDGE_COLUMNS
    from .core.corrections import CORRECTION_COLUMNS
    write_csv(os.path.join(args.out, "relationships.csv"), EDGE_COLUMNS,
              [e.to_dict() for e in getattr(pipe, "edges", [])])
    write_csv(os.path.join(args.out, "corrections.csv"), CORRECTION_COLUMNS,
              report.corrections.get("items", []))
    pipe.corrections.save()

    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2)
    with open(os.path.join(args.out, "graphs.json"), "w", encoding="utf-8") as fh:
        json.dump([r.to_dict() for r in results], fh, indent=2)

    print()
    print("=" * 62)
    print("  rows enriched        : {}".format(report.n_rows))
    print("  elapsed              : {}s".format(report.elapsed_s))
    print("  product families     : {}".format(report.families))
    print("  category specs       : {} induced".format(len(report.specs)))
    print("  brand resolved       : {:.1%}".format(report.brand_resolution))
    print("  classified           : {:.1%}".format(report.classification_rate))
    print("  mean columns filled  : {} / {}".format(
        report.mean_columns_filled, len(DELIVERY_COLUMNS)))
    print("  status               : {}".format(report.status_counts))
    for col, v in report.char_compliance.items():
        print("  char limit {:<10}: {:.1%}".format(col, v))
    k = report.knowledge or {}
    print("  relationships        : {} edges, {:.0%} of products connected".format(
        k.get("edges", 0), k.get("coverage", 0)))
    print("  family consensus     : {} facts inherited, {} anomalies".format(
        report.family_inherited, report.family_anomalies))
    c = report.corrections or {}
    if c.get("corrections"):
        print("  corrections          : {} stored, {} rows fixed ({} rows each)".format(
            c.get("corrections", 0), c.get("rows_affected", 0),
            c.get("rows_per_correction", 0)))
    if report.audited_rows:
        ac = report.audit_counts or {}
        print("  audit                : {} rows · {} supported, {} rejected, {} unknown"
              .format(report.audited_rows, ac.get("supported", 0),
                      ac.get("unsupported", 0), ac.get("unknown", 0)))
    if report.llm_invoked:
        print("  llm                  : {} of {} rows ({:.0%})".format(
            report.llm_invoked, report.n_rows, report.llm_invoked / max(1, report.n_rows)))
    print("=" * 62)
    print("  delivery  -> {}".format(csv_path))
    print("            -> {}".format(xlsx_path))
    print("  audit     -> {} ({} cells)".format(
        os.path.join(args.out, "audit_provenance.csv"), len(audit)))
    print("  review    -> {} ({} items)".format(
        os.path.join(args.out, "review_queue.csv"), len(queue)))
    print("  graph     -> {} ({} edges)".format(
        os.path.join(args.out, "relationships.csv"), k.get("edges", 0)))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .web.server import serve
    serve(host=args.host, port=args.port, data_dir=args.out)
    return 0


def cmd_learn_spec(args: argparse.Namespace) -> int:
    """Learn positional category specifications from labelled delivery rows."""
    from .core.packs import learn_packs, DEFAULT_PACK_PATH
    from .eval.harness import extract_input_rows

    truth_rows, _ = read_table(args.truth, sheet=args.sheet)
    if not truth_rows:
        print("no rows in {}".format(args.truth), file=sys.stderr)
        return 1

    # Run the pipeline on the input recovered from the labelled file so each
    # labelled slot can be aligned to the fact key that actually produces it.
    inputs = extract_input_rows(truth_rows)
    schema = detect_schema(list(inputs[0].keys()), inputs)
    pipe = Pipeline()
    results, _ = pipe.run(inputs, schema)
    lookup = {}
    for r in results:
        pn = str(r.delivery.get("Mfg_Part_Num", "")).strip()
        if pn:
            lookup[pn] = {f.key: f.display for f in r.graph.facts()}

    lib = learn_packs(truth_rows, lookup, source=os.path.basename(args.truth))
    out = args.out or DEFAULT_PACK_PATH
    lib.save(out)

    print("learned {} category pack(s) from {} labelled row(s)".format(
        len(lib), len(truth_rows)))
    for cp, pack in lib.packs.items():
        aligned = sum(1 for s2 in pack.slots if s2.key)
        print("  {}".format(cp))
        print("    {} slots · {} aligned to a fact key by value match".format(
            len(pack.slots), aligned))
        for s2 in sorted(pack.slots, key=lambda x: x.position)[:20]:
            print("      {:>2}. {:<28} -> {}".format(
                s2.position, s2.label, s2.key or "(unaligned)"))
    print("saved -> {}".format(out))
    return 0


def cmd_correct(args: argparse.Namespace) -> int:
    """Record a reviewer decision that persists across runs."""
    from .core.corrections import Correction, CorrectionStore

    store = CorrectionStore.load()
    if args.list:
        summary = store.summary()
        print("{} correction(s) stored, {} row(s) fixed on the last run"
              .format(summary["corrections"], summary["rows_affected"]))
        for c in summary["items"]:
            print("  [{}] {} · {} = {!r}  (applied to {} row(s)) — {}".format(
                c["scope"], c["target"], c["key"], c["value"], c["applied"],
                c["by"]))
        return 0
    if args.remove:
        n = store.remove(args.scope, args.target, args.key)
        store.save()
        print("removed {} correction(s)".format(n))
        return 0
    if not (args.target and args.key and args.value):
        print("need --target, --key and --value (or --list / --remove)",
              file=sys.stderr)
        return 1

    store.add(Correction(scope=args.scope, target=args.target, key=args.key,
                         value=args.value, uom=args.uom, note=args.note,
                         by=args.by))
    store.save()
    print("recorded: [{}] {} · {} = {!r}".format(
        args.scope, args.target, args.key, args.value))
    print("scope '{}' means this decision replays on every future run.".format(
        args.scope))
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from .eval.harness import run_evaluation
    return run_evaluation(args.predicted, args.truth, args.out)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="caliper",
        description="CALIPER -- evidence-bound product intelligence. "
                    "Measured, not guessed.")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="enrich a catalogue into the delivery format")
    r.add_argument("input", help="CSV/XLSX catalogue file")
    r.add_argument("-o", "--out", default="data/out", help="output directory")
    r.add_argument("--sheet", default=None, help="sheet name for XLSX input")
    r.add_argument("--limit", type=int, default=0, help="process only N rows")
    r.add_argument("--llm", default="", help="provider: groq|gemini|anthropic|openai")
    r.add_argument("--audit", action="store_true",
                   help="second-opinion pass: the model reviews facts the "
                        "deterministic engines produced instead of writing new ones")
    r.add_argument("--asset-conventions", action="store_true",
                   help="emit convention-derived asset filenames (unverified; "
                        "routed to review)")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("serve", help="run the dashboard")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("-o", "--out", default="data/out")
    s.set_defaults(func=cmd_serve)

    ls = sub.add_parser("learn-spec",
                        help="learn category specs from labelled delivery rows")
    ls.add_argument("truth", help="labelled delivery-format CSV/XLSX")
    ls.add_argument("--sheet", default=None)
    ls.add_argument("-o", "--out", default="", help="pack file to write")
    ls.set_defaults(func=cmd_learn_spec)

    co = sub.add_parser("correct",
                        help="record a reviewer decision that persists across runs")
    co.add_argument("--scope", default="part",
                    choices=["part", "family", "classpath", "brand"])
    co.add_argument("--target", default="", help="part number / family id / supplier string")
    co.add_argument("--key", default="", help="fact key, e.g. brand or item_type")
    co.add_argument("--value", default="")
    co.add_argument("--uom", default="")
    co.add_argument("--note", default="")
    co.add_argument("--by", default="reviewer")
    co.add_argument("--list", action="store_true")
    co.add_argument("--remove", action="store_true")
    co.set_defaults(func=cmd_correct)

    e = sub.add_parser("eval", help="score output against labelled ground truth")
    e.add_argument("predicted", help="delivery-format CSV produced by `run`")
    e.add_argument("--truth", required=True, help="labelled delivery-format file")
    e.add_argument("-o", "--out", default="data/out", help="where to write the report")
    e.set_defaults(func=cmd_eval)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
