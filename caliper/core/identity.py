"""Manufacturer and brand resolution.

Three problems have to be solved together, and the sample data contains all
three in its first few rows:

1. **Messy supplier strings.** ``Phillips Lighting (5831)`` is a misspelling
   plus a category word plus an ERP code. The approved value is ``Philips``.

2. **The supplier is often not the manufacturer.** ``Appliance Dealers
   Cooperative (APPDE)`` is a buying co-op; ``Boise Cascade Building
   Materials`` and ``Parksite`` are distributors. For those rows the real brand
   has to be recovered from the description or the part-number prefix. This is
   exactly what the published ground truth does: ``Part_Manuf`` is the co-op,
   while ``BRAND_NAME`` is ``FRIGIDAIRE(R)``.

3. **Brand and manufacturer can legitimately differ, or be wrong.** The
   ground-truth dishwasher row pairs ``FRIGIDAIRE(R)`` with ``Rheem
   Manufacturing`` -- a real mismatch in the client's own data. We detect and
   report it rather than silently propagating it.

If the official ``UniCat_Manufacturer_and_Brand_List`` is present it is loaded
and takes precedence over everything here. The bootstrap registry exists so the
pipeline runs, and degrades honestly, without it.
"""
from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .facts import Evidence, Fact

# ---------------------------------------------------------------------------
# Bootstrap registry: canonical name, symbol, and the aliases actually seen in
# this catalogue. Replaced wholesale by the official master list when present.
# ---------------------------------------------------------------------------
@dataclass
class BrandEntry:
    brand: str                       # canonical brand, exact casing
    manufacturer: str = ""           # legal manufacturer entity
    symbol: str = ""                 # (R) / (TM) as published
    aliases: Tuple[str, ...] = ()
    mpn_prefixes: Tuple[str, ...] = ()
    source: str = "bootstrap"

    @property
    def display(self) -> str:
        return "{}{}".format(self.brand, self.symbol)


_B = BrandEntry
BOOTSTRAP_BRANDS: Tuple[BrandEntry, ...] = (
    _B("Philips", "Signify Holding", "®", ("phillips", "phillips lighting", "philips lighting")),
    _B("Milwaukee", "Milwaukee Tool", "®", ("milw", "milwaukee accessory", "milwaukee tool"),
       ("48-", "49-", "2", "48")),
    _B("DEWALT", "Stanley Black & Decker", "®",
       ("dewalt", "dewlt", "black & decker/dewlt", "black and decker"),
       ("DCB", "DCD", "DCF", "DCS", "DCG", "DWA", "DW")),
    _B("Diablo", "Freud America, Inc.", "®", ("diablo", "freud", "freud inc")),
    _B("Freud", "Freud America, Inc.", "®", ("freud inc",)),
    _B("Leviton", "Leviton Manufacturing Co., Inc.", "®", ("leviton mfg co", "leviton mfg")),
    _B("Satco", "Satco Products, Inc.", "®", ("satco prod inc", "satco products")),
    _B("Southwire", "Southwire Company, LLC", "®", ("southwire/g turner", "woods wire southwire")),
    _B("Square D", "Schneider Electric", "®", ("square d con prod dv", "squared"), ("HOM", "QO")),
    _B("Kichler", "Kichler Lighting LLC", "®", ("kichler lighting",)),
    _B("Makita", "Makita U.S.A., Inc.", "®", ("makita usa inc",)),
    _B("Festool", "Festool GmbH", "®", ("festool usa",)),
    _B("Trex", "Trex Company, Inc.", "®", ("trex company",)),
    _B("AZEK", "The AZEK Company", "®", ("azek", "azek pvc")),
    _B("TimberTech", "The AZEK Company", "®", ("timbertech",)),
    _B("HardiePanel", "James Hardie Building Products", "®", ("hardiepanel", "hardie", "hardieplank")),
    _B("LP SmartSide", "Louisiana-Pacific Corporation", "®", ("lp smartside", "lp")),
    _B("Whirlpool", "Whirlpool Corporation", "®", ("whirlpool",), ("WDT", "WRF", "WTW", "WED")),
    _B("FRIGIDAIRE", "Electrolux Home Products", "®", ("frigidaire",),
       ("PDSH", "PCFE", "FFSS", "GRSS", "FGHD")),
    _B("Speed Queen", "Alliance Laundry Systems", "®", ("speed queen", "sq"),
       ("TV", "TR", "DC", "DF", "AWN")),
    _B("LG", "LG Electronics", "®", ("lg electronics",), ("LDPH", "LRFD", "WM", "DLE")),
    _B("KitchenAid", "Whirlpool Corporation", "®", ("kitchenaid", "kitchen aid"),
       ("KDFM", "KDTM", "KSES", "KDTS", "KDPS", "KDPM", "KRFF", "KSGB", "KMBP")),
    _B("GE", "GE Appliances", "®", ("ge appliances", "general electric"),
       ("PDT", "PDD", "GDT", "GTW", "GFW", "JB", "JGB")),
    _B("Maytag", "Whirlpool Corporation", "®", ("maytag",), ("MVW", "MED", "MDB")),
    _B("Amana", "Whirlpool Corporation", "®", ("amana",), ("ADB", "NTW", "AER")),
    _B("Café", "GE Appliances", "®", ("cafe appliances",)),
    _B("Element", "Element Electronics", "", ("element",), ("ERFD",)),
    _B("Hunter", "Hunter Fan Company", "®", ("hunter fan co", "hunter fan")),
    _B("Bosch", "Robert Bosch Tool Corporation", "®", ("robt bosch tool corp", "bosch tool")),
    _B("Senco", "Kyocera Senco Industrial Tools", "®", ("senco products inc",)),
    _B("Paslode", "Illinois Tool Works Inc.", "®", ("paslode",)),
    _B("SawStop", "SawStop, LLC", "®", ("saw stop llc", "sawstop")),
    _B("Grizzly", "Grizzly Industrial, Inc.", "®", ("grizzly",)),
    _B("Woodstock", "Woodstock International, Inc.", "®", ("woodstock intl",)),
    _B("JET", "JPW Industries, Inc.", "®", ("jpw industries", "jet tools"), ("JT1", "JWBS")),
    _B("Powermatic", "JPW Industries, Inc.", "®", ("powermatic",)),
    _B("Kreg", "Kreg Tool Company", "®", ("kreg tool company",)),
    _B("Irwin", "Irwin Industrial Tools", "®", ("irwin industrial tools",)),
    _B("3M", "3M Company", "™", ("3 m co", "3m", "3mabr")),
    _B("Mirka", "Mirka Ltd.", "®", ("mirka abrasives inc",)),
    _B("Marshalltown", "Marshalltown Company", "®", ("marshalltown trowel",)),
    _B("Malco", "Malco Products, SBC", "®", ("malco prod",)),
    _B("First Alert", "Resideo Technologies, Inc.", "®", ("first alert - b r k brands", "brk")),
    _B("Feit Electric", "Feit Electric Company, Inc.", "®", ("feit electric",)),
    _B("Lithonia Lighting", "Acuity Brands Lighting, Inc.", "®", ("lithonia lighting", "lithonia")),
    _B("Cooper Lighting", "Signify Holding", "®", ("cooper lighting", "cooper wiring devices")),
    _B("Keystone", "Keystone Technologies", "®", ("keystone",)),
    _B("Streamlight", "Streamlight, Inc.", "®", ("streamlight",)),
    _B("Radians", "Radians, Inc.", "®", ("radians",)),
    _B("Amana Tool", "Amana Tool Corporation", "®", ("amana tool corp",)),
    _B("CMT", "CMT Utensili S.p.A.", "®", ("cmt usa inc",)),
    _B("Whiteside", "Whiteside Machine Company", "®", ("whiteside machine & repair co",)),
    _B("Wera", "Wera Werk Hermann Werner GmbH", "®", ("wera tools na inc",)),
    _B("Vessel", "Vessel Co., Inc.", "®", ("vessel tools usa inc",)),
    _B("Edge Eyewear", "Wolf Peak International", "®", ("edge eyewear inc",)),
    _B("ProVia", "ProVia, LLC", "®", ("provia", "prodo")),
    _B("VELUX", "VELUX America LLC", "®", ("velux america inc",)),
    _B("CertainTeed", "CertainTeed LLC", "®", ("certainteed gypsum",)),
    _B("EMSEAL", "Sika Corporation", "®", ("emseal joint systems ltd", "emseal")),
    _B("Huber", "Huber Engineered Woods LLC", "®", ("huber eng wood llc", "zip system")),
    _B("Thomas & Betts", "ABB Installation Products", "®", ("thomas & betts",)),
    _B("National Nail", "National Nail Corp.", "®", ("national nail corp",)),
    _B("PREBENA", "PREBENA Wilfried Bornemann GmbH", "®", ("prebena",)),
    _B("King Canada", "King Canada Inc.", "®", ("king canada inc",)),
    _B("Oliver", "Oliver Machinery Company", "®", ("oliver machinery company",)),
    _B("Hager", "Hager Companies", "®", ("hager hinge co",)),
    _B("Woodpeckers", "Woodpeckers, LLC", "®", ("woodpeckers inc",)),
    _B("MAXSA", "MAXSA Innovations", "®", ("maxsa innovations",)),
    _B("Sabre", "Sabre Security Equipment Corp.", "®", ("sabre",)),
    _B("Bow Products", "Bow Products LLC", "®", ("bow products",)),
    _B("Prime Wire & Cable", "Prime Wire & Cable Inc.", "®", ("prime wire & cable",)),
)

#: Suppliers that are co-ops, distributors or lumber yards. Their name must
#: never become the manufacturer -- the brand has to come from the description
#: or the part-number prefix instead.
DISTRIBUTOR_MARKERS: Tuple[str, ...] = (
    "cooperative", "co-op", "coop", "dealers", "distributor", "supply",
    "lumber", "building materials", "parksite", "wholesale", "industrial supply",
    "jam industrial", "palmer donavin", "westwood", "boise cascade",
    "u s lumber", "us lumber", "tech gear", "premier metals", "metalmark",
    "fenton bros", "v & v appliance",
)

_CODE_RE = re.compile(r"\s*\(([A-Za-z0-9]{3,6})\)\s*$")
_NOISE_RE = re.compile(
    r"\b(inc|llc|ltd|corp|corporation|company|co|mfg|manufacturing|products|"
    r"prod|tools?|tool|usa|us|na|international|intl|group|holdings?|"
    r"industries|industrial|lighting|electric|electrical|accessory|"
    r"accessories|sales|brands|technologies)\b\.?", re.I)


#: Brand-shaped words that are really product vocabulary in some contexts.
#: "#2 Phillips Drive Bit" is a screw-drive type, not the lighting brand --
#: without this guard every driver bit in the catalogue resolves to Philips.
NEGATIVE_CONTEXT: Dict[str, Tuple[str, ...]] = {
    "phillips": ("drive", "bit", "head", "screw", "driver", "tip", "point", "ph2"),
    "philips": ("drive", "bit", "head", "screw", "driver", "tip", "point"),
    "square": ("drive", "edge", "edg", "foot", "ft", "head", "bit"),
    "square d": ("drive", "edge"),
    "element": ("heating", "filter"),
    "keystone": ("jack", "insert", "plate"),
    "edge eyewear": (),
    "jet": ("black", "stream"),
    "sabre": ("saw",),
}


def _blocked_by_context(alias: str, text: str, span: Tuple[int, int]) -> bool:
    words = NEGATIVE_CONTEXT.get(alias.lower())
    if not words:
        return False
    tail = text[span[1]:span[1] + 24].lower()
    head = text[max(0, span[0] - 12):span[0]].lower()
    return any(re.search(r"^\W*" + re.escape(w) + r"\b", tail) or
               re.search(r"\b" + re.escape(w) + r"\W*$", head) for w in words)


def _norm(s: str) -> str:
    s = str(s or "").lower()
    s = _CODE_RE.sub("", s)
    s = re.sub(r"[^a-z0-9&+ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _core(s: str) -> str:
    """Strip corporate noise words to expose the distinguishing token(s)."""
    s = _NOISE_RE.sub(" ", _norm(s))
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Resolution:
    brand: str = ""
    brand_display: str = ""
    manufacturer: str = ""
    method: str = ""
    confidence: float = 0.0
    evidence_text: str = ""
    evidence_source: str = ""
    detail: str = ""
    is_distributor_source: bool = False
    unverified: bool = False        # resolved, but not on the approved list
    entry: Optional[BrandEntry] = None


class BrandRegistry:
    """Approved manufacturer/brand master data with fuzzy lookup."""

    def __init__(self, entries: Sequence[BrandEntry] = BOOTSTRAP_BRANDS,
                 source: str = "bootstrap"):
        self.entries: List[BrandEntry] = list(entries)
        self.source = source
        self._alias: Dict[str, BrandEntry] = {}
        self._core: Dict[str, BrandEntry] = {}
        self._prefix: List[Tuple[str, BrandEntry]] = []
        self._reindex()

    def _reindex(self) -> None:
        self._alias.clear(); self._core.clear(); self._prefix.clear()
        for e in self.entries:
            keys = {_norm(e.brand), _norm(e.manufacturer)} | {_norm(a) for a in e.aliases}
            for k in keys:
                if k:
                    self._alias.setdefault(k, e)
            for k in {_core(e.brand)} | {_core(a) for a in e.aliases}:
                if k and len(k) >= 2:
                    self._core.setdefault(k, e)
            for p in e.mpn_prefixes:
                if p:
                    self._prefix.append((p.upper(), e))
        self._prefix.sort(key=lambda x: -len(x[0]))

    # -- loading -----------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[str] = None) -> "BrandRegistry":
        """Load the official master list when available, else bootstrap.

        Accepts the UniCat manufacturer/brand workbook or any CSV/XLSX with
        MANUFACTURER_NAME / BRAND_NAME columns.
        """
        if not path or not os.path.exists(path):
            return cls()
        from ..io.tabular import read_table  # local import: optional path
        rows, _ = read_table(path)
        entries: List[BrandEntry] = []
        for r in rows:
            low = {str(k).strip().lower(): (str(v).strip() if v is not None else "")
                   for k, v in r.items()}
            brand = (low.get("brand_name") or low.get("brand") or "").strip()
            manu = (low.get("manufacturer_name") or low.get("manufacturer") or "").strip()
            if not brand and not manu:
                continue
            name = brand or manu
            sym = ""
            for s in ("®", "™"):
                if s in name:
                    sym = s
                    name = name.replace(s, "").strip()
            entries.append(BrandEntry(brand=name, manufacturer=manu, symbol=sym,
                                      aliases=(), source=os.path.basename(path)))
        if not entries:
            return cls()
        merged = {(_norm(e.brand), _norm(e.manufacturer)): e for e in entries}
        # Keep the bootstrap aliases/prefixes; they encode this catalogue's mess.
        for b in BOOTSTRAP_BRANDS:
            merged.setdefault((_norm(b.brand), _norm(b.manufacturer)), b)
        return cls(list(merged.values()), source=os.path.basename(path))

    # -- lookup ------------------------------------------------------------
    def by_alias(self, text: str) -> Optional[BrandEntry]:
        n = _norm(text)
        if not n:
            return None
        if n in self._alias:
            return self._alias[n]
        c = _core(text)
        if c and c in self._core:
            return self._core[c]
        return None

    def by_prefix(self, mpn: str) -> Optional[Tuple[BrandEntry, str]]:
        m = str(mpn or "").upper().strip()
        for p, e in self._prefix:
            if m.startswith(p) and len(m) > len(p):
                return e, p
        return None

    def fuzzy(self, text: str, cutoff: float = 0.86
              ) -> Optional[Tuple[BrandEntry, float, str]]:
        c = _core(text)
        if not c or len(c) < 3:
            return None
        keys = list(self._core.keys())
        hit = difflib.get_close_matches(c, keys, n=1, cutoff=cutoff)
        if not hit:
            return None
        ratio = difflib.SequenceMatcher(None, c, hit[0]).ratio()
        return self._core[hit[0]], ratio, hit[0]

    def scan_text(self, text: str) -> Optional[Tuple[BrandEntry, str, Tuple[int, int]]]:
        """Find an approved brand mentioned inside a free-text description."""
        if not text:
            return None
        best = None
        for e in self.entries:
            names = [e.brand] + list(e.aliases)
            for nm in names:
                if not nm or len(nm) < 2:
                    continue
                for m in re.finditer(
                        r"(?<![A-Za-z0-9])" + re.escape(nm) + r"(?![A-Za-z0-9])",
                        text, re.I):
                    if _blocked_by_context(nm, text, m.span()):
                        continue
                    if best is None or len(nm) > len(best[1]):
                        best = (e, nm, m.span())
                    break
        return best


def is_distributor(supplier: str) -> bool:
    n = _norm(supplier)
    return any(mark in n for mark in DISTRIBUTOR_MARKERS)


def resolve_identity(registry: BrandRegistry, *, mpn: str = "", description: str = "",
                     supplier: str = "", dib_brand: str = "", e1_brand: str = ""
                     ) -> Resolution:
    """Resolve the approved brand for one row.

    Priority: explicit brand columns, then a brand named in the description,
    then the supplier string (only when the supplier is a real manufacturer),
    then the part-number prefix.
    """
    res = Resolution()
    res.is_distributor_source = is_distributor(supplier)

    for value, src, conf, why in (
        (dib_brand, "input:DIB_Brand", 0.95, "Distributor-supplied brand column."),
        (e1_brand, "input:E1_Brand", 0.93, "ERP brand column."),
    ):
        if value:
            e = registry.by_alias(value)
            if e:
                return _fill(res, e, "registry", conf, value, src,
                             "Matched '{}' to the approved brand list.".format(value))
            fz = registry.fuzzy(value)
            if fz:
                return _fill(res, fz[0], "registry", conf * fz[1], value, src,
                             "Fuzzy-matched '{}' at {:.0%}.".format(value, fz[1]))
            res.brand = value
            res.brand_display = value
            res.method, res.confidence = "input", 0.70
            res.evidence_text, res.evidence_source = value, src
            res.detail = "Brand column value not present in the approved list."
            return res

    hit = registry.scan_text(description)
    if hit:
        e, nm, span = hit
        return _fill(res, e, "registry", 0.88, nm, "input:Part_Desc",
                     "Approved brand '{}' found in the description.".format(nm))

    if supplier and not res.is_distributor_source:
        e = registry.by_alias(supplier)
        if e:
            return _fill(res, e, "registry", 0.90, supplier, "input:Part_Manuf",
                         "Supplier string normalised to the approved manufacturer.")
        fz = registry.fuzzy(supplier)
        if fz:
            return _fill(res, fz[0], "registry", 0.82 * fz[1], supplier,
                         "input:Part_Manuf",
                         "Fuzzy-matched supplier at {:.0%}.".format(fz[1]))

    pref = registry.by_prefix(mpn)
    if pref:
        e, p = pref
        return _fill(res, e, "rule", 0.80, p, "input:Mfg_Part_Num",
                     "Part-number prefix '{}' is unique to this brand -- used "
                     "because the supplier is a distributor/co-op.".format(p))

    if supplier and res.is_distributor_source:
        res.detail = ("Supplier is a distributor or buying co-op and no brand "
                      "could be recovered from the description or part number.")
        res.method, res.confidence = "abstain", 0.0
        res.evidence_source = "input:Part_Manuf"
        res.evidence_text = supplier
        return res

    if supplier:
        # The supplier is not a distributor, so it is the manufacturer -- it is
        # simply absent from the approved list. The content guidelines are
        # explicit that where an item has no brand, the manufacturer name is
        # used instead, so the cleaned supplier string is used and flagged as
        # unverified rather than dropped. "Rees Cast Stone Company (REECA)"
        # becomes "Rees Cast Stone Company"; the ERP code is not part of a name.
        name = _clean_supplier_name(supplier)
        if name:
            res.brand = res.brand_display = name
            res.manufacturer = name
            res.method, res.confidence = "input", 0.58
            res.evidence_text, res.evidence_source = supplier, "input:Part_Manuf"
            res.detail = ("Supplier is not a known distributor, so it is treated "
                          "as the manufacturer. This name is NOT on the approved "
                          "list and needs verification before publication.")
            res.unverified = True
    return res


_SUPPLIER_TAIL = re.compile(
    r"\s*\b(inc|llc|ltd|corp|corporation|company|co|mfg|manufacturing)\b\.?\s*$",
    re.I)


def _clean_supplier_name(supplier: str) -> str:
    """Turn an ERP supplier string into something printable as a name."""
    name = _CODE_RE.sub("", str(supplier or "").strip()).strip(" -,")
    if not name or len(name) < 2:
        return ""
    name = re.sub(r"\s{2,}", " ", name)
    # Expand the abbreviations ERP systems use for spacing reasons.
    name = re.sub(r"\bU\s+S\b", "U.S.", name)
    return name.strip()


def _fill(res: Resolution, e: BrandEntry, method: str, conf: float,
          text: str, source: str, detail: str) -> Resolution:
    res.entry = e
    res.brand = e.brand
    res.brand_display = e.display
    res.manufacturer = e.manufacturer or e.brand
    res.method, res.confidence = method, min(0.97, conf)
    res.evidence_text, res.evidence_source, res.detail = text, source, detail
    return res


def identity_facts(res: Resolution) -> List[Fact]:
    """Turn a resolution into evidenced facts."""
    out: List[Fact] = []
    if not res.brand:
        return out
    ev = [Evidence(source=res.evidence_source, text=res.evidence_text,
                   span=None, detail=res.detail)]
    out.append(Fact(key="brand", value=res.brand_display, label="Brand Name",
                    method=res.method if res.method != "abstain" else "inferred",
                    rule_id="IDN-BRD-01", raw=res.evidence_text,
                    confidence=res.confidence, priority=1, evidence=list(ev)))
    if res.manufacturer:
        out.append(Fact(key="manufacturer", value=res.manufacturer,
                        label="Manufacturer Name", method=res.method,
                        rule_id="IDN-MFR-01", raw=res.evidence_text,
                        confidence=res.confidence * 0.98, priority=2,
                        evidence=list(ev)))
    return out


def detect_mismatch(registry: BrandRegistry, res: Resolution,
                    supplier: str) -> Optional[Dict[str, str]]:
    """Flag a brand whose manufacturer disagrees with the supplied one.

    Comparison is between *registry entries*, not strings. Comparing strings
    flags every legitimate parent-company relationship -- ``Phillips Lighting``
    resolving to ``Signify Holding`` is correct, not a mismatch -- and buries
    the real cases. Only a supplier that resolves to a genuinely different
    approved manufacturer is reported.

    The published ground truth contains exactly one real case (FRIGIDAIRE(R)
    paired with Rheem Manufacturing). Reporting it is a feature, not a failure.
    """
    if not res.brand or not supplier or res.is_distributor_source:
        return None
    if not res.entry:
        return None

    supplier_entry = registry.by_alias(supplier)
    if supplier_entry is None:
        fz = registry.fuzzy(supplier, cutoff=0.80)
        supplier_entry = fz[0] if fz else None
    if supplier_entry is None:
        return None  # unknown supplier is a coverage gap, not a contradiction
    if supplier_entry is res.entry:
        return None
    if _core(supplier_entry.manufacturer) == _core(res.entry.manufacturer):
        return None  # same parent company, different brand line

    ratio = difflib.SequenceMatcher(
        None, _core(supplier_entry.brand), _core(res.entry.brand)).ratio()
    if ratio >= 0.85:
        return None
    return {
        "kind": "brand_manufacturer_mismatch",
        "message": ("Supplied manufacturer '{}' does not correspond to the "
                    "approved manufacturer '{}' for brand {}."
                    .format(supplier.strip(), res.manufacturer, res.brand_display)),
        "supplied": supplier.strip(),
        "supplied_brand": supplier_entry.brand,
        "resolved": res.manufacturer,
        "brand": res.brand_display,
        "similarity": "{:.2f}".format(ratio),
    }
