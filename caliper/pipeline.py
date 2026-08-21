"""The CALIPER pipeline.

Stages, in order. Everything from ``parse`` to ``normalise`` *writes* facts;
everything after only *reads* them.

    schema detection -> family clustering -> deterministic parse
    -> identity resolution -> item type -> taxonomy -> (LLM / document fill)
    -> PRODUCT FACT GRAPH
    -> composition -> validation -> selective delivery

The one-way boundary is the point: an output cell cannot contain a value that
no fact supports, so "the model wrote something plausible" is not a failure mode
this design has.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .schema import (DELIVERY_COLUMNS, MAX_ATTRIBUTES, MAX_FEATURES, FIELD_RULES,
                     InputSchema, blank_delivery_row, clean, detect_schema)
from .core.compose import (build_invoice_desc, build_long_desc, build_mobile_desc,
                           build_product_name, build_retail_desc, build_short_desc,
                           clip, enforce_casing)
from .core.facts import Evidence, Fact, ProductFactGraph
from .core.identity import (BrandRegistry, detect_mismatch, identity_facts,
                            resolve_identity)
from .core.induce import (MODIFIER_ONLY, CategorySpec, ItemTypeLexicon,
                          build_lexicon, induce_spec, infer_item_type,
                          strip_terms)
from .core.parse import (expand_abbreviations, parse_description, residual_text,
                         strip_mpn_echo)
from .core.corrections import CorrectionStore
from .core.guardrails import apply as apply_guardrails
from .core import knowledge
from .core.packs import PackLibrary, resolve_slot_key
from .core.taxonomy import classify, taxonomy_facts

# ---------------------------------------------------------------------------
# Series / collection detection
# ---------------------------------------------------------------------------
_SERIES_STOP = {
    "the", "and", "with", "for", "new", "pro", "kit", "set", "only", "display",
    "bare", "each", "box", "pack", "piece", "type", "series",
    # Materials and applications read like collection names but are not:
    # "Metal Cut Off Disc" has no series, it has a application of Metal.
    "metal", "masonry", "wood", "concrete", "steel", "stainless", "aluminum",
    "brass", "copper", "plastic", "ceramic", "tile", "glass", "diamond",
    "carbide", "universal", "standard", "heavy", "duty", "general", "purpose",
    "multi", "all", "round", "square", "flat", "smooth", "primed", "grooved",
    "left", "right", "front", "rear", "upper", "lower", "inch", "volt",
}
_SERIES_RE = re.compile(r"\b([A-Z][A-Za-z]+(?:\s+(?:[A-Z][A-Za-z]+|[IVX]+|\d+\.\d+))*)\b")


def detect_series(residual: str, item_type: str, brand: str,
                  known: Optional[Dict[str, int]] = None) -> Optional[Tuple[str, str]]:
    """Find a collection/series name in the text no other rule claimed.

    Series names are the capitalised phrases left over once the brand and the
    item type have been removed -- ``Cubitron II``, ``Performance+``,
    ``Enhance Basics``, ``Select 2.0``.
    """
    text = strip_terms(residual, [brand, item_type] + item_type.split())
    if not text:
        return None
    best = None
    for m in _SERIES_RE.finditer(text):
        cand = m.group(1).strip()
        words = [w for w in cand.split() if w.lower() not in _SERIES_STOP]
        if not words:
            continue
        cand = " ".join(words)
        low = cand.lower()
        if len(cand) < 3 or low in _SERIES_STOP or low in MODIFIER_ONLY:
            continue
        # A series is not the item type restated, nor the brand restated.
        # "LG Fridge ... Refrigerator" and "Edge Eyewear Edge ..." both came
        # from skipping this check.
        if item_type and (low in item_type.lower() or item_type.lower() in low):
            continue
        if brand and (low in brand.lower() or brand.lower() in low):
            continue
        freq = known.get(cand.lower(), 0) if known else 0
        # A real collection name recurs across the catalogue or is multi-word.
        # A single capitalised word seen once is almost always a stray adjective.
        if freq < 3 and len(words) < 2:
            continue
        score = (freq, len(cand))
        if best is None or score > best[0]:
            best = (score, cand, m.span())
    if not best:
        return None
    return best[1], best[1]


# ---------------------------------------------------------------------------
# Family clustering
# ---------------------------------------------------------------------------
def family_signature(mpn: str, desc: str, supplier: str) -> str:
    """Collapse a row to the family it belongs to.

    Numbers and dimension chains are the *varying* axis inside a family, so
    they are masked out; what remains is the shared product concept.
    """
    d = strip_mpn_echo(desc, mpn)[0]
    d = re.sub(r"\d+(?:\.\d+)?(?:\s*/\s*\d+)?", "#", d)
    d = re.sub(r"[#\"'x\-\s]+", " ", d, flags=re.I)
    toks = sorted({t.lower() for t in re.findall(r"[A-Za-z]{3,}", d)})
    raw = "{}|{}".format(supplier.strip().lower(), " ".join(toks))
    return "F-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------
@dataclass
class RowResult:
    index: int
    graph: ProductFactGraph
    delivery: Dict[str, str] = field(default_factory=dict)
    provenance: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    violations: List[Dict[str, Any]] = field(default_factory=list)
    flags: List[Dict[str, Any]] = field(default_factory=list)
    filled: int = 0
    status: str = "ready"          # ready | needs_review | blocked
    invoice_budget: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index, "status": self.status, "filled": self.filled,
            "score": round(self.graph.score(), 4),
            "family_id": self.graph.family_id,
            "graph": self.graph.to_dict(),
            "violations": self.violations, "flags": self.flags,
            "invoice_budget": self.invoice_budget,
        }


@dataclass
class PipelineReport:
    n_rows: int = 0
    elapsed_s: float = 0.0
    schema: Dict[str, Any] = field(default_factory=dict)
    families: int = 0
    specs: List[Dict[str, Any]] = field(default_factory=list)
    fill_rate: float = 0.0
    mean_columns_filled: float = 0.0
    status_counts: Dict[str, int] = field(default_factory=dict)
    flag_counts: Dict[str, int] = field(default_factory=dict)
    violation_counts: Dict[str, int] = field(default_factory=dict)
    brand_resolution: float = 0.0
    classification_rate: float = 0.0
    char_compliance: Dict[str, float] = field(default_factory=dict)
    family_inherited: int = 0
    family_anomalies: int = 0
    llm_invoked: int = 0
    llm_served: int = 0
    llm_cached: int = 0
    ai_degraded: bool = False
    ai_notice: str = ""
    audited_rows: int = 0
    audit_counts: Dict[str, int] = field(default_factory=dict)
    guardrail_findings: Dict[str, int] = field(default_factory=dict)
    knowledge: Dict[str, Any] = field(default_factory=dict)
    corrections: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class Pipeline:
    """Runs the whole enrichment. Deterministic by default; an optional
    ``llm`` callable fills only what the rules could not reach."""

    def __init__(self, registry: Optional[BrandRegistry] = None,
                 llm: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
                 auditor: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
                 emit_asset_conventions: bool = False):
        self.registry = registry or BrandRegistry.load()
        self.llm = llm
        self.auditor = auditor
        self.audited = 0
        self.audit_counts = {"supported": 0, "unsupported": 0, "unknown": 0}
        self.emit_asset_conventions = emit_asset_conventions
        self.lexicon: Optional[ItemTypeLexicon] = None
        self.vocab: Dict[str, int] = {}
        self.specs: Dict[str, CategorySpec] = {}
        self.series_vocab: Dict[str, int] = {}
        self.llm_invoked = 0
        self.edges = []
        self.packs = PackLibrary.load()
        self.corrections = CorrectionStore.load()
        self._teach_registry_aliases()

    def _teach_registry_aliases(self) -> None:
        """Fold reviewer-taught supplier aliases into the brand registry.

        One reviewer decision -- "this supplier string means this brand" --
        fixes every row from that supplier on every future run.
        """
        aliases = self.corrections.brand_aliases()
        if not aliases:
            return
        taught = 0
        for supplier, brand in aliases.items():
            entry = self.registry.by_alias(brand)
            if entry is None:
                continue
            if supplier not in entry.aliases:
                entry.aliases = tuple(entry.aliases) + (supplier,)
                taught += 1
        if taught:
            self.registry._reindex()

    # -- corpus passes -----------------------------------------------------
    def fit(self, rows: Sequence[Dict[str, str]], schema: InputSchema) -> None:
        """Corpus pass: mine the item-type vocabulary and induce category specs.

        This is the step that makes the pipeline work on a category it has
        never seen -- the rulebook is derived from the data, not hard-coded.
        """
        mpn_col = schema.roles.get("mpn", "")
        desc_col = schema.roles.get("description", "")
        if not desc_col:
            return

        brand_terms = set()
        for e in self.registry.entries:
            brand_terms.add(e.brand)
            brand_terms.update(e.aliases)

        self.lexicon, self.vocab = build_lexicon(rows, mpn_col, desc_col)
        # Re-mine with brand words removed so the vocabulary holds item types
        # rather than brand+item-type compounds.
        lex = ItemTypeLexicon()
        for r in rows:
            mpn = str(r.get(mpn_col) or "")
            desc = str(r.get(desc_col) or "")
            stripped, _ = strip_mpn_echo(desc, mpn)
            facts = parse_description(stripped)
            res = residual_text(stripped, facts)
            lex.observe(strip_terms(res, brand_terms))
        self.lexicon, self.vocab = lex, lex.finalise()

        # Induce one spec per taxonomy leaf discovered in the corpus.
        groups: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        for r in rows:
            key = self._provisional_category(r, schema, brand_terms)
            groups[key].append(r)
        for key, grp in groups.items():
            if len(grp) < 3:
                continue
            self.specs[key] = induce_spec(
                grp, mpn_col, desc_col, category_id=key, label=key,
                lexicon=self.lexicon, vocab=self.vocab)

        # Series candidates: capitalised phrases that recur across the corpus.
        sc: Counter = Counter()
        for r in rows:
            mpn = str(r.get(mpn_col) or "")
            desc = str(r.get(desc_col) or "")
            stripped, _ = strip_mpn_echo(desc, mpn)
            facts = parse_description(stripped)
            res = strip_terms(residual_text(stripped, facts), brand_terms)
            for m in _SERIES_RE.finditer(res):
                sc[m.group(1).strip().lower()] += 1
        self.series_vocab = {k: v for k, v in sc.items() if v >= 3}

    def _provisional_category(self, row: Dict[str, str], schema: InputSchema,
                              brand_terms: Iterable[str]) -> str:
        desc = schema.get(row, "description")
        mpn = schema.get(row, "mpn")
        stripped, _ = strip_mpn_echo(desc, mpn)
        facts = parse_description(stripped)
        res = strip_terms(residual_text(stripped, facts), brand_terms)
        hit = self.lexicon.resolve(res, self.vocab) if self.lexicon else None
        item_type = hit[0] if hit else ""
        c = classify(item_type, desc)
        return c.node.classpath if c.node else "UNCLASSIFIED"

    # -- per-row -----------------------------------------------------------
    def process_row(self, row: Dict[str, str], schema: InputSchema,
                    index: int = 0) -> RowResult:
        mpn = schema.get(row, "mpn")
        desc = schema.get(row, "description")
        supplier = schema.get(row, "manufacturer")

        graph = ProductFactGraph(product_id=mpn or str(index), source_row=dict(row))
        graph.family_id = family_signature(mpn, desc, supplier)

        # 1. identity ------------------------------------------------------
        res = resolve_identity(
            self.registry, mpn=mpn, description=desc, supplier=supplier,
            dib_brand=schema.get(row, "brand_dib"),
            e1_brand=schema.get(row, "brand_e1"))
        for f in identity_facts(res):
            graph.add(f)
        mismatch = detect_mismatch(self.registry, res, supplier)
        if mismatch:
            graph.note(**mismatch)
        if res.method == "abstain":
            graph.note("brand_unresolved", res.detail, severity="review")

        # 2. deterministic parse -------------------------------------------
        stripped, mpn_span = strip_mpn_echo(desc, mpn)
        if mpn:
            graph.add(Fact(key="mpn", value=mpn, label="Manufacturer Part Number",
                           method="input", rule_id="IDN-MPN-01", raw=mpn,
                           confidence=0.99, priority=3,
                           evidence=[Evidence(source="input:Mfg_Part_Num", text=mpn,
                                              detail="Supplied part number.")]))
        for f in parse_description(stripped):
            graph.add(f)

        # 3. item type ------------------------------------------------------
        brand_terms = [res.brand] + list(res.entry.aliases if res.entry else ())
        residual = strip_terms(residual_text(stripped, graph.facts()), brand_terms)
        item_type = ""
        if self.lexicon:
            hit = self.lexicon.resolve(residual, self.vocab)
            if hit:
                item_type, matched, conf = hit
                graph.add(Fact(
                    key="item_type", value=item_type, label="Item Type",
                    method="rule", rule_id="ITM-LEX-01", raw=matched,
                    confidence=conf, priority=5,
                    evidence=[Evidence(
                        source="input:Part_Desc", text=matched,
                        detail="Resolved against the item-type vocabulary "
                               "induced from this catalogue ({} occurrences)."
                               .format(self.vocab.get(matched, 0)))]))
        if not item_type:
            # Nothing in the text names the item -- try to infer it from which
            # attributes co-occur. Recorded as an inference, not an extraction.
            inf = infer_item_type(graph.keys())
            if inf:
                name, rule_id, supporting = inf
                item_type = name
                graph.add(Fact(
                    key="item_type", value=name, label="Item Type",
                    method="inferred", rule_id=rule_id, raw="", confidence=0.78,
                    priority=5,
                    evidence=[Evidence(
                        source="rule:{}".format(rule_id), text=", ".join(supporting),
                        detail="Item type inferred from co-occurring attributes "
                               "({}); the description never names the item."
                               .format(", ".join(supporting)))]))
            else:
                graph.note("item_type_unresolved",
                           "No item type could be resolved from {!r}.".format(residual),
                           severity="review")

        # Lamp technology is an attribute, not an item type.
        for tech, label in (("led", "LED"), ("incandescent", "Incandescent"),
                            ("cfl", "CFL"), ("halogen", "Halogen")):
            m = re.search(r"(?<![A-Za-z])" + tech + r"(?![A-Za-z])", desc, re.I)
            if m:
                graph.add(Fact(
                    key="lamp_type", value=label, label="Lamp Type", method="rule",
                    rule_id="LMP-TEC-01", raw=m.group(0), confidence=0.9, priority=29,
                    evidence=[Evidence(source="input:Part_Desc", text=m.group(0),
                                       span=m.span(),
                                       detail="Lamp technology captured as an "
                                              "attribute rather than an item type.")]))
                break

        # 4. series ---------------------------------------------------------
        ser = detect_series(residual, item_type, res.brand, self.series_vocab)
        if ser:
            name, matched = ser
            graph.add(Fact(key="series", value=name, label="Series", method="rule",
                           rule_id="SER-CAP-01", raw=matched, confidence=0.72,
                           priority=10,
                           evidence=[Evidence(source="input:Part_Desc", text=matched,
                                              detail="Capitalised collection name "
                                                     "left after brand and item "
                                                     "type were removed.")]))

        # 5. taxonomy -------------------------------------------------------
        c = classify(item_type, desc)
        if c.node:
            for f in taxonomy_facts(c, "input:Part_Desc", item_type or desc):
                graph.add(f)
        else:
            graph.note("classification_abstained", c.reason, severity="review")

        # 6. optional model fill -------------------------------------------
        # Deterministic-first routing: the model is only paid for on rows the
        # rules could not resolve. On this catalogue that is roughly a third of
        # them, so cost scales with difficulty rather than with catalogue size.
        if self.llm is not None and self._needs_model(graph, item_type, c):
            self.llm_invoked += 1
            self._llm_fill(graph, residual, desc)
            # The model is the last extractor to run, so anything it recovers
            # arrives after classification. Re-classify when it supplied the
            # item type the rules could not find -- otherwise the model's best
            # contribution never reaches the taxonomy.
            recovered = graph.raw_value("item_type")
            if recovered and not graph.has("classpath"):
                c_llm = classify(str(recovered), desc)
                if c_llm.node:
                    for f in taxonomy_facts(c_llm, "llm:item_type", str(recovered)):
                        graph.add(f)
                    c = c_llm

        # 7. reviewer corrections -- highest authority in the system -------
        if self.corrections.apply(graph, mpn):
            # A corrected item type has to be re-classified, otherwise the
            # reviewer fixes the name and the row still has no classpath.
            corrected_type = graph.raw_value("item_type")
            if corrected_type and not graph.has("classpath"):
                c2 = classify(str(corrected_type), desc)
                if c2.node:
                    for f in taxonomy_facts(c2, "correction:item_type",
                                            str(corrected_type)):
                        graph.add(f)
                    c = c2

        # 8. physical and logical guardrails --------------------------------
        apply_guardrails(graph)

        # 9. model audit -- a second opinion on facts that already exist ----
        # The auditor cannot create a value, only agree or disagree with one.
        # Agreement is what raises confidence; disagreement routes to review.
        if self.auditor is not None:
            self._audit(graph, desc)

        return self._finalise(graph, row, schema, index, c)

    def _audit(self, graph: ProductFactGraph, desc: str) -> None:
        from .llm.audit import apply_verdicts, auditable_facts
        facts = auditable_facts(graph)
        if not facts:
            return
        try:
            out = self.auditor({
                "description": desc,
                "facts": [{"key": f.key, "label": f.label, "value": f.display}
                          for f in facts]})
        except Exception as exc:
            graph.note("audit_error", "Audit call failed: {}".format(exc),
                       severity="info")
            return
        verdicts = (out or {}).get("verdicts", [])
        counts = apply_verdicts(graph, verdicts, model_name="audit")
        self.audited += 1
        for k, v in counts.items():
            self.audit_counts[k] = self.audit_counts.get(k, 0) + v

    @staticmethod
    def _needs_model(graph: ProductFactGraph, item_type: str, c) -> bool:
        """True when the deterministic layer left a gap worth spending a call on."""
        if not item_type:
            return True
        if c is None or c.node is None:
            return True
        if not graph.has("brand"):
            return True
        substantive = [f for f in graph.facts()
                       if f.key not in ("mpn", "brand", "manufacturer", "dept",
                                        "class", "fine", "classpath", "unspsc",
                                        "item_type")]
        return len(substantive) < 3

    def _llm_fill(self, graph: ProductFactGraph, residual: str, desc: str) -> None:
        """Hand the model only what the rules could not reach.

        The contract is strict: the model returns candidate values *with the
        substring of the input that supports each one*. A candidate whose quoted
        evidence is not actually present in the source is discarded, not stored.
        """
        try:
            proposal = self.llm({
                "description": desc, "residual": residual,
                "known": {f.key: f.display for f in graph.facts()},
            })
        except Exception as exc:                      # never let the model break a run
            graph.note("llm_error", "Model call failed: {}".format(exc),
                       severity="info")
            return
        expanded = expand_abbreviations(desc)
        for item in (proposal or {}).get("facts", []):
            key = str(item.get("key") or "").strip()
            value = item.get("value")
            quote = str(item.get("evidence") or "")
            if not key or value in (None, ""):
                continue

            # The firewall accepts a quote that matches the source either
            # literally, or after the documented trade-abbreviation expansion
            # ("Kichler Wall Lt" -> "Kichler Wall Light"). Expanding a known
            # abbreviation is a rule we already own, not a model invention.
            # Anything else is discarded rather than stored.
            grounded, via = False, ""
            if quote:
                if quote.lower() in desc.lower():
                    grounded, via = True, "literal"
                elif quote.lower() in expanded.lower():
                    grounded, via = True, "abbreviation-expanded"
            if quote and not grounded:
                graph.note("llm_evidence_rejected",
                           "Discarded {}={!r}: quoted evidence {!r} is not present "
                           "in the source text.".format(key, value, quote),
                           severity="info")
                continue
            span = None
            if quote and via == "literal":
                i = desc.lower().find(quote.lower())
                span = (i, i + len(quote)) if i >= 0 else None
            graph.add(Fact(
                key=key, value=value, label=str(item.get("label") or "").strip(),
                uom=str(item.get("uom") or "").strip(), method="llm",
                rule_id="LLM-EXT-01", raw=quote,
                confidence=float(item.get("confidence") or 0.7), priority=45,
                evidence=[Evidence(source="input:Part_Desc", text=quote, span=span,
                                   detail="Model proposal, verified {} against the "
                                          "source text.".format(via or "literal"))]))

    # -- rendering ---------------------------------------------------------
    def _finalise(self, graph: ProductFactGraph, row: Dict[str, str],
                  schema: InputSchema, index: int, c) -> RowResult:
        out = blank_delivery_row()
        prov: Dict[str, Dict[str, Any]] = {}

        def put(col: str, value: Any, fact: Optional[Fact] = None,
                method: str = "", detail: str = "", conf: float = 0.0) -> None:
            if value in (None, ""):
                return
            text = str(value)
            rule = FIELD_RULES.get(col)
            if rule:
                text = enforce_casing(text, rule.casing)
                text = clip(text, rule.max_len)
            out[col] = text
            prov[col] = {
                "value": text,
                "method": method or (fact.method if fact else "compose"),
                "confidence": round(conf or (fact.confidence if fact else 0.85), 4),
                "rule_id": (fact.rule_id if fact else ""),
                "detail": detail or (fact.evidence[0].detail if fact and fact.evidence else ""),
                "evidence": [e.to_dict() for e in fact.evidence] if fact else [],
            }

        # -- pass-through of the supplier's own columns --------------------
        for role, col in (("mpn", "Mfg_Part_Num"), ("description", "Part_Desc"),
                          ("brand_e1", "E1_Brand"), ("brand_unilog", "Unilog_Brand"),
                          ("brand_dib", "DIB_Brand"), ("manufacturer", "Part_Manuf"),
                          ("sku", "SKU - MY_PART_NUMBER"), ("dept", "Dept"),
                          ("class", "Class"), ("fine", "Fine")):
            raw = schema.raw(row, role)
            if raw:
                put(col, raw, method="input", conf=0.99,
                    detail="Preserved verbatim from the source file.")

        # -- identity -------------------------------------------------------
        # PART_NUMBER is the distributor's internal identifier (the labelled
        # rows carry values like 20887830), not the manufacturer part number.
        # Nothing in a supplier row derives it, so it stays empty.
        for key, col in (("mpn", "MANUFACTURER_PART_NUMBER"),
                         ("brand", "BRAND_NAME"), ("manufacturer", "MANUFACTURER_NAME"),
                         ("classpath", "Classpath")):
            f = graph.get(key)
            if f:
                put(col, f.display, f)

        # Taxonomy overrides the supplied Dept/Class/Fine only when absent.
        for key, col in (("dept", "Dept"), ("class", "Class"), ("fine", "Fine")):
            f = graph.get(key)
            if f and not out.get(col):
                put(col, f.display, f)

        # -- descriptions ----------------------------------------------------
        spec = self.specs.get(graph.value("classpath") or "UNCLASSIFIED")
        spec_keys = spec.title_order if spec else []

        budget = build_invoice_desc(graph, limit=40)
        put("INVOICE_DESC", budget.text, method="compose", conf=0.9,
            detail="Budget solver fitted {} facts into {}/{} characters{}."
                   .format(len(budget.included), budget.used, budget.limit,
                           "; compressed " + "; ".join(budget.compressions)
                           if budget.compressions else ""))
        put("MOBILE_DESC", build_mobile_desc(graph), method="compose", conf=0.88,
            detail="Identity line sized into the 60-80 character window.")
        put("SHORT_DESC", build_short_desc(graph, spec_keys), method="compose",
            conf=0.88, detail="Title formula: brand + series + model + item type "
                              "+ differentiators.")
        put("RETAIL_DESC", build_retail_desc(graph, spec_keys), method="compose",
            conf=0.85, detail="Shelf line: series + item type + differentiators.")
        put("LONG_DESC1", build_long_desc(graph, spec_keys), method="compose",
            conf=0.85, detail="Every captured attribute rendered in specification "
                              "order.")
        put("Product Name", build_product_name(graph), graph.get("item_type"))
        wf = graph.get("with_feature")
        if wf:
            put("With", wf.display, wf)

        # -- attribute triples ----------------------------------------------
        skip = {"brand", "manufacturer", "mpn", "classpath", "dept", "class",
                "fine", "unspsc", "item_type", "with_feature"}

        # The delivery format is *positional*: the published ground truth keeps
        # an attribute's LABEL slot even when its value is blank, because the
        # slot list is the category specification. So the induced spec drives
        # the slot layout, and facts fill in the values they can. Declaring the
        # attribute is not the same as claiming a value for it.
        slot = 0
        emitted: set = set()
        pack = self.packs.get(graph.value("classpath"))
        if pack is not None and pack.slots:
            # A learned pack states the category's slot order outright, so it
            # takes precedence over the statistically induced spec.
            for ps in sorted(pack.slots, key=lambda x: x.position):
                if slot >= MAX_ATTRIBUTES:
                    break
                slot += 1
                fkey = resolve_slot_key(ps)
                if fkey:
                    emitted.add(fkey)
                put("ATTRIBUTE_LABEL {}".format(slot), ps.label,
                    method="pack", conf=0.95,
                    detail="Slot {} of the '{}' specification learned from {} "
                           "labelled row(s) in {}.".format(
                               ps.position, pack.classpath, pack.rows,
                               pack.source or "the labelled file"))
                f = graph.get(fkey) if fkey else None
                if f and f.display:
                    put("ATTRIBUTE_VALUE {}".format(slot), str(f.value), f)
                    if f.uom or ps.uom:
                        put("ATTRIBUTE_UOM {}".format(slot), f.uom or ps.uom, f)
        elif spec is not None:
            for a in spec.attributes:
                if a.key in skip or slot >= MAX_ATTRIBUTES:
                    continue
                slot += 1
                emitted.add(a.key)
                f = graph.get(a.key)
                put("ATTRIBUTE_LABEL {}".format(slot), a.label,
                    method="spec", conf=0.9,
                    detail="Attribute slot {} of the specification induced for {} "
                           "({} rows, populated in {:.0%} of them)."
                           .format(slot, spec.label, spec.n_rows, a.fill_rate))
                if f and f.display:
                    put("ATTRIBUTE_VALUE {}".format(slot), str(f.value), f)
                    if f.uom:
                        put("ATTRIBUTE_UOM {}".format(slot), f.uom, f)

        # Anything captured that the spec did not anticipate still gets a slot.
        ordered = graph.ordered(spec_keys) if spec_keys else []
        rest = [f for f in graph.ordered() if f not in ordered]
        for f in ordered + rest:
            if (f.key in skip or f.key in emitted or not f.display
                    or slot >= MAX_ATTRIBUTES):
                continue
            slot += 1
            emitted.add(f.key)
            put("ATTRIBUTE_LABEL {}".format(slot), f.label, f)
            put("ATTRIBUTE_VALUE {}".format(slot), str(f.value), f)
            if f.uom:
                put("ATTRIBUTE_UOM {}".format(slot), f.uom, f)

        f = graph.get("unspsc")
        if f:
            put("UNSPSC", f.display, f)
        f = graph.get("selling_qty")
        if f:
            put("Selling Qty", f.display, f)
        f = graph.get("selling_uom")
        if f:
            put("Selling UOM", f.display, f)

        # -- asset naming convention (off by default) ------------------------
        if self.emit_asset_conventions and graph.has("brand") and graph.has("mpn"):
            stem = "{}_{}".format(
                re.sub(r"[^A-Za-z0-9]+", "", graph.raw_value("brand")),
                re.sub(r"[^A-Za-z0-9\-]+", "", str(graph.raw_value("mpn"))))
            put("Product Image", stem + ".jpg", method="convention", conf=0.35,
                detail="Derived from the brand/part-number asset naming "
                       "convention. NOT verified against a real file -- routed "
                       "to review.")

        result = RowResult(index=index, graph=graph, delivery=out, provenance=prov)
        result.invoice_budget = budget.to_dict()
        result.filled = sum(1 for v in out.values() if str(v).strip())
        result.flags = list(graph.notes)
        self._validate(result)
        return result

    # -- validation --------------------------------------------------------
    def _validate(self, r: RowResult) -> None:
        for col, rule in FIELD_RULES.items():
            v = r.delivery.get(col, "")
            if not v:
                continue
            if rule.max_len and len(v) > rule.max_len:
                r.violations.append({
                    "column": col, "rule_id": rule.rule_id, "severity": "error",
                    "message": "{} is {} characters, limit {}.".format(
                        col, len(v), rule.max_len)})
            if rule.min_len and len(v) < rule.min_len:
                r.violations.append({
                    "column": col, "rule_id": rule.rule_id, "severity": "warning",
                    "message": "{} is {} characters, minimum {}.".format(
                        col, len(v), rule.min_len)})
            if rule.casing == "upper" and v != v.upper():
                r.violations.append({
                    "column": col, "rule_id": rule.rule_id, "severity": "error",
                    "message": "{} must be upper case.".format(col)})

        if not r.delivery.get("Classpath"):
            r.violations.append({
                "column": "Classpath", "rule_id": "CG-TAX-01", "severity": "error",
                "message": "Unclassified: attribute validation cannot be keyed."})
        if not r.delivery.get("BRAND_NAME"):
            r.violations.append({
                "column": "BRAND_NAME", "rule_id": "CG-BRD-01", "severity": "error",
                "message": "No approved brand resolved."})

        errors = [v for v in r.violations if v["severity"] == "error"]
        review = [f for f in r.flags if f.get("severity") == "review"] + \
                 [f for f in r.flags if f.get("kind") == "brand_manufacturer_mismatch"]
        if errors:
            r.status = "blocked"
        elif review or r.graph.score() < 0.75:
            r.status = "needs_review"
        else:
            r.status = "ready"

    # -- family consensus --------------------------------------------------
    #: Facts that are properties of the *product concept*, so a sibling may
    #: legitimately inherit them. Dimensional facts are excluded on purpose --
    #: those are exactly what varies inside a family.
    FAMILY_INVARIANT = ("item_type", "classpath", "dept", "class", "fine",
                        "unspsc", "brand", "manufacturer", "series", "material",
                        "application", "lamp_type", "platform")

    def propagate_families(self, results: Sequence[RowResult],
                           min_support: int = 2) -> int:
        """Fill gaps from corroborated family consensus.

        A value propagates only when at least ``min_support`` siblings
        independently produced it and no sibling contradicts it. Copying one
        row's guess onto twenty others would manufacture correlated errors that
        then look like agreement -- so this is consensus, not copying, and the
        provenance records the vote.
        """
        groups: Dict[str, List[RowResult]] = defaultdict(list)
        for r in results:
            groups[r.graph.family_id].append(r)

        filled = 0
        for fid, members in groups.items():
            if len(members) < 2:
                continue
            for key in self.FAMILY_INVARIANT:
                votes: Counter = Counter()
                for m in members:
                    f = m.graph.get(key)
                    if f and f.display:
                        votes[f.display] += 1
                if not votes:
                    continue
                value, n = votes.most_common(1)[0]
                if n < min_support:
                    continue
                if len(votes) > 1:
                    continue           # siblings disagree -- do not propagate
                for m in members:
                    if m.graph.has(key):
                        continue
                    m.graph.add(Fact(
                        key=key, value=value,
                        label=key.replace("_", " ").title(),
                        method="family", rule_id="FAM-CON-01", raw=value,
                        confidence=min(0.88, 0.60 + 0.05 * n), priority=12,
                        evidence=[Evidence(
                            source="family:{}".format(fid), text=value,
                            detail="Inherited from family consensus: {} of {} "
                                   "siblings independently produced this value "
                                   "and none contradicted it."
                                   .format(n, len(members)))]))
                    filled += 1
        return filled

    def detect_family_anomalies(self, results: Sequence[RowResult]) -> int:
        """Flag siblings that break their family's pattern.

        A row whose invariant disagrees with a strong family majority is
        usually an error in the *source* catalogue, not in the extraction.
        """
        groups: Dict[str, List[RowResult]] = defaultdict(list)
        for r in results:
            groups[r.graph.family_id].append(r)
        found = 0
        for fid, members in groups.items():
            if len(members) < 4:
                continue
            for key in ("brand", "item_type", "classpath"):
                votes: Counter = Counter()
                for m in members:
                    f = m.graph.get(key)
                    if f and f.display:
                        votes[f.display] += 1
                if len(votes) < 2:
                    continue
                (top, n), = votes.most_common(1)
                if n / max(1, sum(votes.values())) < 0.75:
                    continue
                for m in members:
                    f = m.graph.get(key)
                    if f and f.display and f.display != top:
                        m.graph.note(
                            "family_anomaly",
                            "{} is {!r} but {} of {} siblings in family {} say "
                            "{!r}. Likely a defect in the source catalogue."
                            .format(key, f.display, n, len(members), fid, top),
                            severity="review")
                        found += 1
        return found

    # -- run ---------------------------------------------------------------
    def run(self, rows: Sequence[Dict[str, str]],
            schema: Optional[InputSchema] = None,
            progress: Optional[Callable[[int, int], None]] = None
            ) -> Tuple[List[RowResult], PipelineReport]:
        t0 = time.time()
        schema = schema or detect_schema(list(rows[0].keys()) if rows else [], rows)
        self.corrections.reset_counts()
        self.edges = []
        self.fit(rows, schema)

        results: List[RowResult] = []
        for i, row in enumerate(rows):
            results.append(self.process_row(row, schema, index=i))
            if progress and (i % 25 == 0 or i == len(rows) - 1):
                progress(i + 1, len(rows))

        # Cross-row pass: consensus fills gaps, disagreement raises flags.
        # Both need the whole catalogue, so they cannot run row-at-a-time.
        inherited = self.propagate_families(results)
        anomalies = self.detect_family_anomalies(results)
        if inherited or anomalies:
            for r in results:
                rebuilt = self._finalise(r.graph, r.graph.source_row, schema,
                                         r.index, None)
                r.delivery, r.provenance = rebuilt.delivery, rebuilt.provenance
                r.violations, r.flags = rebuilt.violations, rebuilt.flags
                r.filled, r.status = rebuilt.filled, rebuilt.status
                r.invoice_budget = rebuilt.invoice_budget

        # Relationship graph: derived from facts, so it runs once everything
        # has been extracted and corroborated.
        nodes = [knowledge.Node(r.index, r.delivery.get("Mfg_Part_Num", ""),
                                r.graph) for r in results]
        self.edges = knowledge.build_graph(nodes)

        rep = PipelineReport(n_rows=len(rows), elapsed_s=round(time.time() - t0, 3))
        rep.knowledge = knowledge.summarise(self.edges, nodes)
        rep.corrections = self.corrections.summary()
        rep.guardrail_findings = dict(Counter(
            f.get("kind_id", f.get("kind", "")) for r in results
            for f in r.flags if f.get("guardrail")))
        rep.family_inherited = inherited
        rep.family_anomalies = anomalies
        try:
            from .llm.provider import Stats as _S
            rep.ai_degraded = bool(_S.exhausted)
            rep.ai_notice = _S.exhausted_reason
            # `llm_invoked` counts rows the gate selected for a model pass.
            # Once the breaker trips those calls short-circuit, so the number
            # that actually reached a model is calls + cache hits, not the
            # number selected. Reporting the former as the latter would
            # overstate the model's contribution.
            rep.llm_served = _S.calls
            rep.llm_cached = _S.cache_hits
        except Exception:
            pass
        rep.llm_invoked = self.llm_invoked
        rep.audited_rows = self.audited
        rep.audit_counts = dict(self.audit_counts)
        rep.schema = schema.to_dict()
        rep.families = len({r.graph.family_id for r in results})
        rep.specs = [s.to_dict() for s in sorted(
            self.specs.values(), key=lambda s: -s.n_rows)]
        rep.status_counts = dict(Counter(r.status for r in results))
        rep.flag_counts = dict(Counter(f.get("kind", "?") for r in results for f in r.flags))
        rep.violation_counts = dict(Counter(
            v["rule_id"] for r in results for v in r.violations))
        if results:
            rep.mean_columns_filled = round(
                sum(r.filled for r in results) / len(results), 2)
            rep.fill_rate = round(rep.mean_columns_filled / len(DELIVERY_COLUMNS), 4)
            rep.brand_resolution = round(
                sum(1 for r in results if r.delivery.get("BRAND_NAME")) / len(results), 4)
            rep.classification_rate = round(
                sum(1 for r in results if r.delivery.get("Classpath")) / len(results), 4)
            comp: Dict[str, float] = {}
            for col in ("INVOICE_DESC", "MOBILE_DESC", "SHORT_DESC"):
                rule = FIELD_RULES.get(col)
                vals = [r.delivery.get(col, "") for r in results]
                vals = [v for v in vals if v]
                if not vals or not rule:
                    continue
                ok = sum(1 for v in vals
                         if (rule.max_len is None or len(v) <= rule.max_len)
                         and (rule.min_len is None or len(v) >= rule.min_len))
                comp[col] = round(ok / len(vals), 4)
            rep.char_compliance = comp
        return results, rep
