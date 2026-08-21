"""Category-spec induction.

A Unilog category specification -- the thing ``FAUCETS_LOV.xlsx`` is -- is a
fixed, ordered list of attribute slots, each with permitted values, a
filterable flag, and a synonym map, plus the word order used to build titles
and descriptions. Today a human content analyst writes one per category, and
there are tens of thousands of categories.

This module induces that object from raw rows.

Given ``n`` unlabelled rows of a category the pipeline has never seen, it
derives:

* the item types the category contains,
* which attributes actually apply, and how often they are populated,
* the permitted value set (the induced LOV) for each attribute,
* a synonym -> canonical collapse map,
* which attributes are worth exposing as search facets,
* the attribute ordering, from most to least discriminating.

The induced spec is then executable: it drives extraction and composition for
the remaining rows of that category. Everything it asserts is backed by a
count, so the spec can be scored against a real one.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .facts import Fact
from .parse import (ABBREVIATIONS, expand_abbreviations, parse_description,
                    residual_text, strip_mpn_echo)

# ---------------------------------------------------------------------------
# Seed lexicon. Anchors induction so the first few rows of an unseen category
# still produce sane head nouns. Corpus mining extends it; it is deliberately
# small and generic rather than a hand-tuned answer key.
# ---------------------------------------------------------------------------
SEED_ITEM_TYPES: Tuple[str, ...] = (
    "cut off disc", "cut off wheel", "grinding wheel", "sanding belt",
    "sanding disc", "flap disc", "saw blade", "drill bit", "driver bit",
    "hole saw", "router bit", "band saw", "table saw", "miter saw",
    "circular saw", "reciprocating saw", "jig saw", "impact driver",
    "impact wrench", "drill", "hammer drill", "ratchet", "die grinder",
    "orbit sander", "random orbit sander", "belt sander", "spindle sander",
    "string trimmer", "battery charger", "charger", "battery",
    "light bulb", "led bulb", "lamp", "ceiling light", "wall light",
    "pendant light", "chandelier", "downlight", "flood light", "flash light",
    "motion light", "exterior wall light", "bath light", "ceiling fan",
    "light fixture", "load center", "circuit breaker", "receptacle", "switch",
    "wall plate", "box cover", "junction box", "wire", "cord", "cable",
    "dishwasher", "refrigerator", "range", "cooktop", "wall oven",
    "microwave", "washer", "dryer", "freezer", "water heater",
    "decking", "railing", "siding", "trim board", "panel", "mortar",
    "support post", "fence", "stock feeder", "table assembly",
    "brad nailer", "finish nailer", "framing nailer", "nail", "screw",
    "staple", "tape", "tape measure", "safety glasses", "gauge",
    "pressure gauge", "sander", "planer", "jointer", "lathe", "vacuum",
)

#: Tokens that are never an item type on their own.
STOPWORDS = {
    "the", "and", "for", "with", "new", "kit", "set", "pro", "plus", "series",
    "only", "display", "bare", "each", "box", "pack", "piece", "type",
    "replacement", "assembly", "system", "advanced", "industrial", "basics",
}

#: Technology / material modifiers that describe an item but are never the item
#: itself. "60W Led Med 27k 3pk" is a light bulb; "Led" is how it makes light.
#: Left unguarded these become the most common "item type" in a lighting
#: catalogue and every one of those rows fails to classify.
MODIFIER_ONLY = {
    "led", "incan", "incandescent", "cfl", "halogen", "fluorescent", "hid",
    "smart", "solar", "cordless", "corded", "electric", "gas", "battery",
    "heated", "insulated", "green", "black", "white", "stainless", "steel",
    "aluminum", "pvc", "composite", "wood", "vinyl", "premium", "standard",
    "mb", "st", "ro", "xl", "pro", "gr",
}

#: Facts that, taken together, identify an item type the text never names.
#: A row with a wattage, a colour temperature and a lamp base is a light bulb
#: whether or not the word "bulb" appears anywhere in the description.
INFERENCE_RULES: Tuple[Tuple[str, Tuple[str, ...], int, str], ...] = (
    ("Light Bulb", ("wattage", "color_temperature"), 2, "ITM-INF-LAMP"),
    ("Light Bulb", ("wattage", "base_type"), 2, "ITM-INF-LAMP"),
    ("Light Bulb", ("bulb_shape", "color_temperature"), 2, "ITM-INF-LAMP"),
    ("Light Bulb", ("lumens", "color_temperature"), 2, "ITM-INF-LAMP"),
)


def infer_item_type(fact_keys: Iterable[str]) -> Optional[Tuple[str, str, List[str]]]:
    """Infer an item type from co-occurring attributes.

    Returns ``(item_type, rule_id, supporting_keys)``. This is an *inference*,
    not an extraction -- the caller records it as such so the provenance panel
    shows it was derived rather than read.
    """
    have = set(fact_keys)
    for name, required, need, rule_id in INFERENCE_RULES:
        hits = [k for k in required if k in have]
        if len(hits) >= need:
            return name, rule_id, hits
    return None


#: Words that mark a brand/series rather than an item type.
_BRANDISH = re.compile(r"^[A-Z0-9][A-Z0-9\-+.]*$")


def _tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[A-Za-z][A-Za-z\-+]*", text) if t]


def strip_terms(text: str, terms: Iterable[str]) -> str:
    """Remove brand and series words before item-type mining.

    Without this the mined vocabulary fills up with ``azek pvc decking`` and
    ``kichler wall light`` -- brand-prefixed variants of the same item type,
    which fragments the LOV and inflates cardinality.
    """
    out = text
    for t in sorted({str(t or "").strip() for t in terms if t}, key=len, reverse=True):
        if len(t) < 2:
            continue
        out = re.sub(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])",
                     " ", out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


# ---------------------------------------------------------------------------
# Item-type induction
# ---------------------------------------------------------------------------
class ItemTypeLexicon:
    """Frequency-scored vocabulary of item types mined from a corpus."""

    def __init__(self, seed: Iterable[str] = SEED_ITEM_TYPES):
        self.counts: Counter = Counter()
        self.seed = {_norm(s) for s in seed}
        for s in self.seed:
            self.counts[s] = 0

    def observe(self, residual: str) -> None:
        """Record the trailing noun phrases of one residual string."""
        expanded = expand_abbreviations(residual)
        toks = [t for t in _tokens(expanded)]
        if not toks:
            return
        low = [t.lower() for t in toks]
        # Trailing n-grams up to 3 words are the item-type candidates; industrial
        # descriptions put the head noun last ("Milw Masonry Cut Off Disc").
        for n in (3, 2, 1):
            if len(low) < n:
                continue
            gram = " ".join(low[-n:])
            if n == 1 and (low[-1] in STOPWORDS or low[-1] in MODIFIER_ONLY):
                continue
            if gram in MODIFIER_ONLY:
                continue
            self.counts[gram] += 1

    def finalise(self, min_count: int = 3) -> Dict[str, int]:
        """Keep grams that either recur or were seeded."""
        return {g: c for g, c in self.counts.items()
                if c >= min_count or g in self.seed}

    # -- resolution --------------------------------------------------------
    def resolve(self, residual: str,
                vocab: Optional[Dict[str, int]] = None) -> Optional[Tuple[str, str, float]]:
        """Return ``(item_type, matched_text, confidence)`` for one residual.

        Longest match wins; ties break on corpus frequency. Falls back to the
        trailing noun when nothing in the vocabulary matches, which keeps
        unseen categories working instead of returning nothing.
        """
        vocab = vocab if vocab is not None else self.finalise()
        expanded = expand_abbreviations(residual)
        toks = _tokens(expanded)
        if not toks:
            return None
        low = [t.lower() for t in toks]

        # A canonical (seeded) gram beats a longer corpus-mined one: without
        # this, series words glue themselves to the head noun and the category
        # fragments into "transcend lineage decking" vs "enhance basics
        # decking" instead of collapsing to "decking".
        best: Optional[Tuple[int, int, int, str]] = None
        for n in (4, 3, 2, 1):
            for i in range(len(low) - n + 1):
                gram = " ".join(low[i:i + n])
                if gram not in vocab:
                    continue
                if gram in MODIFIER_ONLY:
                    continue
                cand = (1 if gram in self.seed else 0, n, vocab.get(gram, 0), gram)
                if best is None or cand[:3] > best[:3]:
                    best = cand
        if best:
            gram = best[3]
            conf = 0.72 + min(0.2, math.log1p(best[2]) / 25.0) + 0.04 * (best[1] - 1)
            if best[0]:
                conf += 0.05
            return _titlecase(gram), gram, min(0.95, conf)

        tail = [t for t in low if t not in STOPWORDS and t not in MODIFIER_ONLY]
        if not tail:
            return None
        head = tail[-1]
        if _BRANDISH.match(toks[low.index(head)]) and len(head) <= 4:
            return None
        return _titlecase(head), head, 0.55


_ACRONYMS = {"led", "gfci", "pvc", "usb", "hvac", "nm", "so", "ud", "mc", "thhn"}


def _titlecase(gram: str) -> str:
    out = []
    for w in gram.split():
        out.append(w.upper() if w in _ACRONYMS else w.capitalize())
    return " ".join(out)


# ---------------------------------------------------------------------------
# The induced specification
# ---------------------------------------------------------------------------
@dataclass
class AttributeSlot:
    """One induced attribute: what it is, how often it applies, what it allows."""

    key: str
    label: str
    uom: str = ""
    fill_rate: float = 0.0
    support: int = 0                       # rows where it was populated
    cardinality: int = 0
    filterable: bool = False
    discriminative: float = 0.0            # normalised entropy
    values: List[Tuple[str, int]] = field(default_factory=list)   # induced LOV
    synonyms: Dict[str, str] = field(default_factory=dict)
    rule_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["fill_rate"] = round(self.fill_rate, 4)
        d["discriminative"] = round(self.discriminative, 4)
        return d


@dataclass
class CategorySpec:
    """An executable, evidence-backed category rulebook."""

    category_id: str
    label: str = ""
    n_rows: int = 0
    item_types: List[Tuple[str, int]] = field(default_factory=list)
    attributes: List[AttributeSlot] = field(default_factory=list)
    title_order: List[str] = field(default_factory=list)
    induced_from: List[str] = field(default_factory=list)   # sample MPNs
    coverage: float = 0.0                                    # mean facts/row

    @property
    def attribute_keys(self) -> List[str]:
        return [a.key for a in self.attributes]

    def slot(self, key: str) -> Optional[AttributeSlot]:
        for a in self.attributes:
            if a.key == key:
                return a
        return None

    def permitted(self, key: str) -> List[str]:
        s = self.slot(key)
        return [v for v, _ in s.values] if s else []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category_id": self.category_id, "label": self.label,
            "n_rows": self.n_rows, "coverage": round(self.coverage, 3),
            "item_types": self.item_types,
            "title_order": list(self.title_order),
            "induced_from": list(self.induced_from),
            "attributes": [a.to_dict() for a in self.attributes],
        }


#: Canonical ordering prior. Induction decides *which* attributes exist; this
#: only decides how they read, matching the ordering seen in the delivery
#: format (identity -> electrical -> physical -> material -> misc).
ORDER_PRIOR: Tuple[str, ...] = (
    "series", "model", "platform", "item_type",
    "wattage", "voltage", "amperage", "horsepower", "phase",
    "lumens", "color_temperature", "bulb_shape", "base_type",
    "grit", "gauge", "diameter", "thickness", "arbor_size",
    "nominal_size", "dimensions", "size", "length",
    "conductor_config", "cable_type",
    "finish", "material", "pack_quantity", "selling_qty", "selling_uom",
    "includes_battery", "display_only",
)
_ORDER_INDEX = {k: i for i, k in enumerate(ORDER_PRIOR)}


def _entropy(counts: Sequence[int]) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    h = -sum((c / total) * math.log2(c / total) for c in counts if c)
    return h / math.log2(len(counts)) if len(counts) > 1 else 0.0


def induce_spec(rows: Sequence[Dict[str, str]],
                mpn_col: str, desc_col: str,
                category_id: str, label: str = "",
                lexicon: Optional[ItemTypeLexicon] = None,
                vocab: Optional[Dict[str, int]] = None,
                min_fill: float = 0.20,
                filter_max_cardinality: int = 40) -> CategorySpec:
    """Induce a category specification from unlabelled rows.

    ``min_fill`` is the fraction of rows an attribute must appear in before it
    earns a slot. Below that it is noise, not a category attribute.
    """
    n = len(rows)
    spec = CategorySpec(category_id=category_id, label=label or category_id, n_rows=n)
    if n == 0:
        return spec

    lexicon = lexicon or ItemTypeLexicon()
    values: Dict[str, Counter] = defaultdict(Counter)
    labels: Dict[str, str] = {}
    uoms: Dict[str, Counter] = defaultdict(Counter)
    rules: Dict[str, set] = defaultdict(set)
    support: Counter = Counter()
    item_types: Counter = Counter()
    total_facts = 0

    for r in rows:
        mpn = str(r.get(mpn_col) or "").strip()
        desc = str(r.get(desc_col) or "").strip()
        stripped, _ = strip_mpn_echo(desc, mpn)
        facts = parse_description(stripped)
        total_facts += len(facts)
        seen = set()
        for f in facts:
            support[f.key] += 1 if f.key not in seen else 0
            seen.add(f.key)
            values[f.key][str(f.value)] += 1
            labels.setdefault(f.key, f.label)
            if f.uom:
                uoms[f.key][f.uom] += 1
            if f.rule_id:
                rules[f.key].add(f.rule_id)

        res = residual_text(stripped, facts)
        hit = lexicon.resolve(res, vocab)
        if hit:
            item_types[hit[0]] += 1

    spec.coverage = total_facts / n
    spec.item_types = item_types.most_common(12)
    spec.induced_from = [str(r.get(mpn_col) or "") for r in rows[:8]]

    slots: List[AttributeSlot] = []
    for key, cnt in support.items():
        fill = cnt / n
        if fill < min_fill:
            continue
        vc = values[key]
        card = len(vc)
        slot = AttributeSlot(
            key=key,
            label=labels.get(key, key.replace("_", " ").title()),
            uom=(uoms[key].most_common(1)[0][0] if uoms[key] else ""),
            fill_rate=fill, support=cnt, cardinality=card,
            discriminative=_entropy(list(vc.values())),
            values=vc.most_common(60),
            rule_ids=sorted(rules[key]),
        )
        # A facet is useful when it splits the category into a browsable number
        # of buckets -- not one bucket, not one bucket per product.
        slot.filterable = (1 < card <= filter_max_cardinality
                           and fill >= 0.35 and card < max(2, 0.6 * cnt))
        slots.append(slot)

    slots.sort(key=lambda s: (_ORDER_INDEX.get(s.key, 500), -s.fill_rate))
    spec.attributes = slots
    spec.title_order = [s.key for s in slots if s.fill_rate >= 0.3][:8]
    return spec


def build_lexicon(rows: Sequence[Dict[str, str]], mpn_col: str,
                  desc_col: str) -> Tuple[ItemTypeLexicon, Dict[str, int]]:
    """One pass over the whole catalogue to mine the item-type vocabulary."""
    lex = ItemTypeLexicon()
    for r in rows:
        mpn = str(r.get(mpn_col) or "").strip()
        desc = str(r.get(desc_col) or "").strip()
        stripped, _ = strip_mpn_echo(desc, mpn)
        facts = parse_description(stripped)
        lex.observe(residual_text(stripped, facts))
    return lex, lex.finalise()


# ---------------------------------------------------------------------------
# Scoring an induced spec against a real one
# ---------------------------------------------------------------------------
def score_spec(induced: CategorySpec, truth_labels: Sequence[str]) -> Dict[str, Any]:
    """Compare induced attribute slots to a real category spec's label list.

    Reported as precision / recall / ordering correlation so a weak category
    shows up as weak instead of being averaged away.
    """
    def canon(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(s).lower())

    truth = [canon(t) for t in truth_labels]
    got = [canon(a.label) for a in induced.attributes]
    tset, gset = set(truth), set(got)
    hits = tset & gset
    precision = len(hits) / len(gset) if gset else 0.0
    recall = len(hits) / len(tset) if tset else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    # Ordering agreement over the attributes both lists contain.
    common = [t for t in truth if t in gset]
    order_pairs = concordant = 0
    for i in range(len(common)):
        for j in range(i + 1, len(common)):
            order_pairs += 1
            if got.index(common[i]) < got.index(common[j]):
                concordant += 1
    order_score = concordant / order_pairs if order_pairs else 1.0

    return {
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(f1, 4), "order_agreement": round(order_score, 4),
        "matched": sorted(hits), "missed": sorted(tset - gset),
        "extra": sorted(gset - tset),
        "n_truth": len(tset), "n_induced": len(gset),
    }
