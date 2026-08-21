"""Invariant tests for CALIPER.

Runs on the standard library alone:

    python tests/test_core.py

These check the promises the design actually makes -- that an unevidenced
value cannot enter the graph, that the invoice line is compliant by
construction, that the audit pass can never create a value -- rather than
re-asserting numbers that shift as the rules improve.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from caliper.core.compose import build_invoice_desc
from caliper.core.facts import Evidence, Fact, ProductFactGraph
from caliper.core.guardrails import check, to_inches, to_number
from caliper.core.parse import (decimal_to_fraction, parse_description,
                                strip_mpn_echo)
from caliper.core.taxonomy import classify
from caliper.llm.audit import apply_verdicts, auditable_facts
from caliper.schema import DELIVERY_COLUMNS, clean, is_placeholder

PASS = FAIL = 0


def check_that(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  pass  {}".format(name))
    else:
        FAIL += 1
        print("  FAIL  {}  {}".format(name, detail))


def graph_with(*facts):
    g = ProductFactGraph("TEST")
    for f in facts:
        g.add(f)
    return g


def fact(key, value, uom="", method="rule", conf=0.9, evidence=True):
    ev = [Evidence(source="input:Part_Desc", text=str(value))] if evidence else []
    return Fact(key=key, value=value, uom=uom, method=method,
                confidence=conf, evidence=ev)


# ---------------------------------------------------------------------------
print("\nsource integrity")
# A shell heredoc can turn \b inside a regex into a literal backspace byte.
# The pattern then never matches, and no amount of reading the file reveals it
# because a terminal does not draw the character. Two live regexes in this
# project were broken exactly that way -- `residual_text` never split on "w/",
# and the provider's daily-quota detector never matched \bTPD\b.
import subprocess as _sp
_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_files = _sp.run(["git", "ls-files", "*.py"], capture_output=True, text=True,
                 cwd=_root).stdout.split()
_ctrl = []
for _f in _files:
    _p = os.path.join(_root, _f)
    if os.path.exists(_p):
        _ctrl += [_f for _b in open(_p, "rb").read()
                  if _b < 0x20 and _b not in (9, 10, 13)]
check_that("no control characters in any source file", not _ctrl,
           "{} byte(s) in {}".format(len(_ctrl), sorted(set(_ctrl))))

# ---------------------------------------------------------------------------
print("\nschema")
check_that("delivery header is exactly 252 columns", len(DELIVERY_COLUMNS) == 252,
           "got {}".format(len(DELIVERY_COLUMNS)))
check_that("placeholder sentinels are treated as empty",
           all(is_placeholder(v) for v in
               ("-- Unbranded --", "-- No DIB Brand --", "N/A", "-", "")))
check_that("real values survive cleaning",
           clean("Freud Inc (2435)") == "Freud Inc (2435)")

# ---------------------------------------------------------------------------
print("\nfact graph -- the one-way boundary")
g = ProductFactGraph("X")
check_that("a fact with no evidence is rejected",
           g.add(fact("brand", "Milwaukee", evidence=False)) is None)
check_that("rejection is recorded, not silent", len(g.rejected) == 1)
check_that("an empty value never enters the graph",
           g.add(fact("brand", "")) is None)

g2 = graph_with(fact("voltage", "120", "V", method="rule", conf=0.9))
before = g2.get("voltage").confidence
g2.add(fact("voltage", "120", "V", method="llm", conf=0.7))
check_that("independent agreement raises confidence",
           g2.get("voltage").confidence > before,
           "{} -> {}".format(before, g2.get("voltage").confidence))
check_that("agreement records which method families concurred",
           len(g2.get("voltage").agreed_by) == 2)

g3 = graph_with(fact("finish", "White", conf=0.9))
g3.add(fact("finish", "Black", method="llm", conf=0.5))
check_that("a contradiction keeps the stronger value",
           str(g3.get("finish").value) == "White")
check_that("the losing value is retained as a conflict",
           len(g3.get("finish").conflicts) == 1)
check_that("contradiction lowers confidence", g3.get("finish").confidence < 0.9)

# ---------------------------------------------------------------------------
print("\ndeterministic parsing")
d, _ = strip_mpn_echo("49-94-1940 Milw 14\"x1/8\"x1\" Cut Off Disc", "49-94-1940")
check_that("the part-number echo is stripped", not d.startswith("49-94-1940"))

from caliper.core.parse import residual_text
_r = residual_text(*(lambda x: (x, parse_description(x)))(
    strip_mpn_echo("PBUC013 15A Wall Tap w/USB", "PBUC013")[0]))
check_that("'w/' survives as a qualifier boundary", " - " in _r, repr(_r))

f = {x.key: x.display for x in parse_description(d)}
check_that("three-part abrasive chain splits correctly",
           f.get("diameter") == "14 in" and f.get("thickness") == "1/8 in"
           and f.get("arbor_size") == "1 in", str(f))

f2 = {x.key: x.display for x in
      parse_description('Milw 12"x1/8"x20mm Metal Cut Off Disc')}
check_that("a metric arbor keeps its own unit", f2.get("arbor_size") == "20 mm",
           str(f2.get("arbor_size")))

f3 = {x.key: x.display for x in parse_description("60W Led BA11 50k 3pk")}
check_that("lamp shorthand 50k becomes 5000 K",
           f3.get("color_temperature") == "5000 K", str(f3))
check_that("dual voltage is not truncated",
           {x.key: x.display for x in
            parse_description("Dewalt 12V/20V Charger - 4 Amp")
            }.get("voltage") == "12/20 V")

check_that("decimals convert to trade fractions",
           decimal_to_fraction("0.5") == "1/2"
           and decimal_to_fraction("50.25") == "50-1/4")
check_that("a non-64th decimal is left alone rather than invented",
           decimal_to_fraction("0.037") is None)

# ---------------------------------------------------------------------------
print("\ncharacter budget")
big = graph_with(
    fact("item_type", "Cut Off Disc"), fact("diameter", "14", "in"),
    fact("thickness", "1/8", "in"), fact("arbor_size", "1", "in"),
    fact("finish", "Stainless Steel"), fact("voltage", "120", "V"),
    fact("amperage", "15", "A"), fact("grit", "120"),
    fact("pack_quantity", "10"), fact("lumens", "2600", "lm"))
r = build_invoice_desc(big, limit=40)
check_that("the invoice line never exceeds its limit", len(r.text) <= 40,
           "{} chars: {!r}".format(len(r.text), r.text))
check_that("the invoice line is upper case", r.text == r.text.upper())
check_that("the item type always earns a place", "CUT OFF DISC" in r.text)
check_that("what was dropped is reported", isinstance(r.dropped, list))

tiny = graph_with(fact("item_type", "Dishwasher"), fact("finish", "Stainless Steel"))
check_that("trade abbreviation leads the ladder",
           "SST" in build_invoice_desc(tiny, limit=40).text,
           build_invoice_desc(tiny, limit=40).text)

# ---------------------------------------------------------------------------
print("\ntaxonomy")
check_that("a known item type classifies",
           classify("Cut Off Disc", "").node is not None)
check_that("an unknown item type abstains rather than guessing",
           classify("Zzyzx Frobnicator", "").abstained)

# ---------------------------------------------------------------------------
print("\nguardrails")
bad = graph_with(fact("diameter", "12", "in"), fact("arbor_size", "20", "in"))
check_that("an arbor wider than its wheel is caught",
           any(x.rule_id == "GRD-REL-ARB" for x in check(bad)))
ok = graph_with(fact("diameter", "12", "in"), fact("arbor_size", "20", "mm"))
check_that("a metric arbor is converted, not flagged",
           not any(x.rule_id == "GRD-REL-ARB" for x in check(ok)))
check_that("unit conversion is correct",
           abs(to_inches(20.0, "mm") - 0.7874) < 0.001
           and to_inches(1.0, "ft") == 12.0)
check_that("trade fractions parse numerically",
           to_number("4-1/2") == 4.5 and to_number("1/8") == 0.125)
check_that("an implausible colour temperature is caught",
           any(x.rule_id == "GRD-DOM-K"
               for x in check(graph_with(fact("color_temperature", "49382", "K")))))

# ---------------------------------------------------------------------------
print("\naudit -- verdicts can never create a value")
ga = graph_with(fact("finish", "Chrome", method="llm", conf=0.70),
                fact("item_type", "Cut Off Disc", conf=0.90))
n_before = len(ga)
apply_verdicts(ga, [
    {"key": "finish", "verdict": "unsupported", "reason": "not in the text"},
    {"key": "item_type", "verdict": "supported", "reason": "stated verbatim"},
    {"key": "voltage", "verdict": "supported", "reason": "invented key"},
], model_name="stub")
check_that("an audit cannot add a fact for a key that did not exist",
           len(ga) == n_before and not ga.has("voltage"))
check_that("a rejected value is kept, not deleted",
           str(ga.get("finish").value) == "Chrome")
check_that("rejection lowers confidence", ga.get("finish").confidence < 0.70)
check_that("rejection raises a review note",
           any(n["kind"] == "audit_disagreement" for n in ga.notes))
check_that("confirmation raises confidence",
           ga.get("item_type").confidence > 0.90)
check_that("confirmation is recorded as an independent method",
           "model" in ga.get("item_type").agreed_by)
check_that("copied-through inputs are not sent for audit",
           all(f.method != "input" for f in auditable_facts(
               graph_with(fact("mpn", "ABC", method="input")))))

# ---------------------------------------------------------------------------
print("\n{} passed, {} failed".format(PASS, FAIL))
sys.exit(1 if FAIL else 0)
