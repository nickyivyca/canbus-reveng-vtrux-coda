"""
balancing_cell_voltage_spread.py

For each completed charge session, extract bcm_cell_vmax, bcm_cell_vmin,
spread (vmax-vmin), and bcm_balancing_cnt to understand how cell voltage
spread relates to balancing behavior.

Signals (all from epri-pt-bus.dbc):
  0x430: bcm_cell_vmax (13-bit Motorola, 1 mV/count)
         bcm_cell_vmin (13-bit Motorola, 1 mV/count)
  0x440: bcm_balancing_cnt (B7, raw count, invalid if >=0xFE)
  0x410: bcm_soc (B3, *0.5 %, invalid if >=0xFE)

Usage:
  py -3.12 projects/vtrux/notes/artifacts/balancing_cell_voltage_spread.py
"""

import os
import sys
import cantools
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from canre.utils.merge import merge_files
from canre.utils.sessions import group_files_by_session

DBC_PATH  = os.path.join(PROJECT_ROOT, "projects", "vtrux", "epri-pt-bus.dbc")
LOGS_ROOT = os.path.join(PROJECT_ROOT, "projects", "vtrux", "logs")
SWAP_ROOT = os.path.join(LOGS_ROOT, "after-battery-swap-charges")

PT_BUS_ANCHOR_IDS = {0x410, 0x420, 0x430, 0x440, 0x471}
SAMPLE_LIMIT = 200000


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
        print(f"  [{name}] Could not identify PT bus, skipping.")
        return None

    msg_430 = db.get_message_by_frame_id(0x430)
    msg_440 = db.get_message_by_frame_id(0x440)

    # Per-frame samples: (time, soc, vmax, vmin, cnt)
    # We'll track last-known values and emit a combined sample whenever any
    # of the three messages updates.
    last_soc  = None
    last_vmax = None
    last_vmin = None
    last_cnt  = None

    soc_ts   = []   # (t, soc)
    spread_ts = []  # (t, vmax, vmin, spread_mV)
    cnt_ts   = []   # (t, cnt)

    for frame in merge_files(file_paths):
        if frame.bus != pt_bus:
            continue

        t = frame.timestamp
        aid = frame.arbitration_id

        if aid == 0x410 and len(frame.data) >= 4:
            raw = frame.data[3]
            if raw < 0xFE:
                soc_ts.append((t, raw * 0.5))

        elif aid == 0x430 and len(frame.data) >= 4:
            try:
                dec = msg_430.decode(frame.data, decode_choices=False)
                vmax = dec.get("bcm_cell_vmax")
                vmin = dec.get("bcm_cell_vmin")
                if vmax is not None and vmin is not None:
                    # Sentinel: vmax raw 0x1FFE = 8.190 V -- skip
                    if vmax < 8.0 and vmin < 8.0 and vmin > 0:
                        spread_mV = round((vmax - vmin) * 1000, 1)
                        spread_ts.append((t, vmax, vmin, spread_mV))
            except Exception:
                pass

        elif aid == 0x440 and len(frame.data) >= 8:
            raw = frame.data[7]
            if raw < 0xFE:
                cnt_ts.append((t, raw))

    if not soc_ts or not spread_ts:
        print(f"  [{name}] Insufficient data.")
        return None

    soc_vals = [s for _, s in soc_ts]
    max_soc  = max(soc_vals)

    return {
        "name":      name,
        "files":     len(files),
        "duration_s": soc_ts[-1][0] - soc_ts[0][0] if len(soc_ts) > 1 else 0,
        "soc_max":   max_soc,
        "reached_100": max_soc >= 100.0,
        "soc_ts":    soc_ts,
        "spread_ts": spread_ts,
        "cnt_ts":    cnt_ts,
        "pt_bus":    pt_bus,
    }


def report_session(s):
    name  = s["name"]
    dur_m = s["duration_s"] / 60.0
    t0    = s["soc_ts"][0][0]

    print(f"\n{'='*65}")
    print(f"Session: {name}")
    print(f"  Files: {s['files']}  Duration: {dur_m:.1f} min  PT bus: {s['pt_bus']}")
    print(f"  SOC range: {min(v for _,v in s['soc_ts']):.1f}% -> {s['soc_max']:.1f}%")

    spreads = s["spread_ts"]
    cnts    = s["cnt_ts"]

    if not spreads:
        print("  No spread data.")
        return

    all_spreads = [sp for _,_,_,sp in spreads]
    print(f"  Spread (vmax-vmin): min={min(all_spreads):.1f} mV  "
          f"max={max(all_spreads):.1f} mV  "
          f"mean={sum(all_spreads)/len(all_spreads):.1f} mV")

    # Find balancing onset (first non-zero cnt)
    nonzero_cnt = [(t, c) for t, c in cnts if c > 0]

    if nonzero_cnt:
        onset_t, onset_c = nonzero_cnt[0]
        last_t,  last_c  = nonzero_cnt[-1]

        # Nearest spread sample to onset
        onset_spread = min(spreads, key=lambda x: abs(x[0] - onset_t))
        last_spread  = min(spreads, key=lambda x: abs(x[0] - last_t))

        # Nearest SOC at onset
        onset_soc = min(s["soc_ts"], key=lambda x: abs(x[0] - onset_t))

        print(f"\n  Balancing onset:  t+{onset_t - t0:.0f}s  cnt={onset_c}  "
              f"SOC~{onset_soc[1]:.1f}%  "
              f"spread~{onset_spread[3]:.1f} mV  "
              f"(vmax={onset_spread[1]*1000:.0f} mV  vmin={onset_spread[2]*1000:.0f} mV)")
        print(f"  Balancing end:    t+{last_t - t0:.0f}s  cnt={last_c}  "
              f"spread~{last_spread[3]:.1f} mV  "
              f"(vmax={last_spread[1]*1000:.0f} mV  vmin={last_spread[2]*1000:.0f} mV)")

        # Peak cnt
        peak_t, peak_c = max(cnts, key=lambda x: x[1])
        peak_spread = min(spreads, key=lambda x: abs(x[0] - peak_t))
        peak_soc    = min(s["soc_ts"], key=lambda x: abs(x[0] - peak_t))
        print(f"  Balancing peak:   t+{peak_t - t0:.0f}s  cnt={peak_c}  "
              f"SOC~{peak_soc[1]:.1f}%  "
              f"spread~{peak_spread[3]:.1f} mV  "
              f"(vmax={peak_spread[1]*1000:.0f} mV  vmin={peak_spread[2]*1000:.0f} mV)")
    else:
        print("  No non-zero balancing_cnt observed.")

    # 10-min timeline: SOC, spread_mean, cnt_mean
    print(f"\n  Timeline (10-min buckets):")
    print(f"  {'bucket':>8}  {'SOC':>6}  {'spread_mean':>11}  {'spread_max':>10}  {'cnt_mean':>8}  {'cnt_max':>7}")

    def bucket_idx(t):
        return int((t - t0) / 600)

    soc_b   = {}
    spr_b   = {}
    cnt_b   = {}

    for t, v in s["soc_ts"]:
        soc_b.setdefault(bucket_idx(t), []).append(v)
    for t, vmax, vmin, sp in spreads:
        spr_b.setdefault(bucket_idx(t), []).append(sp)
    for t, c in cnts:
        cnt_b.setdefault(bucket_idx(t), []).append(c)

    for b in sorted(set(list(soc_b) + list(spr_b) + list(cnt_b))):
        sv = soc_b.get(b, [])
        spv = spr_b.get(b, [])
        cv  = cnt_b.get(b, [])
        avg_soc = f"{sum(sv)/len(sv):.1f}%" if sv else "  n/a"
        avg_spr = f"{sum(spv)/len(spv):.1f}" if spv else "  n/a"
        max_spr = f"{max(spv):.1f}" if spv else "  n/a"
        avg_cnt = f"{sum(cv)/len(cv):.1f}" if cv else "  n/a"
        max_cnt = f"{max(cv)}" if cv else "n/a"
        print(f"  t+{b*10:>4}min  {avg_soc:>6}  {avg_spr:>11}  {max_spr:>10}  {avg_cnt:>8}  {max_cnt:>7}")


def main():
    print("Loading DBC...")
    db = cantools.db.load_file(DBC_PATH)

    sessions = []

    full_charge = os.path.join(LOGS_ROOT, "full charge then fail.log")
    if os.path.exists(full_charge):
        sessions.append(("full_charge_then_fail", [full_charge]))

    swap_groups = group_files_by_session(Path(SWAP_ROOT))
    for gname, files in sorted(swap_groups.items()):
        sessions.append((f"after_swap_{gname}", files))

    print(f"Sessions: {[s[0] for s in sessions]}")
    print("Processing (two passes per session)...\n")

    results = []
    for name, files in sessions:
        print(f"  {name} ({len(files)} file(s))...")
        s = process_session(name, files, db)
        if s:
            results.append(s)

    print(f"\n{'#'*65}")
    print("CELL VOLTAGE SPREAD vs BALANCING REPORT")
    print(f"{'#'*65}")

    for s in results:
        report_session(s)

    if not results:
        print("No sessions processed.")


if __name__ == "__main__":
    main()
