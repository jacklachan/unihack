"""Deterministic extraction from raw supplier descriptions.

Everything in here is a named rule that produces a :class:`Fact` with a real
character span into the source string. Rules never guess: if a pattern does not
match, no fact is written and the field stays empty for a later stage (LLM,
document, family consensus) to attempt -- or to be reported as a gap.

Patterns were derived from the actual 1,000-row sample: abrasive dimension
chains (``14"x1/8"x1"``), decking nominals (``7/8nx6-20'``), lamp shorthand
(``60W Led BA11 50k 3pk``), appliance finish codes (``SS``/``BSS``/``Wh``) and
so on.
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple

from .facts import Evidence, Fact

# ---------------------------------------------------------------------------
# Decimal <-> fraction. Reproduces Decimal_Fraction.xlsx (1/64 .. 63/64) plus
# the coarser trade fractions, generated rather than transcribed.
# ---------------------------------------------------------------------------
DECIMAL_TO_FRACTION: Dict[str, str] = {}
for _d in (2, 4, 8, 16, 32, 64):
    for _n in range(1, _d):
        _f = Fraction(_n, _d)
        if _f.denominator != _d:
            continue  # keep the lowest-terms form only
        DECIMAL_TO_FRACTION["{:.6f}".format(float(_f)).rstrip("0")] = "{}/{}".format(
            _f.numerator, _f.denominator)


def decimal_to_fraction(text: str) -> Optional[str]:
    """``0.5`` -> ``1/2``; ``50.25`` -> ``50-1/4``. None when not an exact
    64th, because inventing a fraction is worse than leaving the decimal."""
    try:
        val = float(text)
    except (TypeError, ValueError):
        return None
    whole = int(abs(val))
    frac = round(abs(val) - whole, 6)
    if frac == 0:
        return str(int(val))
    key = "{:.6f}".format(frac).rstrip("0")
    name = DECIMAL_TO_FRACTION.get(key)
    if not name:
        return None
    sign = "-" if val < 0 else ""
    return "{}{}-{}".format(sign, whole, name) if whole else "{}{}".format(sign, name)


def normalise_measure(text: str) -> str:
    """Tidy a single measurement token: strip quotes, prefer trade fractions."""
    t = text.strip().strip('"').strip("'").strip()
    t = t.replace("''", "")
    if re.fullmatch(r"\.\d+", t):          # ".045" -> "0.045"
        t = "0" + t
    if re.fullmatch(r"\d*\.\d+", t):
        frac = decimal_to_fraction(t)
        if frac:
            return frac
    return t


# ---------------------------------------------------------------------------
# Trade abbreviation lexicon. Seeded from the corpus; the induction stage
# extends it and keeps only entries that measurably improve accuracy.
# ---------------------------------------------------------------------------
ABBREVIATIONS: Dict[str, str] = {
    "lt": "Light", "lts": "Lights", "lgt": "Light",
    "elect": "Electric", "elec": "Electric", "electr": "Electric",
    "ext": "Exterior", "int": "Interior",
    "milw": "Milwaukee", "sq": "Speed Queen", "dewalt": "DEWALT",
    "fridge": "Refrigerator", "refrig": "Refrigerator", "dishw": "Dishwasher",
    "wshr": "Washer", "dryr": "Dryer",
    "sst": "Stainless Steel", "ss": "Stainless Steel",
    "bss": "Black Stainless Steel", "bo": "Black",
    "wh": "White", "wht": "White", "bk": "Black", "blk": "Black",
    "clr": "Clear", "brz": "Bronze", "nkl": "Nickel", "chr": "Chrome",
    "brs": "Brass", "alum": "Aluminum", "galv": "Galvanized",
    "cplg": "Coupling", "nip": "Nipple", "elb": "Elbow", "tee": "Tee",
    "bltln": "Built-in", "bltin": "Built-in",
    "sq edg": "Square Edge", "sq edge": "Square Edge", "grvd": "Grooved",
    "ud": "Underground", "thhn": "THHN", "romex": "NM-B",
    "pk": "Pack", "pc": "Piece", "ea": "Each", "bx": "Box",
    "cd": "Cord", "hd": "Head", "adj": "Adjustable",
    "med": "Medium Base", "cand": "Candelabra Base",
    "ph": "Phase", "hp": "Horsepower",
    "mtr": "Motor", "gal": "Gallon", "qt": "Quart",
    "cmpt": "Compact", "std": "Standard", "hvy": "Heavy Duty",
    "assy": "Assembly", "brkt": "Bracket", "conn": "Connector",
    "recept": "Receptacle", "swt": "Switch", "gfci": "GFCI",
    "pnl": "Panel", "encl": "Enclosure",
}

#: Reverse ladder used by the invoice-line char budget: long form -> shorter
#: approved forms, best first.
ABBREV_LADDER: Dict[str, List[str]] = {
    "stainless steel": ["STAINLESS", "SST", "SS"],
    "black stainless steel": ["BLK STAINLESS", "BSST", "BSS"],
    "built-in": ["BLT-IN", "BLTLN", "BLTN"],
    "refrigerator": ["REFRIG", "FRIDGE", "REF"],
    "dishwasher": ["DISHWSHR", "DISHW", "DW"],
    "underground": ["UNDRGRND", "UGND", "UD"],
    "adjustable": ["ADJUST", "ADJ"],
    "horsepower": ["HP"],
    "medium base": ["MED BASE", "MED"],
    "candelabra base": ["CAND BASE", "CAND"],
    "square edge": ["SQ EDGE", "SQ EDG", "SQE"],
    "aluminum": ["ALUM", "AL"],
    "galvanized": ["GALV", "GV"],
    "white": ["WHT", "WH"],
    "black": ["BLK", "BK"],
    "bronze": ["BRZ"],
    "nickel": ["NKL"],
    "grooved": ["GRVD", "GRV"],
}


def expand_abbreviations(text: str) -> str:
    """Expand known trade shorthand, preserving unknown tokens untouched."""
    def sub(m: "re.Match[str]") -> str:
        tok = m.group(0)
        rep = ABBREVIATIONS.get(tok.lower())
        return rep if rep else tok
    return re.sub(r"\b[A-Za-z][A-Za-z\-]{0,7}\b", sub, text)


# ---------------------------------------------------------------------------
# Rule table. Each entry: (rule_id, key, label, uom, priority, pattern, handler)
# ---------------------------------------------------------------------------
# Longest-first alternation: without this, "1/8" loses to a bare "1" and the
# whole dimension chain silently truncates.
_DIM_TOKEN = r"(?:\d+\s*-\s*\d+\s*/\s*\d+|\d+\s*/\s*\d+|\d+\.\d+|\.\d+|\d+)"
# The mark is captured, not skipped: a chain can mix units ("1.5x1.5x13'" is
# two inch dimensions and a foot length) and the tick is the only signal.
_DIM_MARK = r"(\"|''|in\.?|inch(?:es)?|'|ft\.?)?"

RE_DIM_CHAIN = re.compile(
    r"(?<![\w/.])(" + _DIM_TOKEN + r")\s*" + _DIM_MARK + r"[nN]?\s*[xX]\s*"
    r"(" + _DIM_TOKEN + r")\s*" + _DIM_MARK +
    r"(?:\s*[xX]\s*(" + _DIM_TOKEN + r")\s*" + _DIM_MARK + r")?",
    re.I,
)

#: A three-part inch chain only means diameter/thickness/arbor on a bonded
#: abrasive. On tape or lumber it means something else entirely, so the
#: component split is gated on the item words rather than applied blindly.
RE_ABRASIVE_CTX = re.compile(
    r"\b(disc|disk|wheel|blade|belt|sanding|grinding|cut\s*-?\s*off|cutoff|abrasive)\b", re.I)


def _mark_to_uom(mark: Optional[str]) -> str:
    if not mark:
        return ""
    m = mark.strip().lower()
    if m in ("'", "ft", "ft."):
        return "ft"
    return "in"
RE_NOMINAL_LEN = re.compile(r"(?<![\w.])(\d+(?:/\d+)?)[nN]?\s*[xX]\s*(\d+)\s*-\s*(\d+)\s*'")
# "12V/20V" (unit repeated) and "12/20V" (unit once) are both common.
RE_VOLTAGE_DUAL = re.compile(r"(?<![\w.])(\d{1,3})\s*[vV]\s*/\s*(\d{1,3})\s*[vV](?![\w])")
RE_VOLTAGE = re.compile(r"(?<![\w.])(\d{1,3}(?:\s*/\s*\d{1,3})?)\s*[vV](?![\w])")
RE_AMPERAGE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:[aA](?![\w])|[aA]mps?\b)")
RE_WATTAGE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*[wW](?![\w])")
RE_KELVIN = re.compile(r"(?<![\w.])(\d{2,4})\s*[kK](?![\w])")
RE_PACK = re.compile(r"(?<![\w.])(\d+)\s*(?:pk|pc|pcs|pack|ct)\b", re.I)
RE_PER_BOX = re.compile(r"(?<![\w.])(\d+)\s+(\w+)\s*/\s*(box|bx|case|cs|pk)\b", re.I)
RE_GRIT = re.compile(r"\b[pP](\d{2,4})\b(?!\w)")
RE_GRIT_WORD = re.compile(r"(?<![\w.])(\d{2,4})\s*(?:grit|grt)\b", re.I)
RE_HP = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:HP|H\.P\.)\b", re.I)
RE_PHASE = re.compile(r"(?<![\w.])(\d)\s*(?:PH|PHASE)\b", re.I)
RE_BULB_SHAPE = re.compile(r"\b(A\d{2}|BA\d{2}|PAR\d{2}|BR\d{2}|MR\d{2}|T\d{1,2}|G\d{2}|CA\d{2})\b", re.I)
RE_BASE_TYPE = re.compile(r"\b(Med|Medium|Cand|Candelabra|GU10|GU24|E26|E12|E39)\b", re.I)
RE_GAUGE = re.compile(r"(?<![\w.])(\d{1,2})\s*[/-]\s*(\d)\s+(SO|SOOW|SJ|UD|THHN|MC|NM|SER|SEU)\b", re.I)
RE_TRIPLEX = re.compile(r"(?<![\w.])(\d{1,2}(?:/\d{1,2}){2})\s+(UD|SE|SER|SEU|MC)\b", re.I)
RE_DISPLAY_ONLY = re.compile(r"\bdisplay\s*only\b", re.I)
RE_LINEAR_FOOT = re.compile(r"\(?\s*linear\s*(?:foot|ft)\s*\)?", re.I)
# A lone measurement that is not part of an x-chain: '52" MB Anisten Fan'.
RE_SINGLE_DIM = re.compile(
    r"(?<![\w/.x])(" + _DIM_TOKEN + r")\s*(\"|''|in\.?|inch(?:es)?|'|ft\.?)(?![\w])", re.I)
RE_GAUGE_WIRE = re.compile(r"(?<![\w.])(\d{1,2})\s*(?:GA|GAUGE)\b", re.I)
RE_LUMENS = re.compile(r"(?<![\w.])(\d{2,6})\s*L(?:M|UMENS?)?\b(?![\w])")
RE_PLATFORM = re.compile(
    r"\b(M12|M18|MX\s?FUEL|FLEXVOLT|XR|ATOMIC|20V\s?MAX|18V|12V\s?MAX|"
    r"ONE\+|POWERSTACK|CXT|LXT|XGT)\b", re.I)
RE_THOUSAND_CT = re.compile(r"(?<![\w.])(\d{1,3})\s*M\b(?!\w)")
RE_BARE_TOOL = re.compile(r"\((?:bare|tool\s*only|bare\s*tool)\)", re.I)

FINISH_CODES: Dict[str, str] = {
    "sst": "Stainless Steel", "ss": "Stainless Steel",
    "bss": "Black Stainless Steel", "bstl": "Black Stainless Steel",
    "wh": "White", "wht": "White", "bk": "Black", "blk": "Black",
    "bo": "Black", "clr": "Clear", "chr": "Chrome", "brz": "Bronze",
    "nkl": "Brushed Nickel", "cu": "Copper", "gld": "Gold",
    "bsl": "Brushed Silver", "bkclr": "Black/Clear",
}
RE_FINISH = re.compile(
    r"\b(" + "|".join(sorted(FINISH_CODES, key=len, reverse=True)) + r")\b", re.I)
RE_FINISH_WORD = re.compile(
    r"\b(Stainless\s+Steel|Black\s+Stainless|White|Black|Bronze|Chrome|Brass|"
    r"Nickel|Copper|Clear|Almond|Bisque|Slate|Graphite)\b", re.I)


def _ev(source: str, text: str, span: Tuple[int, int], detail: str) -> List[Evidence]:
    return [Evidence(source=source, text=text, span=span, detail=detail)]


def _mk(key: str, value: Any, label: str, uom: str, rule_id: str, priority: int,
        source: str, raw: str, span: Tuple[int, int], detail: str,
        method: str = "rule") -> Fact:
    return Fact(key=key, value=value, label=label, uom=uom, method=method,
                rule_id=rule_id, raw=raw, priority=priority,
                evidence=_ev(source, raw, span, detail))


def strip_mpn_echo(desc: str, mpn: str) -> Tuple[str, Optional[Tuple[int, int]]]:
    """Most supplier descriptions repeat the part number as a prefix.

    Returns the description with the echo removed plus the span it occupied, so
    the MPN fact can still cite where it was seen.
    """
    if not mpn:
        return desc, None
    pat = re.compile(r"^\s*" + re.escape(mpn) + r"\s*[-:]?\s*", re.I)
    m = pat.match(desc)
    if m:
        return desc[m.end():].strip(), (m.start(), m.end())
    loose = re.compile(r"\b" + re.escape(mpn) + r"\b", re.I)
    m2 = loose.search(desc)
    if m2:
        return (desc[:m2.start()] + " " + desc[m2.end():]).strip(), (m2.start(), m2.end())
    return desc, None


def parse_description(desc: str, source: str = "input:Part_Desc") -> List[Fact]:
    """Run every deterministic rule over one description string."""
    facts: List[Fact] = []
    if not desc:
        return facts
    add = facts.append

    # -- dimension chains ---------------------------------------------------
    m = RE_NOMINAL_LEN.search(desc)
    if m:
        thick, width, length = m.group(1), m.group(2), m.group(3)
        add(_mk("nominal_size", "{} in x {} in".format(normalise_measure(thick), width),
                "Nominal Size", "", "DIM-NOM-01", 20, source, m.group(0), m.span(),
                "Decking nominal profile: thickness x width, length carried separately."))
        add(_mk("length", length, "Length", "ft", "DIM-LEN-01", 22, source,
                m.group(0), m.span(), "Board length in feet from the '-NN'' suffix."))
    else:
        m = RE_DIM_CHAIN.search(desc)
        if m:
            g = m.groups()
            pairs = [(normalise_measure(g[i]), _mark_to_uom(g[i + 1]))
                     for i in (0, 2, 4) if g[i]]
            # Unmarked tokens default to inches rather than inheriting a
            # neighbour's mark -- "1.5x1.5x13'" is two inch dimensions and a
            # foot length, not three foot dimensions.
            pairs = [(v, u or "in") for v, u in pairs]
            if len(pairs) >= 2:
                add(_mk("dimensions",
                        " x ".join("{} {}".format(v, u) for v, u in pairs),
                        "Size", "", "DIM-CHN-01", 20, source, m.group(0), m.span(),
                        "Dimension chain; decimals converted to trade fractions, "
                        "unit taken per token from the tick mark."))
                if len(pairs) == 3 and RE_ABRASIVE_CTX.search(desc) \
                        and all(u == "in" for _, u in pairs):
                    for key, disp, (val, uom) in zip(
                            ("diameter", "thickness", "arbor_size"),
                            ("Diameter", "Thickness", "Arbor Size"), pairs):
                        add(_mk(key, val, disp, uom, "DIM-CHN-02", 30, source,
                                m.group(0), m.span(),
                                "Positional component of a bonded-abrasive "
                                "diameter x thickness x arbor chain."))

    # -- electrical ---------------------------------------------------------
    mm = RE_VOLTAGE_DUAL.search(desc)
    if mm:
        add(_mk("voltage", "{}/{}".format(mm.group(1), mm.group(2)),
                "Voltage Rating", "V", "ELE-V-02", 25, source, mm.group(0),
                mm.span(), "Dual-voltage platform tool (e.g. 12V/20V)."))

    for rx, key, label, uom, rid, prio, note in (
        (RE_VOLTAGE, "voltage", "Voltage Rating", "V", "ELE-V-01", 25,
         "Voltage token; dual ratings kept as '12/20'."),
        (RE_AMPERAGE, "amperage", "Amperage Rating", "A", "ELE-A-01", 26,
         "Amperage token."),
        (RE_WATTAGE, "wattage", "Wattage", "W", "ELE-W-01", 24, "Wattage token."),
        (RE_HP, "horsepower", "Horsepower", "HP", "ELE-HP-01", 27, "Motor rating."),
        (RE_PHASE, "phase", "Phase", "PH", "ELE-PH-01", 34, "Electrical phase."),
    ):
        if any(f.key == key for f in facts):
            continue  # a more specific rule already claimed this key
        mm = rx.search(desc)
        if mm:
            add(_mk(key, re.sub(r"\s+", "", mm.group(1)), label, uom, rid, prio,
                    source, mm.group(0), mm.span(), note))

    # -- colour temperature: trade shorthand 50k == 5000 K ------------------
    mm = RE_KELVIN.search(desc)
    if mm:
        n = int(mm.group(1))
        kelvin = n * 100 if n < 100 else n
        add(_mk("color_temperature", kelvin, "Color Temperature", "K",
                "LMP-K-01", 28, source, mm.group(0), mm.span(),
                "Lamp shorthand: two-digit K value means hundreds (50k = 5000 K)."))

    for rx, key, label, rid, prio, note in (
        (RE_BULB_SHAPE, "bulb_shape", "Bulb Shape", "LMP-SHP-01", 30,
         "ANSI lamp shape designation."),
        (RE_BASE_TYPE, "base_type", "Base Type", "LMP-BAS-01", 31,
         "Lamp base designation."),
    ):
        mm = rx.search(desc)
        if mm:
            val = mm.group(1)
            if key == "base_type":
                val = ABBREVIATIONS.get(val.lower(), val).title() \
                    if val.lower() in ("med", "cand") else val.upper()
            add(_mk(key, val.upper() if key == "bulb_shape" else val, label, "",
                    rid, prio, source, mm.group(0), mm.span(), note))

    # -- abrasives ----------------------------------------------------------
    for rx, note in ((RE_GRIT, "P-graded abrasive grit."),
                     (RE_GRIT_WORD, "Grit stated in words.")):
        mm = rx.search(desc)
        if mm:
            add(_mk("grit", mm.group(1), "Grit", "", "ABR-GRT-01", 29,
                    source, mm.group(0), mm.span(), note))
            break

    # -- packaging ----------------------------------------------------------
    mm = RE_PER_BOX.search(desc)
    if mm:
        add(_mk("selling_qty", mm.group(1), "Selling Qty", "", "PKG-QTY-01", 40,
                source, mm.group(0), mm.span(), "Count per selling unit."))
        add(_mk("selling_uom", mm.group(3).upper(), "Selling UOM", "",
                "PKG-UOM-01", 41, source, mm.group(0), mm.span(),
                "Selling unit of measure."))
    else:
        mm = RE_PACK.search(desc)
        if mm:
            add(_mk("pack_quantity", mm.group(1), "Pack Quantity", "",
                    "PKG-PK-01", 40, source, mm.group(0), mm.span(),
                    "Multi-pack count."))

    if RE_LINEAR_FOOT.search(desc):
        mm = RE_LINEAR_FOOT.search(desc)
        add(_mk("selling_uom", "FT", "Selling UOM", "", "PKG-LF-01", 41,
                source, mm.group(0), mm.span(), "Sold by the linear foot."))

    # -- wire ---------------------------------------------------------------
    mm = RE_TRIPLEX.search(desc) or RE_GAUGE.search(desc)
    if mm:
        add(_mk("conductor_config", mm.group(1), "Conductor Configuration", "",
                "WIR-CFG-01", 23, source, mm.group(0), mm.span(),
                "Gauge / conductor-count configuration."))
        add(_mk("cable_type", mm.group(len(mm.groups())).upper(), "Cable Type", "",
                "WIR-TYP-01", 24, source, mm.group(0), mm.span(),
                "Cable construction designation."))

    # -- finish / colour ----------------------------------------------------
    mm = RE_FINISH_WORD.search(desc)
    if mm:
        add(_mk("finish", mm.group(1).title(), "Color", "", "FIN-WRD-01", 35,
                source, mm.group(0), mm.span(), "Finish stated in full words."))
    else:
        mm = RE_FINISH.search(desc)
        if mm:
            add(_mk("finish", FINISH_CODES[mm.group(1).lower()], "Color", "",
                    "FIN-CDE-01", 35, source, mm.group(0), mm.span(),
                    "Trade finish code expanded via the approved abbreviation map."))

    # -- battery platform / tool family ------------------------------------
    mm = RE_PLATFORM.search(desc)
    if mm:
        add(_mk("platform", re.sub(r"\s+", " ", mm.group(1)).upper(),
                "Battery Platform", "", "TOL-PLT-01", 26, source, mm.group(0),
                mm.span(), "Cordless battery platform; drives accessory compatibility."))
    if RE_BARE_TOOL.search(desc):
        mm2 = RE_BARE_TOOL.search(desc)
        add(_mk("includes_battery", "No", "Battery Included", "", "TOL-BAR-01", 45,
                source, mm2.group(0), mm2.span(), "Marked bare / tool-only."))

    # -- standalone measurement, gauge, lumens ------------------------------
    if not any(f.key in ("dimensions", "nominal_size") for f in facts):
        mm = RE_SINGLE_DIM.search(desc)
        if mm:
            add(_mk("size", normalise_measure(mm.group(1)), "Size",
                    _mark_to_uom(mm.group(2)), "DIM-SGL-01", 21, source,
                    mm.group(0), mm.span(),
                    "Single stated dimension (nominal size of the item)."))

    mm = RE_GAUGE_WIRE.search(desc)
    if mm:
        add(_mk("gauge", mm.group(1), "Gauge", "GA", "DIM-GA-01", 29, source,
                mm.group(0), mm.span(), "Wire / fastener gauge."))

    mm = RE_LUMENS.search(desc)
    if mm and int(mm.group(1)) >= 100:
        add(_mk("lumens", mm.group(1), "Light Output", "lm", "LMP-LM-01", 27,
                source, mm.group(0), mm.span(), "Rated light output."))

    if not any(f.key in ("pack_quantity", "selling_qty") for f in facts):
        mm = RE_THOUSAND_CT.search(desc)
        if mm:
            add(_mk("pack_quantity", str(int(mm.group(1)) * 1000), "Pack Quantity",
                    "", "PKG-M-01", 40, source, mm.group(0), mm.span(),
                    "Fastener trade shorthand: '4M' means 4,000 count."))

    # -- merchandising flags ------------------------------------------------
    mm = RE_DISPLAY_ONLY.search(desc)
    if mm:
        add(_mk("display_only", "Yes", "Display Only", "", "MRC-DSP-01", 60,
                source, mm.group(0), mm.span(),
                "Showroom display unit; not stocked for shipment."))

    return facts


def consumed_spans(facts: List[Fact]) -> List[Tuple[int, int]]:
    spans = []
    for f in facts:
        for e in f.evidence:
            if e.span:
                spans.append(tuple(e.span))
    return sorted(set(spans))


def residual_text(desc: str, facts: List[Fact]) -> str:
    """Text no rule claimed -- the candidate pool for item type, series and
    the LLM stage. Keeping this explicit is what stops the model re-deriving
    facts the rules already own."""
    spans = consumed_spans(facts)
    out, cursor = [], 0
    for s, e in spans:
        if s >= cursor:
            out.append(desc[cursor:s])
            cursor = e
    out.append(desc[cursor:])
    txt = " ".join(out)
    txt = re.sub(r"\s*[-|,/]\s*", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()
