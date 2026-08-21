"""Delivery-format schema: the frozen 252-column contract, plus role detection
for arbitrary input files.

The header is loaded from ``refdata/delivery_header.csv`` so it stays
byte-identical to the sheet Unilog published. Nothing here renames, reorders or
drops a column -- that is an explicit rule of the challenge.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
_HEADER_PATH = os.path.join(_HERE, "refdata", "delivery_header.csv")


def load_delivery_header(path: str = _HEADER_PATH) -> List[str]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return next(csv.reader(fh))


DELIVERY_COLUMNS: List[str] = load_delivery_header()
DELIVERY_INDEX: Dict[str, int] = {c: i for i, c in enumerate(DELIVERY_COLUMNS)}

#: How many repeating attribute triples the sheet exposes.
MAX_ATTRIBUTES = 50
#: How many ITEM_FEATURES_n bullet slots the sheet exposes.
MAX_FEATURES = 20
#: How many reference-URL slots the sheet exposes.
MAX_REF_URLS = 5


def attribute_slot(n: int) -> Sequence[str]:
    """Column names for the nth (1-based) attribute triple."""
    return (
        "ATTRIBUTE_LABEL {}".format(n),
        "ATTRIBUTE_VALUE {}".format(n),
        "ATTRIBUTE_UOM {}".format(n),
    )


# --------------------------------------------------------------------------
# Character limits and casing rules, transcribed from the content guidelines.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class FieldRule:
    column: str
    min_len: Optional[int] = None
    max_len: Optional[int] = None
    casing: str = "free"
    rule_id: str = ""
    note: str = ""


FIELD_RULES: Dict[str, FieldRule] = {
    r.column: r
    for r in [
        FieldRule("INVOICE_DESC", None, 40, "upper", "CG-INV-01",
                  "Till/invoice line. Hard 40-char ceiling, all caps."),
        FieldRule("MOBILE_DESC", 60, 80, "free", "CG-MOB-01",
                  "Mobile listing line, 60-80 chars, comma-delimited fact order."),
        FieldRule("SHORT_DESC", None, 240, "free", "CG-SHT-01",
                  "Product title / search-results line."),
        FieldRule("Product Name", None, 120, "free", "CG-PNM-01",
                  "Bare item type, no brand or model."),
        FieldRule("LONG_DESC1", None, 4000, "free", "CG-LNG-01",
                  "Product-page description; every captured attribute in order."),
        FieldRule("RETAIL_DESC", None, 240, "free", "CG-RET-01",
                  "Retail shelf line: series + item type + differentiators."),
        FieldRule("MARKETING_DESCRIPTION", None, 4000, "sentence", "CG-MKT-01",
                  "Manufacturer marketing copy. Sourced, never invented."),
    ]
}
for _i in range(1, MAX_ATTRIBUTES + 1):
    FIELD_RULES["ATTRIBUTE_VALUE {}".format(_i)] = FieldRule(
        "ATTRIBUTE_VALUE {}".format(_i), None, 200, "free", "CG-ATT-01",
        "Attribute value must exist in the controlled vocabulary for the classpath.")
for _i in range(1, MAX_FEATURES + 1):
    FIELD_RULES["ITEM_FEATURES_{}".format(_i)] = FieldRule(
        "ITEM_FEATURES_{}".format(_i), None, 200, "sentence", "CG-FEA-01",
        "Selling bullet. Sourced from manufacturer copy.")


# --------------------------------------------------------------------------
# Input role detection -- the pipeline must accept *any* file, not just the
# sample.
# --------------------------------------------------------------------------
ROLE_PATTERNS: Dict[str, List[str]] = {
    "mpn": [r"^mfg[_ ]?part[_ ]?num", r"^manufacturer[_ ]?part", r"^mfr[_ ]?part",
            r"^part[_ ]?(no|num|number)$", r"^mpn$", r"^model[_ ]?(no|num)?$",
            r"^catalog[_ ]?(no|num)"],
    "description": [r"^part[_ ]?desc", r"^item[_ ]?desc", r"^(short[_ ]?)?desc",
                    r"^product[_ ]?(name|desc|title)", r"^title$", r"^name$"],
    "brand_e1": [r"^e1[_ ]?brand", r"^erp[_ ]?brand"],
    "brand_unilog": [r"^unilog[_ ]?brand"],
    "brand_dib": [r"^dib[_ ]?brand", r"^distributor[_ ]?brand"],
    "brand": [r"^brand([_ ]?name)?$", r"^make$"],
    "manufacturer": [r"^part[_ ]?manuf", r"^manufacturer", r"^mfg$", r"^mfr$",
                     r"^vendor", r"^supplier"],
    "sku": [r"^sku", r"^my[_ ]?part[_ ]?number", r"^internal[_ ]?(id|part)"],
    "dept": [r"^dept", r"^department"],
    "class": [r"^class$", r"^category$"],
    "fine": [r"^fine$", r"^sub[_ ]?class", r"^sub[_ ]?category"],
    "upc": [r"^upc", r"^gtin", r"^ean"],
    "url": [r"url$", r"^link$"],
    "price": [r"price$", r"^cost$"],
}

#: Values that look like data but mean "this field is empty".
PLACEHOLDER_RE = re.compile(
    r"^\s*(--\s*)?(no\s+)?(unbranded|un-?branded|none|n/?a|null|nil|tbd|unknown|"
    r"no\s+[\w& ]+\s+brand|commodity\s*-\s*unbranded|not\s+applicable|-{1,3}|\.)"
    r"\s*(--)?\s*$",
    re.I,
)


def is_placeholder(value: Optional[str]) -> bool:
    """True when a cell is filled with a sentinel that means 'empty'.

    The double-dash sentinels account for ~80% of the brand columns in the
    sample; treating them as real values poisons every downstream match.
    """
    if value is None:
        return True
    v = str(value).strip()
    if not v:
        return True
    if PLACEHOLDER_RE.match(v):
        return True
    if v.startswith("--") and v.endswith("--"):
        return True
    return False


def clean(value: Optional[str]) -> str:
    """Normalise whitespace and blank out placeholders."""
    if is_placeholder(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _norm_col(name: str) -> str:
    return re.sub(r"[^a-z0-9_ ]+", "", str(name).strip().lower())


@dataclass
class InputSchema:
    """Detected mapping from a source file's columns onto canonical roles."""

    columns: List[str]
    roles: Dict[str, str] = field(default_factory=dict)
    unmapped: List[str] = field(default_factory=list)
    confidence: Dict[str, float] = field(default_factory=dict)

    def get(self, row: Dict[str, str], role: str) -> str:
        col = self.roles.get(role)
        return clean(row.get(col)) if col else ""

    def raw(self, row: Dict[str, str], role: str) -> str:
        col = self.roles.get(role)
        return str(row.get(col) or "").strip() if col else ""

    def to_dict(self) -> Dict[str, object]:
        return {"roles": dict(self.roles), "unmapped": list(self.unmapped),
                "confidence": dict(self.confidence)}


def detect_schema(columns: Sequence[str],
                  sample_rows: Optional[Sequence[Dict[str, str]]] = None) -> InputSchema:
    """Map arbitrary column headers onto canonical roles.

    Name matching first (high confidence), then content sniffing for anything
    still unclaimed -- so a file with headers like ``col_a, col_b`` still gets a
    usable mapping instead of failing outright.
    """
    schema = InputSchema(columns=list(columns))
    taken = set()

    for role, patterns in ROLE_PATTERNS.items():
        for col in columns:
            if col in taken:
                continue
            n = _norm_col(col)
            matched = False
            for pat in patterns:
                if re.search(pat, n):
                    matched = True
                    break
            if matched:
                schema.roles[role] = col
                schema.confidence[role] = 0.98
                taken.add(col)
                break

    if sample_rows:
        _sniff(schema, columns, taken, sample_rows)

    schema.unmapped = [c for c in columns if c not in taken]
    return schema


def _sniff(schema: InputSchema, columns: Sequence[str], taken: set,
           rows: Sequence[Dict[str, str]]) -> None:
    """Content-based fallback for unnamed / cryptically named columns."""
    for col in columns:
        if col in taken:
            continue
        vals = [str(r.get(col) or "").strip() for r in rows[:200]]
        vals = [v for v in vals if v]
        if not vals:
            continue
        uniq = len(set(vals)) / max(1, len(vals))
        avg_len = sum(len(v) for v in vals) / len(vals)
        has_space = sum(1 for v in vals if " " in v) / len(vals)
        placeholder_rate = sum(1 for v in vals if is_placeholder(v)) / len(vals)

        if "mpn" not in schema.roles and uniq > 0.9 and has_space < 0.25 and avg_len < 30:
            schema.roles["mpn"] = col
            schema.confidence["mpn"] = 0.62
            taken.add(col)
        elif "description" not in schema.roles and has_space > 0.7 and avg_len > 18:
            schema.roles["description"] = col
            schema.confidence["description"] = 0.60
            taken.add(col)
        elif "manufacturer" not in schema.roles and 0 < uniq < 0.3 and placeholder_rate < 0.5:
            schema.roles["manufacturer"] = col
            schema.confidence["manufacturer"] = 0.45
            taken.add(col)


def blank_delivery_row() -> Dict[str, str]:
    return dict((c, "") for c in DELIVERY_COLUMNS)
