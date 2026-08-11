"""Does main-orig ever cross the cooling threshold WITHOUT engaging cooling?

battery-thermals.md established the cooling-active signature on parts-orig:
  * 0x508 broadcast only while cooling is active
  * 0x506 B0 bit5 high
  * DCDC_LV_Curr (0x18FFD6B3 B2-B3, x0.05 A) steps ~6 A -> ~100 A
  * engages around cell_tmax 38.0-39.5 C, releases ~36.5 C

main-orig broadcasts NEITHER 0x506 NOR 0x508 (0 of 35 logs), so the first two tests are
unavailable on that pack. **The 12V load step is not** -- DCDC_LV_Curr comes from the
Bel DCDC on J1939 extended IDs, independent of the BMS, and is present on both packs.

So: find every log where cell_tmax crosses ~36 C, split by pack, and check whether the
12V load stepped. A main-orig log that goes hot with NO 12V step is direct evidence the
pack has no working conditioning -- matching the owner's report of never hearing the fan
on main-orig.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/mainorig_cooling_test.py
"""
import sys
import os
import re
import datetime
from pathlib import Path

sys.path.insert(0, ".")

SWAP = datetime.date(2025, 12, 9)
HOT = 34.0          # report any log reaching this
COOL_ON = 38.0      # parts-orig engagement band from battery-thermals.md

DIRS = [Path("projects/vtrux/logs"), Path("../../CANLogs/VtruxLogs")]

BM = re.compile(r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+(0x[0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
CD = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)$")

ID_CELL = 0x430
ID_DCDC = 0x18FFD6B3
ID_506 = 0x506
ID_508 = 0x508


def hdr_date(p):
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as fh:
            for _ in range(30):
                line = fh.readline()
                if not line:
                    break
                m = re.search(r"START DATE AND TIME\s+(\d+):(\d+):(\d+)", line)
                if m:
                    d, mo, y = [int(x) for x in m.groups()]
                    try:
                        return datetime.date(y, mo, d)
                    except ValueError:
                        break
                s = line.strip()
                if s.startswith("("):
                    try:
                        return datetime.date.fromtimestamp(float(s[1:s.index(")")]))
                    except (ValueError, IndexError):
                        break
    except OSError:
        pass
    return datetime.date.fromtimestamp(os.path.getmtime(p))


def scan(p):
    tmax = -99.0
    lv_lo = None
    lv_hi = None
    hot_lv = []          # DCDC current samples while tmax >= HOT
    n506 = n508 = 0
    cur_t = -99.0
    try:
        fh = open(p, "r", encoding="utf-8", errors="ignore")
    except OSError:
        return None
    with fh:
        for line in fh:
            if line[:1] == "*":
                continue
            m = BM.match(line)
            if m:
                idh = m.group(5)
                rest = m.group(7)
                aid = int(idh, 16)
                try:
                    d = bytes(int(b, 16) for b in rest.split())
                except ValueError:
                    continue
            else:
                m = CD.match(line.strip())
                if not m:
                    continue
                aid = int(m.group(2), 16)
                try:
                    d = bytes.fromhex(m.group(3)) if m.group(3) else b""
                except ValueError:
                    continue
            if aid == ID_CELL and len(d) >= 5 and d[4] < 0xFE:
                cur_t = d[4] * 0.5 - 40.0
                tmax = max(tmax, cur_t)
            elif aid == ID_506:
                n506 += 1
            elif aid == ID_508:
                n508 += 1
            elif aid == ID_DCDC and len(d) >= 4:
                lv = (d[2] | (d[3] << 8)) * 0.05
                if lv > 400:
                    continue
                lv_lo = lv if lv_lo is None else min(lv_lo, lv)
                lv_hi = lv if lv_hi is None else max(lv_hi, lv)
                if cur_t >= HOT:
                    hot_lv.append(lv)
    return tmax, lv_lo, lv_hi, hot_lv, n506, n508


files = []
for dp in DIRS:
    if dp.exists():
        for p in list(dp.rglob("*.log")) + list(dp.rglob("*.txt")):
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if 3e6 < sz <= 9e8:
                files.append(p)
byname = {}
for p in files:
    sz = os.path.getsize(p)
    if p.name not in byname or sz > byname[p.name][1]:
        byname[p.name] = (p, sz)
files = [v[0] for v in byname.values()]
print("scanning %d logs for cell_tmax and 12V load...\n" % len(files), flush=True)

rows = []
for i, p in enumerate(files):
    if i % 50 == 0:
        print("  %d/%d" % (i, len(files)), flush=True)
    r = scan(str(p))
    if not r:
        continue
    tmax, lo, hi, hot_lv, n506, n508 = r
    if tmax < -90:
        continue
    d = hdr_date(str(p))
    parts_truck = "partstruck" in p.name.lower()
    pack = "main-orig" if ((parts_truck and d >= SWAP) or (not parts_truck and d < SWAP)) else "parts-orig"
    rows.append((pack, d, p.name, tmax, lo, hi, hot_lv, n506, n508))

print()
print("=" * 116)
print("  HOTTEST LOGS PER PACK  (cooling engages ~%.1f C on parts-orig)" % COOL_ON)
print("=" * 116)
print("  %-11s %-11s %-38s %-8s %-16s %-7s %s"
      % ("pack", "date", "log", "tmax C", "12V lo..hi (A)", "0x506", "12V while >=%.0fC" % HOT))
print("  " + "-" * 112)
for pack in ("main-orig", "parts-orig"):
    sub = sorted([r for r in rows if r[0] == pack], key=lambda r: -r[3])[:12]
    for pk, d, n, tmax, lo, hi, hot_lv, n506, n508 in sub:
        hv = ("n=%d mean=%.0f max=%.0f" % (len(hot_lv), sum(hot_lv) / len(hot_lv), max(hot_lv))
              if hot_lv else "-")
        print("  %-11s %-11s %-38s %-8.1f %-16s %-7s %s"
              % (pk, d, n[:38], tmax,
                 ("%.0f..%.0f" % (lo, hi)) if lo is not None else "-",
                 n506 or "-", hv))
    print()

print("=" * 116)
print("  VERDICT")
print("=" * 116)
for pack in ("main-orig", "parts-orig"):
    sub = [r for r in rows if r[0] == pack]
    if not sub:
        continue
    hot = [r for r in sub if r[3] >= COOL_ON]
    peak = max(r[3] for r in sub)
    print("  %-11s %3d logs | peak cell_tmax %.1f C | %d log(s) reached %.1f C"
          % (pack, len(sub), peak, len(hot), COOL_ON))
    for r in sorted(hot, key=lambda r: -r[3]):
        hv = r[6]
        step = (max(hv) - min(hv)) if hv else 0
        print("       HOT: %-36s tmax=%.1f  12V while hot: %s"
              % (r[2][:36], r[3],
                 ("n=%d %.0f..%.0f A  (span %.0f A)" % (len(hv), min(hv), max(hv), step))
                 if hv else "no DCDC data"))
