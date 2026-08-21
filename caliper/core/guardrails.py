"""Physical and logical guardrails.

Character-limit validation catches a description that is too long. It does not
catch a cut-off wheel whose arbor hole is larger than the wheel, a 4,000 K
"colour temperature" that is really a part number, or a 500 W LED lamp. Those
are extraction errors that produce perfectly well-formed output.

Every check here is a named rule that reasons about the *values* rather than
their formatting:

* **domain**   -- is this value physically possible for this attribute?
* **relation** -- are these two values coherent with each other?
* **unit**     -- is the unit the right kind of quantity for this attribute?

A guardrail never edits a value. It raises a finding with a rule id, and the
row is routed to review. Silently "fixing" a number the pipeline is unsure
about is how bad data gets laundered into a catalogue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable, Dict, List, Optional, Tuple

from .facts import Fact, ProductFactGraph


# ---------------------------------------------------------------------------
# Numeric parsing that understands trade fractions
# ---------------------------------------------------------------------------
_NUM = re.compile(r"^\s*(-?\d+)?\s*(?:-|\s)?\s*(\d+)\s*/\s*(\d+)\s*$")


def to_number(value: Any) -> Optional[float]:
    """Parse ``14``, ``1/8``, ``4-1/2``, ``0.045``, ``12/20`` -> float.

    ``12/20`` is ambiguous: a dual-voltage platform, not three fifths. Values
    where both sides are >= 5 and the denominator is not a power of two are
    treated as a range and reported as their maximum.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    m = _NUM.match(s)
    if m:
        whole = int(m.group(1)) if m.group(1) else 0
        num, den = int(m.group(2)), int(m.group(3))
        if den == 0:
            return None
        if whole == 0 and num >= 5 and den >= 5 and (den & (den - 1)) != 0:
            return float(max(num, den))          # "12/20" style range
        sign = -1 if whole < 0 else 1
        return float(abs(whole) + Fraction(num, den)) * sign
    m2 = re.match(r"^\s*(-?[\d.]+)", s)
    if m2:
        try:
            return float(m2.group(1))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Domain ranges: (key, min, max, unit_kind, rule_id, note)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DomainRule:
    key: str
    lo: float
    hi: float
    unit_kind: str
    rule_id: str
    note: str


DOMAINS: Tuple[DomainRule, ...] = (
    DomainRule("voltage", 1, 1000, "electrical", "GRD-DOM-V",
               "Mains and tool voltages fall between 1 V and 1000 V."),
    DomainRule("amperage", 0.01, 400, "electrical", "GRD-DOM-A",
               "Catalogue amperages fall between 0.01 A and 400 A."),
    DomainRule("wattage", 0.1, 25000, "electrical", "GRD-DOM-W",
               "Wattage outside 0.1 W - 25 kW is almost always a part number."),
    DomainRule("horsepower", 0.01, 500, "electrical", "GRD-DOM-HP",
               "Motor ratings fall between 0.01 HP and 500 HP."),
    DomainRule("phase", 1, 3, "electrical", "GRD-DOM-PH",
               "Electrical phase is 1 or 3."),
    DomainRule("color_temperature", 1500, 10000, "photometric", "GRD-DOM-K",
               "Lamp colour temperature runs 1500 K (amber) to 10000 K (daylight)."),
    DomainRule("lumens", 5, 200000, "photometric", "GRD-DOM-LM",
               "Rated light output below 5 lm or above 200000 lm is implausible."),
    DomainRule("grit", 8, 8000, "abrasive", "GRD-DOM-GRT",
               "Abrasive grit designations run from 8 (coarse) to 8000 (polishing)."),
    DomainRule("sound_level", 15, 130, "acoustic", "GRD-DOM-DBA",
               "Product sound ratings run 15 dBA to 130 dBA."),
    DomainRule("diameter", 0.01, 120, "length", "GRD-DOM-DIA",
               "Wheel and bit diameters run 0.01 in to 120 in."),
    DomainRule("thickness", 0.001, 24, "length", "GRD-DOM-THK",
               "Thickness runs 0.001 in to 24 in."),
    DomainRule("arbor_size", 0.05, 12, "length", "GRD-DOM-ARB",
               "Arbor holes run 0.05 in to 12 in."),
    DomainRule("length", 0.01, 2000, "length", "GRD-DOM-LEN",
               "Length runs 0.01 to 2000 in the stated unit."),
    DomainRule("pack_quantity", 1, 100000, "count", "GRD-DOM-PK",
               "Pack quantity runs 1 to 100000."),
    DomainRule("selling_qty", 1, 100000, "count", "GRD-DOM-SQ",
               "Selling quantity runs 1 to 100000."),
    DomainRule("gauge", 1, 40, "count", "GRD-DOM-GA",
               "Wire and fastener gauges run 1 to 40."),
    DomainRule("number_of_cycles", 1, 30, "count", "GRD-DOM-CYC",
               "Appliance cycle counts run 1 to 30."),
)

#: Conversion to inches, the canonical unit for the length ranges above.
_TO_INCH: Dict[str, float] = {
    "in": 1.0, "": 1.0, "ft": 12.0, "mm": 1.0 / 25.4, "cm": 1.0 / 2.54,
    "m": 39.3701,
}


def to_inches(n: Optional[float], uom: str) -> Optional[float]:
    if n is None:
        return None
    factor = _TO_INCH.get((uom or "").strip().lower())
    return None if factor is None else n * factor


#: Which units legitimately express which kind of quantity.
UNIT_KINDS: Dict[str, str] = {
    "V": "electrical", "A": "electrical", "W": "electrical", "HP": "electrical",
    "PH": "electrical", "K": "photometric", "lm": "photometric",
    "dBA": "acoustic", "in": "length", "ft": "length", "mm": "length",
    "cm": "length", "m": "length", "GA": "count", "": "any",
}


# ---------------------------------------------------------------------------
# Relational checks
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RelationRule:
    left: str
    right: str
    op: str                    # "<" | "<="
    rule_id: str
    note: str


RELATIONS: Tuple[RelationRule, ...] = (
    RelationRule("arbor_size", "diameter", "<", "GRD-REL-ARB",
                 "An arbor hole must be smaller than the wheel it is cut in. "
                 "If it is not, the dimension chain was read in the wrong order."),
    RelationRule("thickness", "diameter", "<", "GRD-REL-THK",
                 "A bonded abrasive is thinner than it is wide."),
    RelationRule("arbor_size", "length", "<=", "GRD-REL-AL",
                 "Arbor size cannot exceed overall length."),
)


@dataclass
class Finding:
    rule_id: str
    severity: str              # error | warning
    key: str
    message: str
    observed: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"rule_id": self.rule_id, "severity": self.severity,
                "key": self.key, "message": self.message,
                "observed": self.observed, "kind": "guardrail"}


def check(graph: ProductFactGraph) -> List[Finding]:
    """Run every guardrail over one product's facts."""
    out: List[Finding] = []

    # -- domain ranges ----------------------------------------------------
    for rule in DOMAINS:
        f = graph.get(rule.key)
        if not f:
            continue
        n = to_number(f.value)
        if n is None:
            continue
        # Length ranges are stated in inches, so a metric value has to be
        # converted before it is judged -- otherwise a perfectly ordinary
        # 20 mm arbor is reported as twenty inches wide.
        if rule.unit_kind == "length":
            n = to_inches(n, f.uom)
            if n is None:
                continue
        if not (rule.lo <= n <= rule.hi):
            out.append(Finding(
                rule.rule_id, "error", rule.key,
                "{} = {} is outside the plausible range {}-{}. {}".format(
                    f.label, f.display, rule.lo, rule.hi, rule.note),
                observed=f.display))

    # -- unit kinds -------------------------------------------------------
    for rule in DOMAINS:
        f = graph.get(rule.key)
        if not f or not f.uom:
            continue
        kind = UNIT_KINDS.get(f.uom)
        if kind and kind != "any" and kind != rule.unit_kind:
            out.append(Finding(
                "GRD-UNIT-01", "error", rule.key,
                "{} is a {} quantity but carries the unit {!r}, which measures "
                "{}.".format(f.label, rule.unit_kind, f.uom, kind),
                observed=f.display))

    # -- relations --------------------------------------------------------
    for rel in RELATIONS:
        a, b = graph.get(rel.left), graph.get(rel.right)
        if not a or not b:
            continue
        # Convert both sides to inches rather than skipping the comparison:
        # a 12 in wheel with a 20 mm arbor is valid and must not be flagged,
        # but a 12 in wheel with a 20 in arbor still must be.
        na = to_inches(to_number(a.value), a.uom or "in")
        nb = to_inches(to_number(b.value), b.uom or "in")
        if na is None or nb is None:
            continue
        ok = (na < nb) if rel.op == "<" else (na <= nb)
        if not ok:
            out.append(Finding(
                rel.rule_id, "error", rel.left,
                "{} ({}) is not {} {} ({}). {}".format(
                    a.label, a.display, rel.op, b.label, b.display, rel.note),
                observed="{} vs {}".format(a.display, b.display)))

    # -- cross-attribute plausibility -------------------------------------
    lamp = graph.get("lamp_type")
    watt = graph.get("wattage")
    if lamp and watt and str(lamp.value).upper() == "LED":
        n = to_number(watt.value)
        if n is not None and n > 300:
            out.append(Finding(
                "GRD-XAT-LED", "warning", "wattage",
                "An LED lamp rated {} is unusual; the figure is more likely an "
                "equivalent-incandescent rating or a part number."
                .format(watt.display), observed=watt.display))

    ct = graph.get("color_temperature")
    if ct is not None:
        n = to_number(ct.value)
        if n is not None and n % 100 != 0 and n > 1000:
            out.append(Finding(
                "GRD-XAT-K", "warning", "color_temperature",
                "Colour temperature {} is not a round hundred; lamp ratings are "
                "published in round steps (2700 K, 3000 K, 5000 K)."
                .format(ct.display), observed=ct.display))

    # A dimension chain that produced identical values in every position is
    # usually a misparse of a repeated token rather than a real cube.
    dims = [graph.get(k) for k in ("diameter", "thickness", "arbor_size")]
    vals = [to_number(d.value) for d in dims if d]
    if len(vals) == 3 and None not in vals and len(set(vals)) == 1:
        out.append(Finding(
            "GRD-REL-DUP", "warning", "dimensions",
            "All three dimension components are {}; the chain was probably "
            "mis-segmented.".format(vals[0]), observed=str(vals[0])))

    return out


def apply(graph: ProductFactGraph) -> List[Dict[str, Any]]:
    """Run guardrails and record findings on the graph as review notes."""
    findings = check(graph)
    for f in findings:
        graph.note(f.rule_id, f.message,
                   severity="review" if f.severity == "error" else "info",
                   guardrail=True, key=f.key, observed=f.observed)
        fact = graph.get(f.key)
        if fact is not None and f.severity == "error":
            # A value that fails a physical check should not carry high
            # confidence into the delivery decision.
            fact.confidence = min(fact.confidence, 0.45)
    return [f.to_dict() for f in findings]
