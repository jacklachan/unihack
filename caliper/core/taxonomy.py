"""Taxonomy assignment.

The delivery format carries two parallel hierarchies:

* ``Dept`` / ``Class`` / ``Fine`` -- the distributor's own merchandising tree;
* ``Classpath`` -- Unilog's canonical ``A>B>C`` path, which is also the key the
  attribute LOV is defined against.

Both are assigned from the resolved item type. Classification *abstains* rather
than guessing: an unmatched item leaves the columns empty and raises a
``needs_review`` note, because a wrong classpath silently invalidates every
attribute validated against it.

When the official ``Unicat_Lov`` is supplied its classpaths take precedence and
this table becomes the fallback for anything the master data does not cover.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .facts import Evidence, Fact


@dataclass(frozen=True)
class TaxonomyNode:
    dept: str
    klass: str
    fine: str
    classpath: str
    unspsc: str = ""


#: (regex over the item type, node). First match wins, so order is specific
#: -> general. Written against the item types the sample actually produces.
RULES: Tuple[Tuple[str, TaxonomyNode], ...] = (
    # ---- lamps & lighting -------------------------------------------------
    (r"\b(led\s+bulb|light\s+bulb|bulb|lamp)\b",
     TaxonomyNode("Electrical", "Lighting", "Light Bulbs",
                  "Electrical>Lighting & Bulbs>Light Bulbs", "39101600")),
    (r"\b(chandelier)\b",
     TaxonomyNode("Electrical", "Lighting", "Chandeliers",
                  "Electrical>Lighting & Bulbs>Chandeliers", "39111524")),
    (r"\b(pendant\s+light|pendant)\b",
     TaxonomyNode("Electrical", "Lighting", "Pendant Lights",
                  "Electrical>Lighting & Bulbs>Pendant Lighting", "39111524")),
    (r"\b(bath\s+light|vanity\s+light)\b",
     TaxonomyNode("Electrical", "Lighting", "Bath & Vanity Lights",
                  "Electrical>Lighting & Bulbs>Bath & Vanity Lighting", "39111524")),
    (r"\b(exterior\s+wall\s+light|outdoor\s+light|flood\s+light)\b",
     TaxonomyNode("Electrical", "Lighting", "Outdoor Lighting",
                  "Electrical>Lighting & Bulbs>Outdoor Lighting", "39111500")),
    (r"\b(wall\s+light|wall\s+sconce|sconce)\b",
     TaxonomyNode("Electrical", "Lighting", "Wall Lights",
                  "Electrical>Lighting & Bulbs>Wall Lighting", "39111524")),
    (r"\b(downlight|recessed\s+light)\b",
     TaxonomyNode("Electrical", "Lighting", "Recessed Lighting",
                  "Electrical>Lighting & Bulbs>Recessed Lighting", "39111524")),
    (r"\b(ceiling\s+light|ceiling\s+lt|flush\s+mount)\b",
     TaxonomyNode("Electrical", "Lighting", "Ceiling Lights",
                  "Electrical>Lighting & Bulbs>Ceiling Lighting", "39111524")),
    (r"\b(motion\s+light|security\s+light)\b",
     TaxonomyNode("Electrical", "Lighting", "Security Lighting",
                  "Electrical>Lighting & Bulbs>Security Lighting", "39111500")),
    (r"\b(flash\s*light|torch)\b",
     TaxonomyNode("Tools", "Hand Tools", "Flashlights",
                  "Tools & Equipment>Portable Lighting>Flashlights", "39111610")),
    (r"\b(ceiling\s+fan|fan)\b",
     TaxonomyNode("Electrical", "Fans & Ventilation", "Ceiling Fans",
                  "Electrical>Fans & Ventilation>Ceiling Fans", "40101602")),
    (r"\b(light\s+fixture|light)\b",
     TaxonomyNode("Electrical", "Lighting", "Light Fixtures",
                  "Electrical>Lighting & Bulbs>Light Fixtures", "39111500")),

    # ---- abrasives & cutting ---------------------------------------------
    (r"\b(cut\s*off\s+(disc|wheel))\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Cut-Off Wheels",
                  "Tools & Equipment>Power Tool Accessories>Cut-Off Wheels", "23131500")),
    (r"\b(grinding\s+wheel)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Grinding Wheels",
                  "Tools & Equipment>Power Tool Accessories>Grinding Wheels", "23131500")),
    (r"\b(flap\s+disc)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Flap Discs",
                  "Tools & Equipment>Power Tool Accessories>Flap Discs", "23131500")),
    (r"\b(sanding\s+belt)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Sanding Belts",
                  "Tools & Equipment>Abrasives>Sanding Belts", "31191500")),
    (r"\b(sanding\s+sheet|abrasive\s+sheet|sanding\s+pad|abrasive\s+mesh)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Sanding Sheets",
                  "Tools & Equipment>Abrasives>Sanding Sheets", "31191500")),
    (r"\b(sanding\s+disc|abrasive\s+disc|disc)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Sanding Discs",
                  "Tools & Equipment>Abrasives>Sanding Discs", "31191500")),
    (r"\b(saw\s+blade|blade)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Saw Blades",
                  "Tools & Equipment>Power Tool Accessories>Saw Blades", "27112700")),
    (r"\b(router\s+bit)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Router Bits",
                  "Tools & Equipment>Power Tool Accessories>Router Bits", "27112800")),
    (r"\b(drill\s+bit)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Drill Bits",
                  "Tools & Equipment>Power Tool Accessories>Drill Bits", "27112800")),
    (r"\b(driver\s+bit|drive\s+bit|bit)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Driver Bits",
                  "Tools & Equipment>Power Tool Accessories>Driver Bits", "27112800")),
    (r"\b(hole\s+saw)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Hole Saws",
                  "Tools & Equipment>Power Tool Accessories>Hole Saws", "27112800")),

    # ---- power tools ------------------------------------------------------
    (r"\b(band\s*saw)\b",
     TaxonomyNode("Tools", "Stationary Power Tools", "Band Saws",
                  "Tools & Equipment>Stationary Power Tools>Band Saws", "27112100")),
    (r"\b(table\s+saw)\b",
     TaxonomyNode("Tools", "Stationary Power Tools", "Table Saws",
                  "Tools & Equipment>Stationary Power Tools>Table Saws", "27112100")),
    (r"\b(miter\s+saw)\b",
     TaxonomyNode("Tools", "Power Tools", "Miter Saws",
                  "Tools & Equipment>Power Tools>Miter Saws", "27112100")),
    (r"\b(circular\s+saw|reciprocating\s+saw|jig\s*saw)\b",
     TaxonomyNode("Tools", "Power Tools", "Saws",
                  "Tools & Equipment>Power Tools>Saws", "27112100")),
    (r"\b(impact\s+driver|impact\s+wrench)\b",
     TaxonomyNode("Tools", "Power Tools", "Impact Tools",
                  "Tools & Equipment>Power Tools>Impact Drivers & Wrenches", "27112000")),
    (r"\b(hammer\s+drill|drill)\b",
     TaxonomyNode("Tools", "Power Tools", "Drills",
                  "Tools & Equipment>Power Tools>Drills", "27112000")),
    (r"\b(die\s+grinder|grinder)\b",
     TaxonomyNode("Tools", "Power Tools", "Grinders",
                  "Tools & Equipment>Power Tools>Grinders", "27112000")),
    (r"\b(orbit\s+sander|belt\s+sander|spindle\s+sander|sander)\b",
     TaxonomyNode("Tools", "Power Tools", "Sanders",
                  "Tools & Equipment>Power Tools>Sanders", "27112000")),
    (r"\b(ratchet)\b",
     TaxonomyNode("Tools", "Hand Tools", "Ratchets",
                  "Tools & Equipment>Hand Tools>Ratchets", "27111700")),
    (r"\b(string\s+trimmer|trimmer)\b",
     TaxonomyNode("Outdoor", "Lawn & Garden", "String Trimmers",
                  "Lawn & Garden>Outdoor Power Equipment>String Trimmers", "21101800")),
    (r"\b(battery\s+charger|charger)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Battery Chargers",
                  "Tools & Equipment>Power Tool Accessories>Chargers", "26111700")),
    (r"\b(battery)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Batteries",
                  "Tools & Equipment>Power Tool Accessories>Batteries", "26111700")),
    (r"\b(brad\s+nailer|finish\s+nailer|framing\s+nailer|nailer)\b",
     TaxonomyNode("Tools", "Power Tools", "Nailers",
                  "Tools & Equipment>Power Tools>Nailers", "27112000")),

    # ---- appliances -------------------------------------------------------
    (r"\b(dishwasher)\b",
     TaxonomyNode("Appliances", "Large Appliances", "Dishwashers",
                  "Appliances & Consumer Electronics>Kitchen Appliances>Built-In Dishwashers",
                  "52141500")),
    (r"\b(refrigerator|fridge)\b",
     TaxonomyNode("Appliances", "Large Appliances", "Refrigerators",
                  "Appliances & Consumer Electronics>Kitchen Appliances>Refrigerators",
                  "52141501")),
    (r"\b(range|cooktop|wall\s+oven|oven)\b",
     TaxonomyNode("Appliances", "Large Appliances", "Ranges & Ovens",
                  "Appliances & Consumer Electronics>Kitchen Appliances>Ranges",
                  "52141502")),
    (r"\b(microwave)\b",
     TaxonomyNode("Appliances", "Large Appliances", "Microwaves",
                  "Appliances & Consumer Electronics>Kitchen Appliances>Microwave Ovens",
                  "52141520")),
    (r"\b(washer)\b",
     TaxonomyNode("Appliances", "Large Appliances", "Washers",
                  "Appliances & Consumer Electronics>Laundry Appliances>Washers",
                  "52141601")),
    (r"\b(dryer)\b",
     TaxonomyNode("Appliances", "Large Appliances", "Dryers",
                  "Appliances & Consumer Electronics>Laundry Appliances>Dryers",
                  "52141602")),
    (r"\b(freezer)\b",
     TaxonomyNode("Appliances", "Large Appliances", "Freezers",
                  "Appliances & Consumer Electronics>Kitchen Appliances>Freezers",
                  "52141503")),

    # ---- electrical distribution -----------------------------------------
    (r"\b(load\s+center|panel\s*board)\b",
     TaxonomyNode("Electrical", "Power Distribution", "Load Centers",
                  "Electrical>Power Distribution>Load Centers", "39121000")),
    (r"\b(circuit\s+breaker|breaker)\b",
     TaxonomyNode("Electrical", "Power Distribution", "Circuit Breakers",
                  "Electrical>Power Distribution>Circuit Breakers", "39121004")),
    (r"\b(receptacle|outlet)\b",
     TaxonomyNode("Electrical", "Wiring Devices", "Receptacles",
                  "Electrical>Wiring Devices>Receptacles", "39121600")),
    (r"\b(box\s+cover|wall\s+plate|cover)\b",
     TaxonomyNode("Electrical", "Wiring Devices", "Wall Plates & Covers",
                  "Electrical>Wiring Devices>Wall Plates", "39131700")),
    (r"\b(switch)\b",
     TaxonomyNode("Electrical", "Wiring Devices", "Switches",
                  "Electrical>Wiring Devices>Switches", "39121500")),
    (r"\b(wire|cable|cord)\b",
     TaxonomyNode("Electrical", "Wire & Cable", "Building Wire",
                  "Electrical>Wire & Cable>Building Wire", "26121600")),

    # ---- building products ------------------------------------------------
    (r"\b(decking|deck\s+board)\b",
     TaxonomyNode("Building Materials", "Decking", "Composite Decking",
                  "Building Materials>Decking>Composite & PVC Decking", "30103600")),
    (r"\b(railing|rail)\b",
     TaxonomyNode("Building Materials", "Decking", "Railing",
                  "Building Materials>Decking>Railing Systems", "30103600")),
    (r"\b(fascia|trim\s+board|trim)\b",
     TaxonomyNode("Building Materials", "Trim", "Trim Board",
                  "Building Materials>Trim & Moulding>Trim Board", "30103600")),
    (r"\b(siding|panel)\b",
     TaxonomyNode("Building Materials", "Siding", "Siding Panels",
                  "Building Materials>Siding>Fiber Cement & Engineered Siding", "30151500")),
    (r"\b(mortar|grout)\b",
     TaxonomyNode("Building Materials", "Masonry", "Mortar",
                  "Building Materials>Masonry>Mortar & Grout", "30111500")),
    (r"\b(support\s+post|post)\b",
     TaxonomyNode("Building Materials", "Structural", "Support Posts",
                  "Building Materials>Structural>Columns & Posts", "30102300")),
    (r"\b(nail|screw|staple|fastener)\b",
     TaxonomyNode("Building Materials", "Fasteners", "Fasteners",
                  "Building Materials>Fasteners>Nails & Staples", "31161500")),
    (r"\b(tape\s+measure)\b",
     TaxonomyNode("Tools", "Hand Tools", "Tape Measures",
                  "Tools & Equipment>Hand Tools>Measuring Tools", "27111700")),
    (r"\b(tape)\b",
     TaxonomyNode("Building Materials", "Sealants", "Sealant Tape",
                  "Building Materials>Sealants & Adhesives>Sealant Tape", "31201500")),
    (r"\b(safety\s+glasses|eyewear|hearing\s+protector)\b",
     TaxonomyNode("Safety", "PPE", "Protective Equipment",
                  "Safety>Personal Protective Equipment>Eye & Ear Protection", "46181800")),

    # ---- generic families ------------------------------------------------
    # Deliberately broad: these catch real categories in the long tail without
    # encoding sample-specific answers. Anything still unmatched abstains.
    (r"\b(glove|glove\s+liners|mitt)\b",
     TaxonomyNode("Safety", "PPE", "Gloves",
                  "Safety>Personal Protective Equipment>Hand Protection", "46181504")),
    (r"\b(hoodie|jacket|vest|apparel|sweatshirt)\b",
     TaxonomyNode("Safety", "Workwear", "Apparel",
                  "Safety>Workwear>Jackets & Hoodies", "53102500")),
    (r"\b(planer|jointer|lathe|mortiser|shaper)\b",
     TaxonomyNode("Tools", "Stationary Power Tools", "Woodworking Machinery",
                  "Tools & Equipment>Stationary Power Tools>Woodworking Machinery",
                  "27112100")),
    (r"\b(dust\s+extractor|vacuum|shop\s+vac|blower)\b",
     TaxonomyNode("Tools", "Power Tools", "Dust Extraction",
                  "Tools & Equipment>Dust Management>Vacuums & Extractors", "47121701")),
    (r"\b(wrench|socket|hex\s+socket|adapter|mechanics)\b",
     TaxonomyNode("Tools", "Hand Tools", "Wrenches & Sockets",
                  "Tools & Equipment>Hand Tools>Wrenches & Sockets", "27111700")),
    (r"\b(rachet|ratchet)\b",
     TaxonomyNode("Tools", "Hand Tools", "Ratchets",
                  "Tools & Equipment>Hand Tools>Ratchets", "27111700")),
    (r"\b(knife|blade\s+knife|utility\s+knife)\b",
     TaxonomyNode("Tools", "Hand Tools", "Knives",
                  "Tools & Equipment>Hand Tools>Knives", "27111900")),
    (r"\b(laser|level|square|measuring)\b",
     TaxonomyNode("Tools", "Hand Tools", "Layout & Measuring",
                  "Tools & Equipment>Hand Tools>Layout & Measuring Tools", "41111700")),
    (r"\b(organizer|tool\s+box|case|storage)\b",
     TaxonomyNode("Tools", "Storage", "Tool Storage",
                  "Tools & Equipment>Tool Storage>Organizers & Cases", "24101600")),
    (r"\b(timer|dimmer|sensor|photocell)\b",
     TaxonomyNode("Electrical", "Controls", "Lighting Controls",
                  "Electrical>Wiring Devices>Lighting Controls", "39121500")),
    (r"\b(alarm|detector|smoke\s+alarm)\b",
     TaxonomyNode("Safety", "Life Safety", "Alarms & Detectors",
                  "Safety>Life Safety>Smoke & CO Alarms", "46191500")),
    (r"\b(beverage\s+center|toaster|espresso|coffee|blender|maker)\b",
     TaxonomyNode("Appliances", "Small Appliances", "Countertop Appliances",
                  "Appliances & Consumer Electronics>Small Appliances>Countertop Appliances",
                  "52141700")),
    (r"\b(fence|fencing|guard)\b",
     TaxonomyNode("Tools", "Power Tool Accessories", "Fences & Guides",
                  "Tools & Equipment>Power Tool Accessories>Fences & Guides", "27112800")),
    (r"\b(sheathing|board|brd|plywood|osb)\b",
     TaxonomyNode("Building Materials", "Structural Panels", "Sheathing",
                  "Building Materials>Structural Panels>Sheathing", "30161700")),
    (r"\b(hanger|bracket|connector)\b",
     TaxonomyNode("Building Materials", "Structural", "Connectors",
                  "Building Materials>Structural>Connectors & Hangers", "31162400")),
    (r"\b(saw)\b",
     TaxonomyNode("Tools", "Power Tools", "Saws",
                  "Tools & Equipment>Power Tools>Saws", "27112100")),
    (r"\b(impact)\b",
     TaxonomyNode("Tools", "Power Tools", "Impact Tools",
                  "Tools & Equipment>Power Tools>Impact Drivers & Wrenches", "27112000")),
)

_COMPILED: List[Tuple["re.Pattern[str]", TaxonomyNode]] = [
    (re.compile(p, re.I), n) for p, n in RULES
]


@dataclass
class Classification:
    node: Optional[TaxonomyNode] = None
    confidence: float = 0.0
    matched: str = ""
    rule_id: str = ""
    abstained: bool = False
    reason: str = ""


def classify(item_type: str, description: str = "") -> Classification:
    """Assign a taxonomy node from the item type, falling back to the raw
    description. Abstains when nothing matches."""
    for text, conf, src in ((item_type, 0.90, "item_type"),
                            (description, 0.72, "description")):
        if not text:
            continue
        for i, (rx, node) in enumerate(_COMPILED):
            m = rx.search(text)
            if m:
                return Classification(node=node, confidence=conf,
                                      matched=m.group(0),
                                      rule_id="TAX-{:03d}".format(i + 1))
    return Classification(
        abstained=True,
        reason=("No taxonomy rule matched item type {!r}. Classpath left empty "
                "rather than guessed, because attribute validation is keyed on "
                "it.".format(item_type or description[:40])))


def taxonomy_facts(c: Classification, source: str, text: str) -> List[Fact]:
    if not c.node:
        return []
    ev = [Evidence(source=source, text=text,
                   detail="Matched taxonomy rule {} on {!r}.".format(c.rule_id, c.matched))]
    out = []
    for key, label, value, prio in (
        ("dept", "Dept", c.node.dept, 6),
        ("class", "Class", c.node.klass, 7),
        ("fine", "Fine", c.node.fine, 8),
        ("classpath", "Classpath", c.node.classpath, 9),
    ):
        out.append(Fact(key=key, value=value, label=label, method="rule",
                        rule_id=c.rule_id, raw=c.matched, confidence=c.confidence,
                        priority=prio, evidence=list(ev)))
    if c.node.unspsc:
        out.append(Fact(key="unspsc", value=c.node.unspsc, label="UNSPSC",
                        method="inferred", rule_id=c.rule_id, raw=c.matched,
                        confidence=c.confidence * 0.8, priority=70,
                        evidence=[Evidence(source="registry:taxonomy",
                                           text=c.node.unspsc,
                                           detail="UNSPSC family for classpath {}."
                                           .format(c.node.classpath))]))
    return out
