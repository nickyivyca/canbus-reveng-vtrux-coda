"""
read_gas_sheet.py

Dump the structure, values and FORMULAS of `projects/vtrux/notes/Vtrux Gas.xlsx`
(the user's fuel-consumption tracking sheet), so the ethanol-correction math can
be read and reused rather than reinvented.

xlsx is a zip of XML; parsed with stdlib only (no openpyxl on this machine).

Usage:
  python3.13 projects/vtrux/notes/artifacts/read_gas_sheet.py [--rows N] [--formulas-only]
"""

import sys
import zipfile
import re
from xml.etree import ElementTree as ET

sys.path.insert(0, ".")

PATH = "projects/vtrux/notes/Vtrux Gas.xlsx"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}

MAXROWS = 40
FORMULAS_ONLY = "--formulas-only" in sys.argv
for i, a in enumerate(sys.argv):
    if a == "--rows":
        MAXROWS = int(sys.argv[i + 1])


def col_of(ref):
    return re.match(r"([A-Z]+)", ref).group(1)


def row_of(ref):
    return int(re.search(r"(\d+)", ref).group(1))


z = zipfile.ZipFile(PATH)

# shared strings
shared = []
if "xl/sharedStrings.xml" in z.namelist():
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    for si in root.findall("m:si", NS):
        shared.append("".join(t.text or "" for t in si.iter(
            "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))

# sheet name -> file
wb = ET.fromstring(z.read("xl/workbook.xml"))
rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
relmap = {r.get("Id"): r.get("Target") for r in rels}
sheets = []
for sh in wb.findall("m:sheets/m:sheet", NS):
    rid = sh.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    tgt = relmap.get(rid, "")
    sheets.append((sh.get("name"), "xl/" + tgt.lstrip("/")))

print("Workbook: %s" % PATH)
print("Sheets: %s\n" % ", ".join(n for n, _ in sheets))

for name, path in sheets:
    if path not in z.namelist():
        continue
    print("=" * 78)
    print("SHEET: %s" % name)
    root = ET.fromstring(z.read(path))
    formulas = {}
    grid = {}
    for row in root.findall("m:sheetData/m:row", NS):
        rn = int(row.get("r"))
        for c in row.findall("m:c", NS):
            ref = c.get("r")
            t = c.get("t")
            f = c.find("m:f", NS)
            v = c.find("m:v", NS)
            val = ""
            if v is not None and v.text is not None:
                val = v.text
                if t == "s":
                    try:
                        val = shared[int(val)]
                    except (ValueError, IndexError):
                        pass
            if t == "inlineStr":
                istr = c.find("m:is", NS)
                if istr is not None:
                    val = "".join(x.text or "" for x in istr.iter(
                        "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"))
            grid[ref] = val
            if f is not None and f.text:
                formulas[ref] = f.text

    # --- unique formula patterns, normalised by stripping row numbers -------
    print("\n-- FORMULA PATTERNS (row numbers stripped; one example ref each) --")
    seen = {}
    for ref, f in formulas.items():
        pat = re.sub(r"(?<=[A-Z])\d+", "#", f)
        key = (col_of(ref), pat)
        if key not in seen:
            seen[key] = (ref, f)
    for (col, pat), (ref, f) in sorted(seen.items()):
        print("   %-6s %-8s %s" % (col, ref, f))

    if FORMULAS_ONLY:
        continue

    # --- grid preview -------------------------------------------------------
    cols = sorted({col_of(r) for r in grid},
                  key=lambda c: (len(c), c))
    rows = sorted({row_of(r) for r in grid})[:MAXROWS]
    print("\n-- VALUES (first %d rows) --" % len(rows))
    for rn in rows:
        cells = []
        for c in cols:
            v = grid.get("%s%d" % (c, rn), "")
            if v != "":
                cells.append("%s=%s" % (c, v[:28]))
        if cells:
            print("  r%-4d %s" % (rn, "  ".join(cells)))
