"""Dependency-free tabular I/O.

Judges will clone this repo and run it. Requiring ``pandas`` and ``openpyxl``
to read a spreadsheet is a needless way to fail on someone else's machine, so
CSV and XLSX are both read with the standard library only -- XLSX is just a zip
of XML.

The reader also copes with the messiness the solution guide warns about:
preamble rows above the real header, merged cells, and blank spacer columns.
"""
from __future__ import annotations

import csv
import io
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------
def _col_to_index(ref: str) -> int:
    """'A1' / 'BC12' -> zero-based column index."""
    letters = re.match(r"([A-Z]+)", ref.upper())
    if not letters:
        return 0
    n = 0
    for ch in letters.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _shared_strings(z: zipfile.ZipFile) -> List[str]:
    try:
        data = z.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    out: List[str] = []
    root = ET.fromstring(data)
    for si in root.findall("m:si", _NS):
        # A cell's string can be split across several runs; join them all.
        parts = [t.text or "" for t in si.iter("{%s}t" % _NS["m"])]
        out.append("".join(parts))
    return out


def _sheet_paths(z: zipfile.ZipFile) -> List[Tuple[str, str]]:
    """Return [(sheet_name, zip_path)] in workbook order."""
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    except KeyError:
        names = sorted(n for n in z.namelist()
                       if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
        return [(os.path.basename(n), n) for n in names]

    rid_to_target = {}
    for rel in rels:
        rid_to_target[rel.get("Id")] = rel.get("Target")

    out = []
    rns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    for sh in wb.iter("{%s}sheet" % _NS["m"]):
        name = sh.get("name") or ""
        target = rid_to_target.get(sh.get(rns), "")
        if not target:
            continue
        path = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
        if path in z.namelist():
            out.append((name, path))
    return out


def read_xlsx_sheet(path: str, sheet: Optional[str] = None) -> List[List[str]]:
    """Read one sheet into a rectangular list of rows of strings."""
    with zipfile.ZipFile(path) as z:
        strings = _shared_strings(z)
        sheets = _sheet_paths(z)
        if not sheets:
            return []
        target = sheets[0][1]
        if sheet:
            for nm, p in sheets:
                if nm.strip().lower() == sheet.strip().lower():
                    target = p
                    break
        root = ET.fromstring(z.read(target))

        rows: List[List[str]] = []
        for row in root.iter("{%s}row" % _NS["m"]):
            cells: Dict[int, str] = {}
            for c in row.findall("m:c", _NS):
                ref = c.get("r") or ""
                idx = _col_to_index(ref) if ref else len(cells)
                ctype = c.get("t")
                if ctype == "inlineStr":
                    node = c.find("m:is", _NS)
                    val = "".join(t.text or "" for t in node.iter("{%s}t" % _NS["m"])) \
                        if node is not None else ""
                else:
                    v = c.find("m:v", _NS)
                    val = v.text if v is not None and v.text is not None else ""
                    if ctype == "s":
                        try:
                            val = strings[int(val)]
                        except (ValueError, IndexError):
                            val = ""
                cells[idx] = (val or "").strip()
            if cells:
                width = max(cells) + 1
                rows.append([cells.get(i, "") for i in range(width)])
            else:
                rows.append([])
        width = max((len(r) for r in rows), default=0)
        return [r + [""] * (width - len(r)) for r in rows]


def list_sheets(path: str) -> List[str]:
    with zipfile.ZipFile(path) as z:
        return [n for n, _ in _sheet_paths(z)]


# ---------------------------------------------------------------------------
# Header detection
# ---------------------------------------------------------------------------
def _score_header(row: Sequence[str]) -> float:
    """How much a row looks like a header rather than data."""
    vals = [v for v in row if str(v).strip()]
    if len(vals) < 2:
        return 0.0
    non_numeric = sum(1 for v in vals if not re.fullmatch(r"[\d.,%$/-]+", str(v).strip()))
    shortish = sum(1 for v in vals if len(str(v)) <= 40)
    unique = len(set(str(v).strip().lower() for v in vals)) / len(vals)
    density = len(vals) / max(1, len(row))
    return (non_numeric / len(vals)) * 0.4 + (shortish / len(vals)) * 0.2 \
        + unique * 0.2 + density * 0.2


def find_header_row(rows: Sequence[Sequence[str]], scan: int = 12) -> int:
    """Locate the real header. Spreadsheets in this pack have titles, notes and
    merged cells above the header, so row 0 cannot be assumed."""
    best_i, best_s = 0, -1.0
    for i, row in enumerate(rows[:scan]):
        s = _score_header(row)
        # Prefer the row that also has data beneath it.
        if i + 1 < len(rows) and any(str(v).strip() for v in rows[i + 1]):
            s += 0.1
        if s > best_s:
            best_i, best_s = i, s
    return best_i


def _dedupe(names: Sequence[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out: List[str] = []
    for i, n in enumerate(names):
        base = str(n).strip() or "column_{}".format(i + 1)
        if base in seen:
            seen[base] += 1
            base = "{}_{}".format(base, seen[base])
        else:
            seen[base] = 0
        out.append(base)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def read_table(path: str, sheet: Optional[str] = None,
               header_row: Optional[int] = None
               ) -> Tuple[List[Dict[str, str]], List[str]]:
    """Read a CSV/TSV/XLSX into ``(rows_as_dicts, header)``."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xltx"):
        grid = read_xlsx_sheet(path, sheet)
    elif ext in (".csv", ".tsv", ".txt"):
        delim = "\t" if ext == ".tsv" else ","
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            sample = fh.read(8192)
            fh.seek(0)
            if ext == ".csv":
                try:
                    delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
                except csv.Error:
                    delim = ","
            grid = [list(r) for r in csv.reader(fh, delimiter=delim)]
    else:
        raise ValueError("Unsupported file type: {}".format(ext))

    if not grid:
        return [], []

    hi = header_row if header_row is not None else find_header_row(grid)
    header = _dedupe(grid[hi])
    rows: List[Dict[str, str]] = []
    for raw in grid[hi + 1:]:
        if not any(str(v).strip() for v in raw):
            continue
        padded = list(raw) + [""] * (len(header) - len(raw))
        rows.append({header[i]: padded[i] for i in range(len(header))})
    return rows, header


def write_csv(path: str, header: Sequence[str],
              rows: Sequence[Dict[str, Any]]) -> None:
    """Write the delivery file. Header order is fixed and never altered."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(header), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else str(r.get(k))) for k in header})


def write_xlsx(path: str, header: Sequence[str],
               rows: Sequence[Dict[str, Any]], sheet_name: str = "Delivery Format") -> None:
    """Minimal XLSX writer -- no third-party dependency.

    Values are written as inline strings, which keeps the file valid and
    readable by Excel/Sheets without a shared-string table.
    """
    def esc(v: Any) -> str:
        s = "" if v is None else str(v)
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return "".join(ch for ch in s if ch >= " " or ch in "\t\n")

    def col_ref(i: int) -> str:
        s, i = "", i + 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    def row_xml(idx: int, values: Sequence[Any]) -> str:
        cells = []
        for ci, v in enumerate(values):
            sv = esc(v)
            if sv == "":
                continue
            cells.append('<c r="{}{}" t="inlineStr"><is><t xml:space="preserve">'
                         '{}</t></is></c>'.format(col_ref(ci), idx, sv))
        return '<row r="{}">{}</row>'.format(idx, "".join(cells))

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    body = [row_xml(1, list(header))]
    for i, r in enumerate(rows, start=2):
        body.append(row_xml(i, [r.get(h, "") for h in header]))

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>{}</sheetData></worksheet>'.format("".join(body)))
    wb_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="{}" sheetId="1" r:id="rId1"/></sheets></workbook>'
        .format(esc(sheet_name)[:31] or "Sheet1"))
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", wb_xml)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
