"""Product relationship graph.

Enrichment makes a part findable. Relationships make it *sellable*: the buyer
looking at a cordless ratchet needs the battery that fits it, and the buyer
holding a 4-1/2 in grinder needs to know which cut-off wheels have the right
arbor. In a distributor's economics that is attach rate, and it is the part of
product intelligence a flat 252-column sheet cannot express.

Every edge here is derived from facts the pipeline already extracted and
carries the same contract as a fact: a rule id, a confidence, and a rationale
naming the evidence. No edge is asserted because two products "seem related" --
if there is no shared platform, arbor, base type or dimension to point at, no
edge is written.

Blocking keeps this linear-ish: candidates are grouped by the attribute that
would license the edge, so only plausible pairs are ever compared.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .facts import ProductFactGraph

# ---------------------------------------------------------------------------
# Which item types play which role
# ---------------------------------------------------------------------------
POWER_SOURCE = re.compile(r"\b(battery|batteries|charger)\b", re.I)
CORDLESS_TOOL = re.compile(
    r"\b(drill|driver|ratchet|grinder|saw|sander|impact|wrench|trimmer|"
    r"blower|vacuum|nailer|light|flashlight)\b", re.I)
BONDED_ABRASIVE = re.compile(
    r"\b(cut off (disc|wheel)|grinding wheel|flap disc|sanding disc|blade)\b", re.I)
ARBOR_TOOL = re.compile(r"\b(grinder|saw|table saw|miter saw|circular saw)\b", re.I)
LAMP = re.compile(r"\b(bulb|lamp)\b", re.I)
LUMINAIRE = re.compile(
    r"\b(light|fixture|chandelier|pendant|downlight|sconce|ceiling fan)\b", re.I)


@dataclass
class Edge:
    source: int
    target: int
    source_pn: str
    target_pn: str
    relation: str
    rule_id: str
    confidence: float
    rationale: str
    shared: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


class Node:
    """A product reduced to the facts that can license a relationship."""

    __slots__ = ("index", "pn", "brand", "item_type", "platform", "arbor",
                 "diameter", "base_type", "bulb_shape", "series", "voltage",
                 "family", "classpath")

    def __init__(self, index: int, pn: str, graph: ProductFactGraph):
        self.index = index
        self.pn = pn
        self.brand = _norm(graph.raw_value("brand"))
        self.item_type = _norm(graph.raw_value("item_type"))
        self.platform = _norm(graph.raw_value("platform"))
        self.arbor = _norm(graph.raw_value("arbor_size"))
        self.diameter = _norm(graph.raw_value("diameter"))
        self.base_type = _norm(graph.raw_value("base_type"))
        self.bulb_shape = _norm(graph.raw_value("bulb_shape"))
        self.series = _norm(graph.raw_value("series"))
        self.voltage = _norm(graph.raw_value("voltage"))
        self.family = graph.family_id
        self.classpath = _norm(graph.raw_value("classpath"))


def _brand_root(b: str) -> str:
    return re.sub(r"[^a-z0-9]", "", b)


def build_graph(nodes: Sequence[Node], max_per_pair: int = 25) -> List[Edge]:
    """Derive relationship edges. Blocked, so it does not go quadratic."""
    edges: List[Edge] = []
    seen: Set[Tuple[int, int, str]] = set()

    def emit(a: Node, b: Node, rel: str, rule: str, conf: float,
             why: str, shared: str) -> None:
        if a.index == b.index:
            return
        k = (a.index, b.index, rel)
        if k in seen:
            return
        seen.add(k)
        edges.append(Edge(a.index, b.index, a.pn, b.pn, rel, rule,
                          round(conf, 3), why, shared))

    # -- 1. battery platform: power source <-> cordless tool ---------------
    by_platform: Dict[str, List[Node]] = defaultdict(list)
    for n in nodes:
        if n.platform:
            by_platform[(_brand_root(n.brand), n.platform)].append(n)
    for (brand, plat), group in by_platform.items():
        sources = [n for n in group if POWER_SOURCE.search(n.item_type)]
        tools = [n for n in group if CORDLESS_TOOL.search(n.item_type)]
        for s in sources[:max_per_pair]:
            for t in tools[:max_per_pair]:
                emit(s, t, "powers", "KG-PLT-01", 0.86,
                     "Both are {} products on the {} battery platform, so the "
                     "power source fits the tool.".format(s.brand.title(),
                                                          plat.upper()),
                     "platform={}".format(plat.upper()))

    # -- 2. arbor fit: bonded abrasive <-> arbor tool ----------------------
    by_arbor: Dict[str, List[Node]] = defaultdict(list)
    for n in nodes:
        if n.arbor:
            by_arbor[n.arbor].append(n)
    for arbor, group in by_arbor.items():
        discs = [n for n in group if BONDED_ABRASIVE.search(n.item_type)]
        tools = [n for n in group if ARBOR_TOOL.search(n.item_type)]
        for d in discs[:max_per_pair]:
            for t in tools[:max_per_pair]:
                emit(d, t, "fits", "KG-ARB-01", 0.78,
                     "Shared {} in arbor size; the wheel mounts on this tool's "
                     "spindle.".format(arbor), "arbor={} in".format(arbor))

    # -- 3. lamp fit: bulb <-> luminaire by base type ----------------------
    by_base: Dict[str, List[Node]] = defaultdict(list)
    for n in nodes:
        if n.base_type:
            by_base[n.base_type].append(n)
    for base, group in by_base.items():
        lamps = [n for n in group if LAMP.search(n.item_type)]
        fixtures = [n for n in group if LUMINAIRE.search(n.item_type)]
        for l in lamps[:max_per_pair]:
            for f in fixtures[:max_per_pair]:
                emit(l, f, "fits", "KG-BAS-01", 0.72,
                     "Both specify a {} lamp base, so the lamp seats in this "
                     "fixture.".format(base), "base={}".format(base))

    # -- 4. interchangeable: same item type and size, different brand ------
    by_spec: Dict[Tuple[str, str, str], List[Node]] = defaultdict(list)
    for n in nodes:
        if n.item_type and (n.diameter or n.bulb_shape):
            by_spec[(n.item_type, n.diameter, n.arbor)].append(n)
    for spec, group in by_spec.items():
        brands = defaultdict(list)
        for n in group:
            brands[_brand_root(n.brand)].append(n)
        if len(brands) < 2:
            continue
        keys = list(brands)
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                for a in brands[keys[i]][:6]:
                    for b in brands[keys[j]][:6]:
                        emit(a, b, "cross_reference", "KG-XRF-01", 0.70,
                             "Same item type and dimensions from a different "
                             "manufacturer -- a substitution candidate.",
                             "spec={}".format("/".join(x for x in spec if x)))

    # -- 5. variants: same family, differing on one axis -------------------
    by_family: Dict[str, List[Node]] = defaultdict(list)
    for n in nodes:
        by_family[n.family].append(n)
    for fam, group in by_family.items():
        if len(group) < 2 or len(group) > 60:
            continue
        head = group[0]
        for other in group[1:max_per_pair]:
            emit(head, other, "variant_of", "KG-VAR-01", 0.90,
                 "Same product family ({}); these differ only on the varying "
                 "axis such as size, grit or colour.".format(fam),
                 "family={}".format(fam))

    # -- 6. same series (merchandising collection) -------------------------
    by_series: Dict[Tuple[str, str], List[Node]] = defaultdict(list)
    for n in nodes:
        if n.series and n.brand:
            by_series[(_brand_root(n.brand), n.series)].append(n)
    for (brand, series), group in by_series.items():
        if len(group) < 2:
            continue
        head = group[0]
        for other in group[1:max_per_pair]:
            emit(head, other, "same_series", "KG-SER-01", 0.80,
                 "Both belong to the {} collection; merchandise together."
                 .format(series.title()), "series={}".format(series))

    return edges


def summarise(edges: Sequence[Edge], nodes: Sequence[Node]) -> Dict[str, Any]:
    by_rel: Dict[str, int] = defaultdict(int)
    for e in edges:
        by_rel[e.relation] += 1
    degree: Dict[int, int] = defaultdict(int)
    for e in edges:
        degree[e.source] += 1
        degree[e.target] += 1
    connected = len(degree)
    top = sorted(degree.items(), key=lambda x: -x[1])[:10]
    pn = {n.index: n.pn for n in nodes}
    it = {n.index: n.item_type for n in nodes}
    return {
        "edges": len(edges),
        "by_relation": dict(by_rel),
        "products_connected": connected,
        "coverage": round(connected / max(1, len(nodes)), 4),
        "most_connected": [
            {"index": i, "part_number": pn.get(i, ""),
             "item_type": it.get(i, ""), "degree": d} for i, d in top],
    }


EDGE_COLUMNS = ["source_pn", "target_pn", "relation", "rule_id", "confidence",
                "shared", "rationale", "source", "target"]
