"""Persisted human corrections.

A review queue that ranks work but forgets the answer makes a steward solve the
same problem every run. This module closes that loop without fine-tuning
anything: a correction is stored as a durable, scoped fact and replayed on
every subsequent run.

Scope is what makes it compound:

* ``part``   -- applies to one part number
* ``family`` -- applies to every sibling in a product family
* ``brand``  -- teaches the registry a supplier-string alias, so *every* row
                from that supplier resolves correctly from then on

The catalogue's largest family holds 65 rows, so one scoped decision can fix 65
SKUs; one brand alias can fix over a hundred. Corrections enter the fact graph
through the same door as everything else -- as facts with evidence naming the
person who made the call -- so a human decision is as auditable as a rule.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .facts import Evidence, Fact, ProductFactGraph

DEFAULT_PATH = os.path.join("data", "corrections.json")

SCOPES = ("part", "family", "classpath", "brand")


@dataclass
class Correction:
    scope: str                 # part | family | classpath | brand
    target: str                # part number, family id, classpath, or supplier string
    key: str                   # fact key, or 'brand_alias' when scope == 'brand'
    value: str
    uom: str = ""
    note: str = ""
    by: str = "reviewer"
    at: str = ""
    applied: int = 0           # rows affected on the last run

    def __post_init__(self) -> None:
        if not self.at:
            self.at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CorrectionStore:
    """Durable set of scoped corrections, replayed on every run."""

    def __init__(self, corrections: Optional[List[Correction]] = None,
                 path: str = DEFAULT_PATH):
        self.path = path
        self.corrections: List[Correction] = corrections or []

    # -- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path: str = DEFAULT_PATH) -> "CorrectionStore":
        if not path or not os.path.exists(path):
            return cls(path=path)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return cls(path=path)
        out = []
        for d in data.get("corrections", []):
            try:
                out.append(Correction(**d))
            except TypeError:
                continue
        return cls(out, path=path)

    def save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".",
                    exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"corrections": [c.to_dict() for c in self.corrections]},
                      fh, indent=2)

    def add(self, correction: Correction) -> Correction:
        """Add or replace a correction with the same scope/target/key."""
        self.corrections = [
            c for c in self.corrections
            if not (c.scope == correction.scope and c.target == correction.target
                    and c.key == correction.key)]
        self.corrections.append(correction)
        return correction

    def remove(self, scope: str, target: str, key: str) -> int:
        before = len(self.corrections)
        self.corrections = [
            c for c in self.corrections
            if not (c.scope == scope and c.target == target and c.key == key)]
        return before - len(self.corrections)

    # -- indexing ----------------------------------------------------------
    def by_scope(self, scope: str) -> Dict[str, List[Correction]]:
        out: Dict[str, List[Correction]] = {}
        for c in self.corrections:
            if c.scope == scope:
                out.setdefault(str(c.target).strip().lower(), []).append(c)
        return out

    def brand_aliases(self) -> Dict[str, str]:
        """Supplier string -> approved brand, taught by a reviewer."""
        return {str(c.target).strip().lower(): c.value
                for c in self.corrections if c.scope == "brand"}

    def reset_counts(self) -> None:
        for c in self.corrections:
            c.applied = 0

    # -- application -------------------------------------------------------
    def apply(self, graph: ProductFactGraph, part_number: str) -> int:
        """Overlay corrections onto one product's fact graph.

        Corrections carry the highest confidence in the system -- above rules,
        registries and the model -- because a person looked at the row and
        decided. They are still facts with evidence, not silent overwrites.
        """
        applied = 0
        pn = str(part_number or "").strip().lower()
        cp = str(graph.raw_value("classpath") or "").strip().lower()
        fam = str(graph.family_id or "").strip().lower()

        targets = (
            (self.by_scope("part").get(pn) or []) +
            (self.by_scope("family").get(fam) or []) +
            (self.by_scope("classpath").get(cp) or [])
        )
        for c in targets:
            if c.key in ("brand_alias",):
                continue
            existing = graph.get(c.key)
            if existing is not None and existing.method == "correction":
                continue
            fact = Fact(
                key=c.key, value=c.value,
                label=c.key.replace("_", " ").title(),
                uom=c.uom, method="correction", rule_id="HITL-COR-01",
                raw=c.value, confidence=0.99, priority=4,
                evidence=[Evidence(
                    source="correction:{}".format(c.scope),
                    text=c.value,
                    detail="Reviewer decision recorded {} by {} (scope: {} = "
                           "{}).{}".format(c.at, c.by, c.scope, c.target,
                                           " " + c.note if c.note else ""))])
            # A correction supersedes whatever was there.
            if existing is not None:
                graph._facts.pop(c.key, None)          # deliberate override
                fact.conflicts.append({
                    "value": existing.value, "uom": existing.uom,
                    "method": existing.method, "rule_id": existing.rule_id,
                    "confidence": round(existing.confidence, 4),
                    "evidence": [e.to_dict() for e in existing.evidence],
                })
            graph.add(fact)
            c.applied += 1
            applied += 1
        return applied

    # -- reporting ---------------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        by_scope: Dict[str, int] = {}
        for c in self.corrections:
            by_scope[c.scope] = by_scope.get(c.scope, 0) + 1
        total_rows = sum(c.applied for c in self.corrections)
        leverage = round(total_rows / max(1, len(self.corrections)), 2)
        return {
            "corrections": len(self.corrections),
            "by_scope": by_scope,
            "rows_affected": total_rows,
            "rows_per_correction": leverage,
            "items": sorted((c.to_dict() for c in self.corrections),
                            key=lambda d: -d["applied"]),
        }


CORRECTION_COLUMNS = ["scope", "target", "key", "value", "uom", "applied",
                      "by", "at", "note"]
