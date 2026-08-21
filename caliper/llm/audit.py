"""The model as auditor, not author.

Extraction asks a model to produce values, which is where hallucination enters.
Auditing inverts the relationship: the deterministic engines produce the facts,
and the model only renders a verdict on facts that already exist.

    SUPPORTED    the source text supports this value
    UNSUPPORTED  the source text contradicts it, or cannot support it
    UNKNOWN      the source is silent; no opinion

A verdict cannot create a value, so the audit pass has no path to inventing
anything. What it *can* do is disagree — and disagreement is the useful signal:

* a fact the rules produced **and** an independent model confirms has two
  methods behind it, and its confidence rises accordingly;
* a fact the model rejects keeps its value but loses confidence and is routed
  to human review, because a value two independent methods disagree about is
  exactly what a steward should look at.

This is also the calibration signal the review queue needs. Confidence stops
being a constant attached to a rule and starts being a measure of how much
independent agreement a value actually attracted.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..core.facts import Evidence, Fact, ProductFactGraph

AUDIT_SYSTEM = """You audit product-attribute extractions for an industrial catalogue.

You are shown a raw supplier description and a list of attributes that were
already extracted from it. For EACH attribute you return exactly one verdict:

  "supported"    - the description supports this value (directly, or through a
                   standard trade abbreviation such as SS = Stainless Steel,
                   Lt = Light, Milw = Milwaukee)
  "unsupported"  - the description contradicts the value, or plainly cannot
                   support it (e.g. the value refers to something absent)
  "unknown"      - the description is silent; you have no basis either way

HARD RULES
1. You may NOT add attributes. You may NOT change values. Verdicts only.
2. Judge only against the description shown. Do not use outside knowledge about
   the product, the brand, or the part number.
3. "unknown" is the correct answer far more often than people expect. Use it.
4. Return a verdict for every attribute you were given, keyed by its key.

Return STRICT JSON:
{"verdicts":[{"key":"snake_case","verdict":"supported|unsupported|unknown","reason":"short"}]}"""

#: Methods whose facts are already grounded in a character span, so auditing
#: them spends a call to re-confirm something that is not in doubt.
TRUSTED_METHODS = {"input", "correction"}

#: Keys never worth auditing: structural, or copied verbatim from the source.
SKIP_KEYS = {"mpn", "dept", "class", "fine", "classpath", "unspsc",
             "selling_uom", "display_only"}


def auditable_facts(graph: ProductFactGraph,
                    include_rules: bool = True) -> List[Fact]:
    """Which facts are worth spending an audit on."""
    out = []
    for f in graph.facts():
        if f.key in SKIP_KEYS or f.method in TRUSTED_METHODS:
            continue
        if not include_rules and f.method == "rule":
            continue
        if f.value in (None, ""):
            continue
        out.append(f)
    return out


def build_payload(description: str, facts: Sequence[Fact]) -> Dict[str, Any]:
    return {
        "description": description,
        "facts": [{"key": f.key, "label": f.label, "value": f.display}
                  for f in facts],
    }


def _extract(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.M)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return []
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    v = obj.get("verdicts", obj.get("results", [])) if isinstance(obj, dict) else obj
    return v if isinstance(v, list) else []


# ---------------------------------------------------------------------------
#: How much an independent confirmation closes the remaining confidence gap.
CONFIRM_GAIN = 0.5
#: How hard a rejection pushes a value toward review.
REJECT_FACTOR = 0.45


def apply_verdicts(graph: ProductFactGraph, verdicts: Sequence[Dict[str, Any]],
                   model_name: str = "audit") -> Dict[str, int]:
    """Fold audit verdicts into the fact graph.

    A verdict never edits a value. It adjusts confidence and, on disagreement,
    raises a review note naming both sides.
    """
    counts = {"supported": 0, "unsupported": 0, "unknown": 0}
    for v in verdicts:
        key = str(v.get("key") or "").strip()
        verdict = str(v.get("verdict") or "").strip().lower()
        reason = str(v.get("reason") or "").strip()
        f = graph.get(key)
        if not f or verdict not in counts:
            continue
        counts[verdict] += 1

        if verdict == "supported":
            # An independent method agreeing is what raises confidence here --
            # not a constant, but the agreement itself.
            if "model" not in f.agreed_by:
                f.agreed_by.append("model")
                gap = 1.0 - f.confidence
                f.confidence = min(0.99, f.confidence + gap * CONFIRM_GAIN)
            f.evidence.append(Evidence(
                source="audit:{}".format(model_name), text=f.display,
                detail="Independently confirmed against the source text."
                       + (" " + reason if reason else "")))
        elif verdict == "unsupported":
            f.confidence = max(0.05, f.confidence * REJECT_FACTOR)
            f.conflicts.append({
                "value": "(rejected by audit)", "method": "audit",
                "rule_id": "AUD-REJ-01", "confidence": 0.0,
                "evidence": [{"source": "audit:{}".format(model_name),
                              "text": reason, "span": None,
                              "detail": "Auditor found no support in the source."}],
            })
            graph.note(
                "audit_disagreement",
                "{} = {!r} was produced by {} but an independent audit found no "
                "support for it in the source text.{}".format(
                    f.label, f.display, f.method, " " + reason if reason else ""),
                severity="review", key=key)
    return counts


def make_auditor(provider_call: Callable[[Dict[str, Any]], Dict[str, Any]]
                 ) -> Callable[[str, Sequence[Fact]], List[Dict[str, Any]]]:
    """Wrap a raw provider callable into an auditor."""
    def audit(description: str, facts: Sequence[Fact]) -> List[Dict[str, Any]]:
        if not facts:
            return []
        payload = build_payload(description, facts)
        out = provider_call(payload)
        if isinstance(out, dict) and "verdicts" in out:
            return out["verdicts"]
        if isinstance(out, dict) and "facts" in out:
            return out["facts"]
        return []
    return audit
