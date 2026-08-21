"""Composition: rendering the delivery format from the fact graph.

Nothing in this module invents a value. Every string it produces is assembled
from facts that already exist in the graph, which is what makes the five
description formats mutually consistent: they are five renderings of one set of
facts, not five independent generations.

The interesting piece is :func:`build_invoice_desc`. ``INVOICE_DESC`` has a hard
40-character ceiling in all caps. Prompting a model to "keep it under 40
characters" fails often and silently. Here it is a budget problem: each fact
contributes a token that has an abbreviation ladder (``Stainless Steel`` ->
``STAINLESS`` -> ``SST`` -> ``SS``), facts are ordered by how much they identify
the product, and the solver fits as many as the budget allows. Compliance is
guaranteed by construction rather than checked afterwards.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .facts import Fact, ProductFactGraph
from .parse import ABBREV_LADDER

# ---------------------------------------------------------------------------
# Invoice line: hard 40 characters, upper case.
# ---------------------------------------------------------------------------
#: Order in which facts earn space on the invoice line. Item type first -- a
#: till receipt that does not say what the thing is has failed.
#: Boolean merchandising flags. "Yes" is meaningless in a description or on an
#: invoice line -- it belongs in its own column, not in prose.
BOOLEAN_KEYS = frozenset({"display_only", "includes_battery"})

#: Never eligible to pad the mobile line. Dept, Class and Fine are where the
#: product sits in a tree, not facts about it -- padding with them produced
#: lines like "Drill, DCD799B, Tools, Power Tools".
SKIP_IN_MOBILE = frozenset({
    "manufacturer", "brand", "item_type", "series", "mpn",
    "dept", "class", "fine", "classpath", "unspsc"}) | BOOLEAN_KEYS

#: Components of a dimension chain. They are worth keeping as separate
#: attributes -- a buyer filters on arbor size -- but printing them beside the
#: chain they came from says the same thing twice and crowds out real
#: differentiators: "Cut Off Disc, 14 in, 1/8 in, 1 in, 14 in x 1/8 in x 1 in".
DIMENSION_PARTS = frozenset({"diameter", "thickness", "arbor_size"})


def _suppress_redundant(graph: ProductFactGraph) -> frozenset:
    """Keys to omit from prose because a composite already states them."""
    if graph.has("dimensions"):
        return DIMENSION_PARTS
    return frozenset()

INVOICE_PRIORITY: Tuple[str, ...] = (
    "item_type", "mounting", "number_of_cycles", "finish", "voltage",
    "amperage", "wattage", "color_temperature", "grit", "diameter",
    "thickness", "arbor_size", "dimensions", "nominal_size", "size",
    "length", "platform", "pack_quantity", "base_type", "bulb_shape",
)

_UNIT_TIGHTEN = re.compile(r"(\d)\s+(IN|FT|V|A|W|K|HP|GA|LM|DBA|PH)\b")


def _ladder(text: str) -> List[str]:
    """Progressively shorter approved forms of one token, longest first."""
    t = str(text or "").strip()
    if not t:
        return []
    low = t.lower()
    if low in ABBREV_LADDER:
        # Trade abbreviation leads; the spelled-out form is the last resort.
        out = list(ABBREV_LADDER[low]) + [t.upper()]
    else:
        out = [t.upper()]
        # Multi-word tokens can shrink by abbreviating any component.
        parts = low.split()
        if len(parts) > 1:
            rebuilt = []
            for p in parts:
                rebuilt.append(ABBREV_LADDER.get(p, [p.upper()])[0])
            cand = " ".join(rebuilt)
            if cand != out[0]:
                out.append(cand)
            out.append("".join(w[:4] for w in parts).upper())
    seen, uniq = set(), []
    for o in out:
        o = o.strip()
        if o and o not in seen:
            seen.add(o)
            uniq.append(o)
    return uniq


def _invoice_token(f: Fact) -> List[str]:
    """Ladder for one fact, tightest form first.

    The published answer key writes the invoice line as
    ``DISHWASHER LEG 5 SST 120V 15A 50-1/4IN`` -- number and unit closed up,
    unlike every other field, where the house style mandates a space. So the
    tightened form leads the ladder here and the spaced form is the fallback.
    """
    base = f.display if f.uom else str(f.value)
    variants = _ladder(base)
    tight = [_UNIT_TIGHTEN.sub(r"\1\2", v) for v in variants]
    seen, out = set(), []
    for v in tight + variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


@dataclass
class BudgetResult:
    text: str
    included: List[str]
    dropped: List[str]
    used: int
    limit: int
    compressions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "included": self.included,
                "dropped": self.dropped, "used": self.used, "limit": self.limit,
                "compressions": self.compressions}


def build_invoice_desc(graph: ProductFactGraph, limit: int = 40) -> BudgetResult:
    """Fit the most identifying facts into ``limit`` characters, all caps.

    Greedy over a priority order, with per-token abbreviation ladders. A token
    is shortened before it is dropped, and dropped before the line overflows --
    so the result is always compliant, and always reports what it gave up.
    """
    ordered: List[Fact] = []
    for key in INVOICE_PRIORITY:
        f = graph.get(key)
        if f:
            ordered.append(f)
    for f in graph.ordered():
        if f not in ordered and f.key not in (
                "brand", "manufacturer", "series", "classpath", "dept",
                "class", "fine", "unspsc", "mpn") and f.key not in BOOLEAN_KEYS:
            ordered.append(f)

    chosen: List[str] = []
    included: List[str] = []
    dropped: List[str] = []
    compressions: List[str] = []

    for f in ordered:
        variants = _invoice_token(f)
        if not variants:
            continue
        placed = False
        for vi, v in enumerate(variants):
            trial = chosen + [v]
            if len(" ".join(trial)) <= limit:
                chosen = trial
                included.append(f.key)
                if vi > 0:
                    compressions.append("{}: {!r} -> {!r}".format(
                        f.key, variants[0], v))
                placed = True
                break
        if not placed:
            dropped.append(f.key)

    # A very short line identifies nothing. When facts ran out but budget did
    # not, the part number is the most identifying thing left -- a till line
    # reading "DRILL" tells a picker less than "DRILL DCD799B".
    #
    # The threshold is deliberately low. The published rows never put a model
    # number on this line, so the fallback is for lines that would otherwise
    # be uninformative, not a licence to pad every one.
    if len(" ".join(chosen)) < 13:
        mpn = graph.get("mpn")
        if mpn and str(mpn.value):
            cand = chosen + [str(mpn.value).upper()]
            if len(" ".join(cand)) <= limit:
                chosen = cand
                included.append("mpn")

    text = " ".join(chosen)[:limit].strip()
    return BudgetResult(text=text, included=included, dropped=dropped,
                        used=len(text), limit=limit, compressions=compressions)


# ---------------------------------------------------------------------------
# The other four formats.
# ---------------------------------------------------------------------------
def _bare(text: str) -> str:
    """Brand without its registration symbol, for fields that omit it."""
    return re.sub(r"[®™]", "", str(text or "")).strip()


def _shares_root(a: str, b: str) -> bool:
    """True when a manufacturer name is just the brand plus a legal suffix."""
    ra = re.sub(r"[^a-z0-9]", "", _bare(a).lower())
    rb = re.sub(r"[^a-z0-9]", "", _bare(b).lower())
    if not ra or not rb:
        return False
    return ra.startswith(rb) or rb.startswith(ra)


def _parts(graph: ProductFactGraph, keys: Sequence[str]) -> List[str]:
    out = []
    for k in keys:
        f = graph.get(k)
        if f and f.display:
            out.append(f.display)
    return out


def build_mobile_desc(graph: ProductFactGraph, lo: int = 60, hi: int = 80,
                      report: Optional[Dict[str, Any]] = None) -> str:
    """Comma-delimited identity line sized into a 60-80 character window.

    When the line falls short of ``lo`` it matters *why*. A row with facts left
    over is a composition failure; a row that has spent every fact it owns is
    a data limit, and no amount of rule-writing closes it -- only more source
    material would. ``report`` receives that distinction so the metrics can
    separate the two instead of counting both as non-compliance.
    """
    # The published rows write this line without the (R)/(TM) symbol, unlike
    # the title, and they never repeat a manufacturer that is just the brand's
    # legal name: "Rheem Manufacturing FRIGIDAIRE" keeps both because the two
    # are different companies, while Whirlpool Corporation's Whirlpool line is
    # written once.
    brand = _bare(graph.value("brand"))
    manu = _bare(graph.value("manufacturer"))
    core = [graph.value("item_type"), graph.value("series"), graph.value("mpn")]

    def assemble(with_manu: bool) -> str:
        head = [p for p in ((manu if with_manu else ""), brand) if p]
        bits = ([" ".join(head)] if head else []) + [c for c in core if c]
        return ", ".join(bits)

    # Prefer the concise form when the manufacturer is only the brand's legal
    # name -- the published rows write Whirlpool Corporation's line as
    # "Whirlpool". But the manufacturer is still a true fact, and gold row 1
    # ("Rheem Manufacturing FRIGIDAIRE") keeps it, so the fuller form is used
    # when the concise one cannot reach the window on its own.
    text = assemble(with_manu=True)
    if manu and brand and _shares_root(manu, brand):
        concise = assemble(with_manu=False)
        if len(concise) >= lo or len(text) > hi:
            text = concise

    if len(text) < lo:
        # Grow with the next most identifying facts until inside the window.
        for f in graph.ordered():
            if f.key in SKIP_IN_MOBILE:
                continue
            if not f.display:
                continue
            cand = text + ", " + f.display
            if len(cand) > hi:
                continue
            text = cand
            if len(text) >= lo:
                break
    if len(text) > hi:
        while len(text) > hi and "," in text:
            text = text.rsplit(",", 1)[0].strip()
        text = text[:hi].rstrip(" ,")

    if report is not None:
        unused = [f.key for f in graph.ordered()
                  if f.display and f.key not in SKIP_IN_MOBILE
                  and f.display not in text]
        report["length"] = len(text)
        report["in_window"] = lo <= len(text) <= hi
        report["short"] = len(text) < lo
        report["facts_exhausted"] = not unused
        report["unused"] = unused
    return text


def _with_clause(graph: ProductFactGraph) -> str:
    f = graph.get("with_feature")
    return f.display if f else ""


def _dedupe_words(text: str) -> str:
    """Drop a word the line has already used.

    Series and item type are detected separately and can share a word --
    "Trex Alum Post Sleeve Select Alum ... Railing" says Alum twice. The first
    occurrence is kept; later ones are dropped, and punctuation is tidied.
    """
    seen, out = set(), []
    for word in text.split():
        key = re.sub(r"[^a-z0-9]", "", word.lower())
        if key and len(key) > 2 and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(word)
    return re.sub(r"\s+,", ",", " ".join(out)).strip(" ,")


def build_short_desc(graph: ProductFactGraph, spec_keys: Sequence[str] = ()) -> str:
    """Product title: Brand + Series + MPN + Item Type + differentiators."""
    lead = [p for p in (graph.value("brand"), graph.value("series"),
                        graph.value("mpn"), graph.value("item_type")) if p]
    title = _dedupe_words(" ".join(lead))
    with_c = _with_clause(graph)
    if with_c:
        title += " {}".format(with_c)
    diffs = _differentiators(graph, spec_keys, limit=4)
    if diffs:
        title += ", " + ", ".join(diffs)
    return title.strip()


def build_retail_desc(graph: ProductFactGraph, spec_keys: Sequence[str] = ()) -> str:
    """Shelf line: series + item type + differentiators. No brand, no model."""
    lead = [p for p in (graph.value("series"), graph.value("item_type")) if p]
    text = " ".join(lead)
    diffs = _differentiators(graph, spec_keys, limit=4)
    if diffs:
        text += ", " + ", ".join(diffs)
    return text.strip()


def build_long_desc(graph: ProductFactGraph, spec_keys: Sequence[str] = ()) -> str:
    """Product-page description: identity, then every captured attribute in
    specification order, then anything that did not earn its own column."""
    lead = [p for p in (graph.value("brand"), graph.value("item_type")) if p]
    text = " ".join(lead)
    with_c = _with_clause(graph)
    if with_c:
        text += " {}".format(with_c)

    redundant = _suppress_redundant(graph)
    body: List[str] = []
    series = graph.value("series")
    if series:
        body.append(series)
    for f in _spec_ordered(graph, spec_keys):
        if (f.key in ("brand", "manufacturer", "item_type", "series", "mpn",
                      "classpath", "dept", "class", "fine", "unspsc",
                      "with_feature")
                or f.key in BOOLEAN_KEYS or f.key in redundant):
            continue
        if f.display:
            body.append(f.display)
    if body:
        text += ", " + ", ".join(body)

    extra = graph.get("additional_information")
    if extra and extra.display:
        text += ", Additional Information: {}".format(extra.display)
    return text.strip()


def build_product_name(graph: ProductFactGraph) -> str:
    """Bare item type -- no brand, no model, no attributes."""
    return graph.value("item_type")


def _spec_ordered(graph: ProductFactGraph, spec_keys: Sequence[str]) -> List[Fact]:
    if spec_keys:
        ordered = graph.ordered(spec_keys)
        rest = [f for f in graph.ordered() if f.key not in set(spec_keys)]
        return ordered + rest
    return graph.ordered()


def _differentiators(graph: ProductFactGraph, spec_keys: Sequence[str],
                     limit: int = 4) -> List[str]:
    """The attributes a buyer chooses between, in specification order."""
    skip = ({"brand", "manufacturer", "item_type", "series", "mpn", "classpath",
             "dept", "class", "fine", "unspsc", "with_feature",
             "additional_information"} | set(BOOLEAN_KEYS)
            | set(_suppress_redundant(graph)))
    out = []
    for f in _spec_ordered(graph, spec_keys):
        if f.key in skip or not f.display:
            continue
        out.append(f.display)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Casing helpers
# ---------------------------------------------------------------------------
def enforce_casing(text: str, casing: str) -> str:
    if casing == "upper":
        return text.upper()
    if casing == "sentence" and text:
        return text[0].upper() + text[1:]
    return text


def clip(text: str, limit: Optional[int]) -> str:
    if limit is None or len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut[int(limit * 0.6):]:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;-")
