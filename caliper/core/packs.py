"""Category packs: positional attribute specifications learned from labelled rows.

The delivery format is positional. A labelled dishwasher row carries fifteen
``ATTRIBUTE_LABEL`` slots in a fixed order -- Series, Model, Number of Wash
Cycles, Voltage Rating ... Additional Information -- and keeps the label even
when the value is blank, because that ordered list *is* the category
specification. Two labelled rows of the same category carry byte-identical
label sequences.

So when a labelled file exists, the specification does not have to be guessed.
This module reads it out, and -- more usefully -- **aligns each label to the
internal fact key that produces it**, by checking which extracted fact actually
matches the labelled value:

    truth "Voltage Rating" = "120" + UOM "V"
    fact  voltage          = "120 V"          -> label maps to key `voltage`

That alignment is learned from data rather than hand-written, so pointing
CALIPER at a labelled file for a category it has never seen produces a working
spec for that category.

Provenance note: labels sourced from a pack are recorded with method ``pack``
and the file they came from, so an evaluation can separate *given* structure
from *predicted* values and never claim credit for the former.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PACK_PATH = os.path.join(_HERE, "..", "refdata", "category_packs.json")

MAX_SLOTS = 50


def _norm(s: Any) -> str:
    t = str(s or "").strip().lower()
    t = t.replace("®", "").replace("™", "")
    t = re.sub(r"[^\w\s./-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _norm_value(s: Any) -> str:
    """Fold a value for comparison: '120' and '120 V' and '120V' all match."""
    t = _norm(s)
    t = re.sub(r"\s+", "", t)
    return t


@dataclass
class PackSlot:
    position: int
    label: str
    uom: str = ""
    key: str = ""                 # internal fact key, learned by alignment
    support: int = 0              # labelled rows agreeing on this slot
    value_support: int = 0        # rows where a fact matched the labelled value
    values: List[str] = field(default_factory=list)   # observed LOV

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CategoryPack:
    classpath: str
    rows: int = 0
    slots: List[PackSlot] = field(default_factory=list)
    source: str = ""
    description_formulas: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"classpath": self.classpath, "rows": self.rows,
                "source": self.source,
                "description_formulas": dict(self.description_formulas),
                "slots": [s.to_dict() for s in self.slots]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CategoryPack":
        p = cls(classpath=d.get("classpath", ""), rows=int(d.get("rows", 0)),
                source=d.get("source", ""),
                description_formulas=dict(d.get("description_formulas") or {}))
        p.slots = [PackSlot(**s) for s in d.get("slots", [])]
        return p


class PackLibrary:
    """All learned category packs, keyed by classpath."""

    def __init__(self, packs: Optional[Dict[str, CategoryPack]] = None):
        self.packs: Dict[str, CategoryPack] = packs or {}

    def get(self, classpath: str) -> Optional[CategoryPack]:
        if not classpath:
            return None
        p = self.packs.get(classpath)
        if p:
            return p
        n = _norm(classpath)
        for k, v in self.packs.items():
            if _norm(k) == n:
                return v
        return None

    def __len__(self) -> int:
        return len(self.packs)

    def save(self, path: str = DEFAULT_PACK_PATH) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"packs": [p.to_dict() for p in self.packs.values()]},
                      fh, indent=2)

    @classmethod
    def load(cls, path: str = DEFAULT_PACK_PATH) -> "PackLibrary":
        if not path or not os.path.exists(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return cls()
        packs = {}
        for d in data.get("packs", []):
            p = CategoryPack.from_dict(d)
            if p.classpath:
                packs[p.classpath] = p
        return cls(packs)


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------
def read_slots(row: Dict[str, str]) -> List[Tuple[int, str, str, str]]:
    """Extract ``(position, label, value, uom)`` for every populated label slot."""
    out = []
    for i in range(1, MAX_SLOTS + 1):
        lab = str(row.get("ATTRIBUTE_LABEL {}".format(i), "") or "").strip()
        if not lab:
            continue
        val = str(row.get("ATTRIBUTE_VALUE {}".format(i), "") or "").strip()
        uom = str(row.get("ATTRIBUTE_UOM {}".format(i), "") or "").strip()
        out.append((i, lab, val, uom))
    return out


def learn_packs(truth_rows: Sequence[Dict[str, str]],
                fact_lookup: Optional[Dict[str, Dict[str, str]]] = None,
                source: str = "") -> PackLibrary:
    """Build category packs from labelled delivery rows.

    ``fact_lookup`` maps a row key (part number) to ``{fact_key: display}`` as
    produced by the pipeline. When supplied, each labelled slot is aligned to
    the fact key whose value matches -- that is how a label learns which
    extractor feeds it.
    """
    by_class: Dict[str, List[Dict[str, str]]] = {}
    for r in truth_rows:
        cp = str(r.get("Classpath", "") or "").strip()
        if cp:
            by_class.setdefault(cp, []).append(r)

    lib = PackLibrary()
    for cp, rows in by_class.items():
        pack = CategoryPack(classpath=cp, rows=len(rows), source=source)
        # position -> label agreement
        slot_labels: Dict[int, Dict[str, int]] = {}
        slot_uoms: Dict[int, Dict[str, int]] = {}
        slot_values: Dict[int, List[str]] = {}
        slot_keys: Dict[int, Dict[str, int]] = {}

        for r in rows:
            facts = {}
            if fact_lookup:
                facts = fact_lookup.get(
                    str(r.get("Mfg_Part_Num", "")).strip(), {}) or {}
            for pos, lab, val, uom in read_slots(r):
                slot_labels.setdefault(pos, {})
                slot_labels[pos][lab] = slot_labels[pos].get(lab, 0) + 1
                if uom:
                    slot_uoms.setdefault(pos, {})
                    slot_uoms[pos][uom] = slot_uoms[pos].get(uom, 0) + 1
                if val:
                    slot_values.setdefault(pos, []).append(val)
                    # Align: which internal fact reproduces this labelled value?
                    target = _norm_value(val + uom)
                    target_bare = _norm_value(val)
                    for fk, fv in facts.items():
                        fvn = _norm_value(fv)
                        if fvn and (fvn == target or fvn == target_bare):
                            slot_keys.setdefault(pos, {})
                            slot_keys[pos][fk] = slot_keys[pos].get(fk, 0) + 1
                            break

        for pos in sorted(slot_labels):
            labs = slot_labels[pos]
            label = max(labs.items(), key=lambda x: x[1])[0]
            uoms = slot_uoms.get(pos, {})
            uom = max(uoms.items(), key=lambda x: x[1])[0] if uoms else ""
            keys = slot_keys.get(pos, {})
            key = max(keys.items(), key=lambda x: x[1])[0] if keys else ""
            vals = slot_values.get(pos, [])
            pack.slots.append(PackSlot(
                position=pos, label=label, uom=uom, key=key,
                support=labs[label], value_support=sum(keys.values()),
                values=sorted(set(vals))[:60]))
        lib.packs[cp] = pack
    return lib


#: Fallback alignment for labels no labelled row could align by value.
#: Deliberately small -- the point is that alignment is learned, and this only
#: covers labels whose value happened to be blank in every labelled row.
LABEL_KEY_HINTS: Dict[str, str] = {
    "series": "series",
    "model": "model",
    "voltage rating": "voltage",
    "amperage rating": "amperage",
    "wattage": "wattage",
    "sound level": "sound_level",
    "material": "material",
    "color": "finish",
    "colour": "finish",
    "size": "dimensions",
    "length": "length",
    "width": "width",
    "height": "height",
    "mounting type": "mounting",
    "number of wash cycles": "number_of_cycles",
    "plug type": "plug_type",
    "grit": "grit",
    "diameter": "diameter",
    "thickness": "thickness",
    "arbor size": "arbor_size",
    "color temperature": "color_temperature",
    "base type": "base_type",
    "bulb shape": "bulb_shape",
    "light output": "lumens",
    "horsepower": "horsepower",
    "phase": "phase",
    "pack quantity": "pack_quantity",
    "battery platform": "platform",
    "lamp type": "lamp_type",
    "application": "application",
    "additional information": "additional_information",
    "depth with door open": "depth_with_door_open",
    "minimum height": "minimum_height",
    "maximum height": "maximum_height",
}


def resolve_slot_key(slot: PackSlot) -> str:
    """Best internal key for a slot: learned alignment first, hint second."""
    if slot.key:
        return slot.key
    return LABEL_KEY_HINTS.get(_norm(slot.label), "")
