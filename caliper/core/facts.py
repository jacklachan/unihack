"""The Product Fact Graph.

This module defines the only object in CALIPER that may hold a product value.
Extractors (rules, registries, the LLM, family consensus, fetched documents)
*write* facts here. Composition, validation and export only ever *read*.

That one-way boundary is the whole design:

* a value cannot reach an output cell without a Fact behind it;
* a Fact cannot exist without at least one Evidence pointing at real input
  text, a named registry entry, or a cited source;
* when two independent methods produce the same value we record the
  *agreement*, and agreement -- not a hand-tuned constant -- is what drives
  the confidence we later calibrate against ground truth.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Method taxonomy. Ordered weakest -> strongest as a tie-break prior only;
# real confidence comes from agreement + calibration, not from this table.
# ---------------------------------------------------------------------------
METHOD_PRIOR: Dict[str, float] = {
    "input": 0.99,       # copied verbatim from a source column
    "registry": 0.94,    # matched an approved master-data entry
    "rule": 0.92,        # deterministic pattern with an explicit rule id
    "document": 0.88,    # parsed from a fetched manufacturer document
    "family": 0.78,      # inherited from corroborated family consensus
    "llm": 0.70,         # model proposal, must carry an evidence span
    "inferred": 0.62,    # derived, not literally present in any source
}

#: Methods that count as independent for agreement purposes. Two facts from
#: the same method family do not corroborate each other.
INDEPENDENCE_CLASS: Dict[str, str] = {
    "input": "source",
    "registry": "master",
    "rule": "pattern",
    "document": "source",
    "family": "consensus",
    "llm": "model",
    "inferred": "pattern",
}


@dataclass
class Evidence:
    """Why a value is believed. Never optional -- a Fact without Evidence is
    rejected by :meth:`ProductFactGraph.add`."""

    source: str                       # 'input:Part_Desc', 'registry:manufacturers', 'web:https://...'
    text: str = ""                    # the literal snippet that justifies the value
    span: Optional[Tuple[int, int]] = None   # char offsets into `source` when applicable
    detail: str = ""                  # human-readable note shown in the evidence panel

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["span"] = list(self.span) if self.span else None
        return d


@dataclass
class Fact:
    """A single typed, evidenced claim about a product."""

    key: str                          # canonical key, e.g. 'voltage'
    value: Any                        # normalised value
    label: str = ""                   # display label, e.g. 'Voltage Rating'
    uom: str = ""                     # approved UOM abbreviation, e.g. 'V'
    method: str = "rule"
    rule_id: str = ""
    raw: str = ""                     # the unnormalised text the value came from
    confidence: float = 0.0
    priority: int = 50                # lower = more important for char budgeting
    evidence: List[Evidence] = field(default_factory=list)
    agreed_by: List[str] = field(default_factory=list)   # independence classes that concur
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    inferred: bool = False            # True when not literally present in any source

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.key.replace("_", " ").title()
        if not self.confidence:
            self.confidence = METHOD_PRIOR.get(self.method, 0.6)
        if self.method == "inferred":
            self.inferred = True

    # -- rendering helpers -------------------------------------------------
    @property
    def display(self) -> str:
        """Value plus approved unit, with the mandated space between them."""
        v = "" if self.value is None else str(self.value).strip()
        if self.uom and v:
            return "{} {}".format(v, self.uom)
        return v

    @property
    def independence(self) -> str:
        return INDEPENDENCE_CLASS.get(self.method, self.method)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "value": self.value,
            "uom": self.uom, "display": self.display, "method": self.method,
            "rule_id": self.rule_id, "raw": self.raw,
            "confidence": round(self.confidence, 4), "priority": self.priority,
            "inferred": self.inferred, "agreed_by": list(self.agreed_by),
            "conflicts": list(self.conflicts),
            "evidence": [e.to_dict() for e in self.evidence],
        }


# ---------------------------------------------------------------------------
# Agreement -> confidence.
# ---------------------------------------------------------------------------
#: Each additional *independent* method that produces the same value closes a
#: fraction of the remaining gap to 1.0. Calibrated later against ground truth;
#: this is the prior, not the final answer.
AGREEMENT_GAIN = 0.55
#: A contradicted fact is penalised toward the review threshold.
CONFLICT_PENALTY = 0.35


def _norm_value(v: Any) -> str:
    """Loose comparison key so '24 in' and '24in' count as the same claim."""
    s = str(v if v is not None else "").strip().lower()
    s = re.sub(r"[\s_]+", "", s)
    s = re.sub(r"[^\w./\-]", "", s)
    return s


class ProductFactGraph:
    """Facts for one product, keyed by canonical attribute key.

    ``add`` is the only mutator. It performs three jobs: reject unevidenced
    claims, merge agreeing claims (raising confidence and recording who
    agreed), and record disagreeing claims as conflicts rather than silently
    overwriting them.
    """

    def __init__(self, product_id: str = "", source_row: Optional[Dict[str, str]] = None):
        self.product_id = product_id
        self.source_row: Dict[str, str] = dict(source_row or {})
        self._facts: Dict[str, Fact] = {}
        self._rejected: List[Dict[str, Any]] = []
        self.notes: List[Dict[str, Any]] = []
        self.family_id: str = ""

    # -- mutation ----------------------------------------------------------
    def add(self, fact: Fact) -> Optional[Fact]:
        """Insert or merge a fact. Returns the resident fact, or None if the
        claim was rejected for lack of evidence."""
        if not fact.evidence:
            self._rejected.append({
                "key": fact.key, "value": fact.value, "method": fact.method,
                "reason": "no evidence attached -- ungrounded values are never stored",
            })
            return None
        if fact.value is None or str(fact.value).strip() == "":
            return None

        existing = self._facts.get(fact.key)
        if existing is None:
            fact.agreed_by = [fact.independence]
            self._facts[fact.key] = fact
            return fact

        if _norm_value(existing.value) == _norm_value(fact.value):
            return self._corroborate(existing, fact)
        return self._contradict(existing, fact)

    def _corroborate(self, existing: Fact, incoming: Fact) -> Fact:
        """Same claim from a second source: raise confidence, merge evidence."""
        existing.evidence.extend(incoming.evidence)
        if incoming.independence not in existing.agreed_by:
            existing.agreed_by.append(incoming.independence)
            gap = 1.0 - existing.confidence
            existing.confidence = min(0.995, existing.confidence + gap * AGREEMENT_GAIN)
        else:
            existing.confidence = max(existing.confidence, incoming.confidence)
        # Prefer the richer normalisation if one carries a unit and the other doesn't.
        if not existing.uom and incoming.uom:
            existing.uom = incoming.uom
        if existing.method != "input" and incoming.method == "input":
            existing.method, existing.rule_id = incoming.method, incoming.rule_id
        return existing

    def _contradict(self, existing: Fact, incoming: Fact) -> Fact:
        """Different claims for the same key. Keep the stronger, remember both."""
        winner, loser = (existing, incoming)
        if incoming.confidence > existing.confidence + 1e-9:
            winner, loser = (incoming, existing)
            winner.agreed_by = winner.agreed_by or [winner.independence]
            winner.conflicts = existing.conflicts

        winner.conflicts.append({
            "value": loser.value, "uom": loser.uom, "method": loser.method,
            "rule_id": loser.rule_id, "confidence": round(loser.confidence, 4),
            "evidence": [e.to_dict() for e in loser.evidence],
        })
        winner.confidence = max(0.05, winner.confidence * (1.0 - CONFLICT_PENALTY))
        self._facts[winner.key] = winner
        return winner

    def note(self, kind: str, message: str, **extra: Any) -> None:
        """Record a pipeline observation (data-quality flag, abstention, gap)."""
        entry = {"kind": kind, "message": message}
        entry.update(extra)
        self.notes.append(entry)

    # -- access ------------------------------------------------------------
    def get(self, key: str) -> Optional[Fact]:
        return self._facts.get(key)

    def value(self, key: str, default: str = "") -> str:
        f = self._facts.get(key)
        return f.display if f else default

    def raw_value(self, key: str, default: Any = "") -> Any:
        f = self._facts.get(key)
        return f.value if f else default

    def has(self, key: str) -> bool:
        return key in self._facts

    def keys(self) -> List[str]:
        return list(self._facts.keys())

    def facts(self) -> List[Fact]:
        return list(self._facts.values())

    def ordered(self, keys: Optional[Iterable[str]] = None) -> List[Fact]:
        """Facts in composition order: explicit key order first, then priority."""
        if keys is not None:
            order = {k: i for i, k in enumerate(keys)}
            return sorted(
                (f for f in self._facts.values() if f.key in order),
                key=lambda f: order[f.key],
            )
        return sorted(self._facts.values(), key=lambda f: (f.priority, f.key))

    def confident(self, threshold: float) -> List[Fact]:
        return [f for f in self._facts.values() if f.confidence >= threshold]

    @property
    def rejected(self) -> List[Dict[str, Any]]:
        return list(self._rejected)

    @property
    def conflicted(self) -> List[Fact]:
        return [f for f in self._facts.values() if f.conflicts]

    def score(self) -> float:
        """Mean confidence across facts -- the row-level quality signal."""
        if not self._facts:
            return 0.0
        return sum(f.confidence for f in self._facts.values()) / len(self._facts)

    def fingerprint(self) -> str:
        payload = json.dumps(
            sorted((k, _norm_value(f.value)) for k, f in self._facts.items()),
            sort_keys=True,
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id,
            "family_id": self.family_id,
            "score": round(self.score(), 4),
            "fingerprint": self.fingerprint(),
            "facts": {k: f.to_dict() for k, f in self._facts.items()},
            "notes": list(self.notes),
            "rejected": self._rejected,
        }

    def __len__(self) -> int:
        return len(self._facts)

    def __repr__(self) -> str:
        return "<ProductFactGraph {} facts={} score={:.2f}>".format(
            self.product_id or "?", len(self._facts), self.score())


def make_fact(key: str, value: Any, source: str, text: str = "",
              span: Optional[Tuple[int, int]] = None, **kw: Any) -> Fact:
    """Convenience constructor that enforces the evidence requirement."""
    detail = kw.pop("detail", "")
    ev = Evidence(source=source, text=text or (str(value) if value is not None else ""),
                  span=span, detail=detail)
    return Fact(key=key, value=value, evidence=[ev], **kw)
