"""
balancing_onset_to_116_ramp.py

For each session, show how bcm_balancing_cnt climbs from first non-zero
to 116, with vmax/vmin at each step.

Output:
  - Timeline binned every 30s from onset to first cnt=116
  - Count distribution during the ramp (onset to first cnt=116)
  - Voltage at key count milestones (first time cnt reaches 12, 52, 104, 116)

Usage:
  py -3.12 projects/vtrux/notes/artifacts/balancing_onset_to_116_ramp.py
"""

import os
import sys
import cantools
from pathlib import Path
import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from canre.utils.merge import merge_files
from canre.utils.sessions import group_files_by_session

DBC_PATH  = os.path.join(PROJECT_ROOT, "projects", "vtrux", "epri-pt-bus.dbc")
LOGS_ROOT = os.path.join(PROJECT_ROOT, "projects", "vtrux", "logs")
SWAP_ROOT = os.path.join(LOGS_ROOT, "after-battery-swap-charges")
PT_BUS_ANCHOR_IDS = {0x410, 0x420, 0x430, 0x440, 0x471}
SAMPLE_LIMIT = 200000
MILESTONES = [1, 12, 52, 104, 115, 116]


def identify_pt_bus(file_paths):
    counts = {}
    for i, frame in enumerate(merge_files(file_paths)):
        if frame.arbitration_id in PT_BUS_ANCHOR_IDS:
            counts[frame.bus] = counts.get(frame.bus, 0) + 1
        if i >= SAMPLE_LIMIT:
            break
    return max(counts, key=counts.get) if counts else None


def process_session(name, files, db):
    file_paths = [str(f) for f in files]
    pt_bus = identify_pt_bus(file_paths)
    if pt_bus is None:
        return None

    msg_430 = db.get_message_by_frame_id(0x430)

    soc_ts    = []
    cnt_ts    = []
    spread_ts = []

    for frame in merge_files(file_paths):
        if frame.bus != pt_bus:
            continue
        t   = frame.timestamp
        aid = frame.arbitration_id

        if aid == 0x410 and len(frame.data) >= 4:
            raw = frame.data[3]
            if raw < 0xFE:
                soc_ts.append((t, raw * 0.5))

        elif aid == 0x430 and len(frame.data) >= 4:
            try:
                dec  = msg_430.decode(frame.data, decode_choices=False)
                vmax = dec.get("bcm_cell_vmax")
                vmin = dec.get("bcm_cell_vmin")
                if vmax is not None and vmin is not None and vmax < 8.0 and vmin > 0:
                    spread_ts.append((t, vmax, vmin))
            except Exception:
                pass

        elif aid == 0x440 and len(frame.data) >= 8:
            raw = frame.data[7]
            if raw < 0xFE:
                cnt_ts.append((t, raw))

    if not soc_ts or not spread_ts or not cnt_ts:
        return None

    return {
        "name":      name,
        "t0":        soc_ts[0][0],
        "soc_ts":    soc_ts,
        "cnt_ts":    cnt_ts,
        "spread_ts": spread_ts,
    }


def nearest(series, t):
    return min(series, key=lambda x: abs(x[0] - t))


def report_session(s):
    name = s["name"]
    t0   = s["t0"]

    nonzero = [(t, c) for t, c in s["cnt_ts"] if c > 0]
    if not nonzero:
        print(f"\n{name}: no balancing.")
        return

    onset_t = nonzero[0][0]

    first_116 = next(((t, c) for t, c in s["cnt_ts"] if c == 116), None)
    if first_116 is None:
        print(f"\n{name}: never reached cnt=116.")
        return

    ramp_end_t = first_116[0]
    ramp_s = ramp_end_t - onset_t

    onset_soc = nearest(s["soc_ts"], onset_t)[1]
    end_soc   = nearest(s["soc_ts"], ramp_end_t)[1]

    print(f"\n{'='*65}")
    print(f"Session: {name}")
    print(f"  Onset:    t+{onset_t - t0:.0f}s  SOC={onset_soc:.1f}%")
    print(f"  cnt=116:  t+{ramp_end_t - t0:.0f}s  SOC={end_soc:.1f}%")
    print(f"  Ramp duration: {ramp_s:.0f}s ({ramp_s/60:.1f} min)")

    print(f"\n  First time each milestone count is reached:")
    print(f"  {'cnt':>5}  {'rel_t':>8}  {'vmax mV':>8}  {'vmin mV':>8}  {'spread':>7}  {'SOC%':>6}")
    for m in MILESTONES:
        hit = next(((t, c) for t, c in s["cnt_ts"] if c >= m), None)
        if hit:
            ht = hit[0]
            _, vmax, vmin = nearest(s["spread_ts"], ht)
            soc = nearest(s["soc_ts"], ht)[1]
            print(f"  {m:>5}  {ht-onset_t:>+8.0f}s  {vmax*1000:>8.0f}  {vmin*1000:>8.0f}  "
                  f"{(vmax-vmin)*1000:>7.0f}  {soc:>6.1f}%")

    ramp_cnt = [(t, c) for t, c in s["cnt_ts"] if onset_t <= t <= ramp_end_t]
    ramp_spr = [(t, vx, vn) for t, vx, vn in s["spread_ts"] if onset_t <= t <= ramp_end_t]

    print(f"\n  Timeline during ramp (30s buckets):")
    print(f"  {'rel_t':>8}  {'cnt_mean':>9}  {'cnt_max':>8}  {'vmax_mean':>10}  {'vmin_mean':>10}  {'spread_mean':>12}  {'SOC':>6}")

    bucket_s = 30
    max_b = int(ramp_s / bucket_s) + 1
    for b in range(max_b + 1):
        b_start = onset_t + b * bucket_s
        b_end   = b_start + bucket_s
        bc = [c for t, c in ramp_cnt if b_start <= t < b_end]
        bs = [(vx, vn) for t, vx, vn in ramp_spr if b_start <= t < b_end]
        bsoc = [v for t, v in s["soc_ts"] if b_start <= t < b_end]
        if not bc and not bs:
            continue
        cnt_mean = sum(bc)/len(bc) if bc else float("nan")
        cnt_max  = max(bc) if bc else float("nan")
        vmax_m   = sum(vx for vx, _ in bs)/len(bs)*1000 if bs else float("nan")
        vmin_m   = sum(vn for _, vn in bs)/len(bs)*1000 if bs else float("nan")
        spr_m    = vmax_m - vmin_m if bs else float("nan")
        soc_m    = sum(bsoc)/len(bsoc) if bsoc else float("nan")
        print(f"  {b*bucket_s:>+8.0f}s  {cnt_mean:>9.1f}  {cnt_max:>8}  "
              f"{vmax_m:>10.0f}  {vmin_m:>10.0f}  {spr_m:>12.0f}  {soc_m:>6.1f}%")


def t_key(path):
    m = re.search(r"_T(\d+)", str(path))
    return int(m.group(1)) if m else 0


def main():
    print("Loading DBC...")
    db = cantools.database.load_file(DBC_PATH)

    sessions = []
    full_charge = os.path.join(LOGS_ROOT, "full-charge-then-fail.log")
    if os.path.exists(full_charge):
        sessions.append(("full_charge_then_fail", [full_charge]))

    swap_groups = group_files_by_session(Path(SWAP_ROOT))
    for gname, files in sorted(swap_groups.items()):
        sessions.append((f"after_swap_{gname}", files))

    charge_files = sorted(Path(LOGS_ROOT).glob("vtrux_charge_M1_T*.log"), key=t_key)
    if charge_files:
        sessions.append(("vtrux_charge_M1_jan25", charge_files))

    print(f"Sessions: {[s[0] for s in sessions]}")
    print("Processing...\n")

    for name, files in sessions:
        print(f"  {name} ({len(files)} file(s))...")
        s = process_session(name, files, db)
        if s:
            report_session(s)
        else:
            print(f"  [{name}] insufficient data")


if __name__ == "__main__":
    main()
