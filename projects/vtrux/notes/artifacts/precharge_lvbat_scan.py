"""
Scan all Vtrux logs for precharge sequences.
For each CLOSE_MAINR->CLOSE_MAINN transition, records:
  - min lvbat during CLOSE_MAINN step
  - lvbat at start of CLOSE_MAINN
  - outcome (success = WAIT_PRECHARGE, fail = ALL_OPEN_SHUTDOWN)
  - truck identity (parts/main, from 0x391 presence or odometer)
  - log date (from filename timestamp or file mtime)
  - battery bin (main-orig / parts-orig, derived from truck + swap date)

Reports binned by truck+battery combo.
"""

import sys
import os
import re
import warnings
from pathlib import Path
from datetime import date
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

from canre.parsers import parse_file
import cantools

PRIMARY_DIR = Path("projects/vtrux/logs")
ANDROID_DIR = Path("../../CANLogs/VtruxLogs")
DBC_PATH    = "projects/vtrux/epri-pt-bus.dbc"
SWAP_DATE   = date(2025, 12, 9)

PARTS_ODO_KM_MIN = 38_600
PARTS_ODO_KM_MAX = 48_300
MAIN_ODO_KM_MIN  = 80_500
MAIN_ODO_KM_MAX  = 104_600

PARTS_EXCLUSIVE_IDS = {0x391, 0x552}
PT_ANCHOR = 0x051

MAINC_STAT = [
    "ALL_OPEN", "FAILED_MAINP_OR_R_WELD", "CLOSE_MAINR", "FAILED_MAINR_OPEN",
    "FAILED_MAINN_WELD", "CLOSE_MAINN", "FAILED_MAINN_OPEN", "WAIT_PRECHARGE",
    "CLOSE_MAINP", "OPEN_MAINR", "FAILED_MAINP_OPEN", "MAIN_PN_CLOSED_DRIVE",
    "MAIN_P_CLOSED_CHARGE", "SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN", "(idx15)",
]

db = cantools.database.load_file(DBC_PATH)


def get_log_date(filepath):
    m = re.search(r"_(\d{8})_", Path(filepath).name)
    if m:
        s = m.group(1)
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            pass
    mtime = os.path.getmtime(filepath)
    return date.fromtimestamp(mtime)


def scan_log(filepath):
    """
    Returns list of event dicts, one per CLOSE_MAINN conclusion found.
    Returns None if no precharge sequences or no PT bus found.
    """
    pt_bus = None
    is_parts_by_id = False
    odo_km = None
    last_lv = None

    in_mainn = False
    min_lv_in_mainn = None
    lv_at_mainn_start = None

    prev_state = None
    events = []
    frame_count = 0

    try:
        for f in parse_file(filepath):
            frame_count += 1

            if pt_bus is None:
                if f.arbitration_id == PT_ANCHOR:
                    pt_bus = f.bus
                elif frame_count > 4000:
                    return None
                continue

            if f.bus != pt_bus:
                continue

            aid = f.arbitration_id

            if not is_parts_by_id and aid in PARTS_EXCLUSIVE_IDS:
                is_parts_by_id = True

            if odo_km is None and aid == 0x625 and len(f.data) >= 3:
                odo_km = (f.data[0] << 16) | (f.data[1] << 8) | f.data[2]

            if aid == 0x430 and len(f.data) >= 7:
                try:
                    d = db.decode_message(0x430, bytes(f.data), decode_choices=False)
                    lv = d.get("bcm_lvbat")
                    if lv is not None:
                        last_lv = float(lv)
                        if in_mainn and last_lv is not None:
                            if min_lv_in_mainn is None or last_lv < min_lv_in_mainn:
                                min_lv_in_mainn = last_lv
                except Exception:
                    pass

            if aid == 0x440 and len(f.data) >= 1:
                try:
                    d = db.decode_message(0x440, bytes(f.data), decode_choices=False)
                    raw = d.get("bcm_mainc_stat")
                    if raw is None:
                        continue
                    idx = int(raw)
                    cur = MAINC_STAT[idx] if idx < len(MAINC_STAT) else f"idx{idx}"

                    if cur != prev_state:
                        if cur == "CLOSE_MAINR":
                            in_mainn = False
                            min_lv_in_mainn = None
                            lv_at_mainn_start = None

                        elif cur == "CLOSE_MAINN":
                            in_mainn = True
                            lv_at_mainn_start = last_lv
                            min_lv_in_mainn = last_lv

                        elif prev_state == "CLOSE_MAINN":
                            in_mainn = False
                            success = (cur == "WAIT_PRECHARGE")
                            events.append({
                                "success":         success,
                                "outcome":         cur,
                                "min_lvbat":       min_lv_in_mainn,
                                "lv_at_mainn":     lv_at_mainn_start,
                            })

                        prev_state = cur

                    elif in_mainn and last_lv is not None:
                        if min_lv_in_mainn is None or last_lv < min_lv_in_mainn:
                            min_lv_in_mainn = last_lv

                except Exception:
                    pass

    except Exception:
        return None

    if not events:
        return None

    if is_parts_by_id:
        truck = "parts"
    elif odo_km is not None:
        if PARTS_ODO_KM_MIN <= odo_km <= PARTS_ODO_KM_MAX:
            truck = "parts"
        elif MAIN_ODO_KM_MIN <= odo_km <= MAIN_ODO_KM_MAX:
            truck = "main"
        else:
            truck = f"unknown(odo={odo_km}km)"
    else:
        truck = "unknown"

    log_date = get_log_date(filepath)

    if truck == "main":
        battery = "main-orig" if log_date < SWAP_DATE else "parts-orig(TYPE2)"
    elif truck == "parts":
        battery = "parts-orig" if log_date < SWAP_DATE else "main-orig"
    else:
        battery = "unknown"

    filename = Path(filepath).name
    for ev in events:
        ev["truck"]    = truck
        ev["log_date"] = log_date
        ev["battery"]  = battery
        ev["filename"] = filename

    return events


log_files = sorted(PRIMARY_DIR.glob("*.log")) + sorted(ANDROID_DIR.glob("*.log"))
total = len(log_files)
print(f"Scanning {total} log files...", flush=True)

all_events = []
files_with_data = 0
for i, fp in enumerate(log_files):
    if i % 10 == 0:
        print(f"  {i}/{total} files scanned, {len(all_events)} sequences found so far...", flush=True)
    result = scan_log(str(fp))
    if result:
        all_events.extend(result)
        files_with_data += 1

print(f"\nDone. {files_with_data} files had precharge sequences. {len(all_events)} total sequences.\n")

bins = defaultdict(lambda: {"success": [], "fail": []})
for ev in all_events:
    key = f"{ev['truck']} + {ev['battery']}"
    bins[key]["success" if ev["success"] else "fail"].append(ev)

def lv_range(evs):
    vals = [e["min_lvbat"] for e in evs if e["min_lvbat"] is not None]
    if not vals:
        return "n/a"
    return f"{min(vals):.1f}-{max(vals):.1f}V"

print(f"{'Bin':<38}  {'N':>4}  {'OK':>4}  {'FAIL':>4}  {'min_lv OK':>12}  {'min_lv FAIL':>12}")
print("-" * 82)
for key in sorted(bins.keys()):
    b = bins[key]
    n = len(b["success"]) + len(b["fail"])
    print(f"{key:<38}  {n:>4}  {len(b['success']):>4}  {len(b['fail']):>4}  {lv_range(b['success']):>12}  {lv_range(b['fail']):>12}")

print()
print("--- All sequences (sorted by truck / date) ---")
print(f"{'date':>12}  {'truck':>6}  {'battery':<22}  {'result':>7}  {'lv_min':>7}  {'lv_at_mainn':>12}  filename")
print("-" * 110)
for ev in sorted(all_events, key=lambda e: (e["truck"], e["log_date"], e["filename"])):
    res = "OK" if ev["success"] else "FAIL"
    lv  = f"{ev['min_lvbat']:.1f}V" if ev["min_lvbat"] is not None else "n/a"
    lva = f"{ev['lv_at_mainn']:.1f}V" if ev["lv_at_mainn"] is not None else "n/a"
    print(f"{str(ev['log_date']):>12}  {ev['truck']:>6}  {ev['battery']:<22}  {res:>7}  {lv:>7}  {lva:>12}  {ev['filename']}")
