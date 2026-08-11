"""Does pack/ambient temperature predict precharge failure on the main-orig pack?

Backstory (from user, 2026-07-26): the MAIN truck originally had a loose 12V terminal
and often failed precharge. The terminal was fixed, but the same failure kept
recurring intermittently -- **notably worse in warm weather** -- and progressed to
random shutdowns while driving. The only logged instance of the running-shutdown form
is the 2025-08-22 full-charge-then-fail session.

This scan tests the temperature claim against the corpus: for every precharge
sequence, record outcome AND pack temperature, then compare the distributions.

Extends precharge_lvbat_scan.py with cell_tmax / cell_tmin (0x430 B4/B5) and
pack temperature (0x506 B1-B3).

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/precharge_temp_scan.py
"""
import sys
import os
import re
import warnings
from pathlib import Path
from datetime import date, datetime
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

from canre.parsers import parse_file  # noqa: E402

PRIMARY_DIR = Path("projects/vtrux/logs")
ANDROID_DIR = Path("../../CANLogs/VtruxLogs")
SWAP_DATE = date(2025, 12, 9)

PARTS_EXCLUSIVE_IDS = {0x391, 0x552}
PT_ANCHOR = 0x051

MAINC = ["ALL_OPEN", "FAILED_MAINP_OR_R_WELD", "CLOSE_MAINR", "FAILED_MAINR_OPEN",
         "FAILED_MAINN_WELD", "CLOSE_MAINN", "FAILED_MAINN_OPEN", "WAIT_PRECHARGE",
         "CLOSE_MAINP", "OPEN_MAINR", "FAILED_MAINP_OPEN", "MAIN_PN_CLOSED_DRIVE",
         "MAIN_P_CLOSED_CHARGE", "SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN", "(idx15)"]


def get_log_date(fp):
    m = re.search(r"_(\d{8})_", Path(fp).name)
    if m:
        s = m.group(1)
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            pass
    return date.fromtimestamp(os.path.getmtime(fp))


def scan_log(fp):
    pt_bus = None
    is_parts = False
    last_lv = last_tmax = last_tmin = None
    pack_t = None
    prev = None
    in_mainn = False
    lv_min = None
    events = []
    n = 0
    try:
        for f in parse_file(fp):
            n += 1
            if pt_bus is None:
                if f.arbitration_id == PT_ANCHOR:
                    pt_bus = f.bus
                elif n > 4000:
                    return None
                continue
            if f.bus != pt_bus:
                continue
            aid = f.arbitration_id
            d = f.data
            if not is_parts and aid in PARTS_EXCLUSIVE_IDS:
                is_parts = True
            if aid == 0x430 and len(d) >= 8:
                if d[7] < 0xFE:
                    last_lv = round(d[7] * 0.1, 1)
                    if in_mainn and (lv_min is None or last_lv < lv_min):
                        lv_min = last_lv
                if d[4] < 0xFE:
                    last_tmax = round(d[4] * 0.5 - 40.0, 1)
                if d[5] < 0xFE:
                    last_tmin = round(d[5] * 0.5 - 40.0, 1)
            elif aid == 0x506 and len(d) >= 4:
                vals = [b - 40 for b in (d[1], d[2], d[3]) if b]
                if vals:
                    pack_t = max(vals)
            elif aid == 0x440 and len(d) >= 1:
                idx = (d[0] >> 2) & 0xF
                cur = MAINC[idx]
                if cur != prev:
                    if cur == "CLOSE_MAINR":
                        in_mainn = False
                        lv_min = None
                    elif cur == "CLOSE_MAINN":
                        in_mainn = True
                        lv_min = last_lv
                    elif prev == "CLOSE_MAINN":
                        in_mainn = False
                        events.append({
                            "success": cur == "WAIT_PRECHARGE",
                            "outcome": cur,
                            "lv_min": lv_min,
                            "cell_tmax": last_tmax,
                            "cell_tmin": last_tmin,
                            "pack_t": pack_t,
                        })
                    elif prev == "CLOSE_MAINR" and cur not in ("CLOSE_MAINN",):
                        # aborted before ever reaching CLOSE_MAINN (truck3-style)
                        events.append({
                            "success": False,
                            "outcome": "ABORT_AT_%s" % cur,
                            "lv_min": last_lv,
                            "cell_tmax": last_tmax,
                            "cell_tmin": last_tmin,
                            "pack_t": pack_t,
                        })
                    prev = cur
    except Exception:
        return None
    if not events:
        return None
    return {"events": events, "is_parts": is_parts}


files = []
for dirp in (PRIMARY_DIR, ANDROID_DIR):
    if dirp.exists():
        files += [p for p in dirp.rglob("*.log")] + [p for p in dirp.rglob("*.txt")]
print("scanning %d files..." % len(files), flush=True)

rows = []
for i, fp in enumerate(files):
    if i % 100 == 0:
        print("  %d/%d  (%d seqs)" % (i, len(files), len(rows)), flush=True)
    try:
        if os.path.getsize(fp) < 2000:
            continue
        r = scan_log(str(fp))
    except Exception:
        continue
    if not r:
        continue
    d = get_log_date(str(fp))
    bat = "main-orig" if (r["is_parts"] and d >= SWAP_DATE) or (not r["is_parts"] and d < SWAP_DATE) else "parts-orig"
    truck = "parts" if r["is_parts"] else "main"
    for e in r["events"]:
        e.update({"file": Path(fp).name, "date": d, "truck": truck, "bat": bat})
        rows.append(e)

print("\n%d sequences from %d files\n" % (len(rows), len(set(r['file'] for r in rows))))

print("=" * 100)
print("  OUTCOME vs PACK TEMPERATURE, by truck+battery")
print("=" * 100)
bins = defaultdict(lambda: {"ok": [], "fail": []})
for r in rows:
    t = r["cell_tmax"] if r["cell_tmax"] is not None else r["pack_t"]
    if t is None:
        continue
    bins["%s + %s" % (r["truck"], r["bat"])]["ok" if r["success"] else "fail"].append(t)

print("  %-26s %-32s %s" % ("bin", "SUCCESS cell_tmax (C)", "FAIL cell_tmax (C)"))
print("  " + "-" * 94)
for k in sorted(bins):
    ok, fl = bins[k]["ok"], bins[k]["fail"]
    f_ok = "n=%-3d %.1f-%.1f (mean %.1f)" % (len(ok), min(ok), max(ok), sum(ok) / len(ok)) if ok else "n=0"
    f_fl = "n=%-3d %.1f-%.1f (mean %.1f)" % (len(fl), min(fl), max(fl), sum(fl) / len(fl)) if fl else "n=0"
    print("  %-26s %-32s %s" % (k, f_ok, f_fl))

print()
print("=" * 100)
print("  ALL FAILURES IN DETAIL")
print("=" * 100)
print("  %-44s %-11s %-13s %-8s %-8s %s" % ("file", "date", "outcome", "cell_tmax", "12V min", "truck+bat"))
print("  " + "-" * 98)
for r in sorted([x for x in rows if not x["success"]], key=lambda x: x["date"]):
    print("  %-44s %-11s %-13s %-8s %-8s %s + %s"
          % (r["file"][:44], r["date"], r["outcome"][:13], r["cell_tmax"], r["lv_min"], r["truck"], r["bat"]))

print()
print("=" * 100)
print("  SUCCESSES AT HIGH TEMPERATURE (cell_tmax >= 30C) -- does warm always fail?")
print("=" * 100)
hot_ok = [r for r in rows if r["success"] and (r["cell_tmax"] or -99) >= 30]
print("  %d successful precharges at cell_tmax >= 30C" % len(hot_ok))
for r in sorted(hot_ok, key=lambda x: -(x["cell_tmax"] or 0))[:15]:
    print("    %-44s %-11s tmax=%.1fC  12Vmin=%s  %s+%s"
          % (r["file"][:44], r["date"], r["cell_tmax"], r["lv_min"], r["truck"], r["bat"]))
