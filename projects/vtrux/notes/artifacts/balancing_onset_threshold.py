"""
balancing_onset_threshold.py

Two questions:
1. Does vmax (bcm_cell_vmax) cross the balancing threshold right when
   bcm_balancing_cnt first goes non-zero?  Show a per-frame window around onset.
2. Does the January vtrux_parts_charge session show the same behavior?

Sessions covered:
  - after-battery-swap-charges (M0_a, M0_b)
  - full-charge-then-fail.log (main logs root)
  - vtrux_parts_charge_M1 (January session, main logs root, T0-T29 excluding drive T20)

Usage:
  py -3.12 projects/vtrux/notes/artifacts/balancing_onset_threshold.py
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
WINDOW_S = 120


def identify_pt_bus(file_paths):
    counts = {}
    for i, frame in enumerate(merge_files(file_paths)):
        if frame.arbitration_id in PT_BUS_ANCHOR_IDS:
            counts[frame.bus] = counts.get(frame.bus, 0) + 1
        if i >= SAMPLE_LIMIT:
            break
    return max(counts, key=counts.get) if counts else None


def t_key(path):
    """Extract T-number for sorting: vtrux_parts_charge_M1_T7.log -> 7"""
    m = re.search(r"_T(\d+)", str(path))
    return int(m.group(1)) if m else 0


def collect_parts_charge_files():
    """Collect vtrux_charge_M1 T-chunks (January session), sorted by T number, skip drive T20."""
    files = sorted(
        [f for f in Path(LOGS_ROOT).glob("vtrux_charge_M1_T*.log")],
        key=t_key
    )
    return files


def process_session(name, files, db):
    file_paths = [str(f) for f in files]
    pt_bus = identify_pt_bus(file_paths)
    if pt_bus is None:
        print(f"  [{name}] Could not identify PT bus, skipping.")
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
        print(f"  [{name}] Insufficient data.")
        return None

    return {
        "name":      name,
        "t0":        soc_ts[0][0],
        "soc_ts":    soc_ts,
        "cnt_ts":    cnt_ts,
        "spread_ts": spread_ts,
        "pt_bus":    pt_bus,
    }


def nearest(series, t):
    return min(series, key=lambda x: abs(x[0] - t))


def report_session(s):
    name = s["name"]
    t0   = s["t0"]
    soc_vals = [v for _, v in s["soc_ts"]]
    max_soc  = max(soc_vals)

    print(f"\n{'='*70}")
    print(f"Session: {name}  |  PT bus: {s['pt_bus']}")
    print(f"SOC range: {min(soc_vals):.1f}% -> {max_soc:.1f}%  |  "
          f"Duration: {(s['soc_ts'][-1][0] - t0)/60:.1f} min")

    nonzero = [(t, c) for t, c in s["cnt_ts"] if c > 0]
    if not nonzero:
        print("  No non-zero balancing_cnt.")
        return

    onset_t, onset_c = nonzero[0]
    peak_t, peak_c   = max(s["cnt_ts"], key=lambda x: x[1])
    onset_soc = nearest(s["soc_ts"], onset_t)[1]

    print(f"\nOnset: t+{onset_t - t0:.0f}s  cnt={onset_c}  SOC~{onset_soc:.1f}%")
    print(f"Peak:  t+{peak_t - t0:.0f}s  cnt={peak_c}")

    print(f"\nPer-frame window around onset ({WINDOW_S}s before to {WINDOW_S}s after):")
    print(f"{'rel_t':>8}  {'vmax mV':>8}  {'vmin mV':>8}  {'spread':>7}  {'cnt':>5}  {'SOC%':>6}")

    window_spread = [(t, vx, vn) for t, vx, vn in s["spread_ts"]
                     if abs(t - onset_t) <= WINDOW_S]
    window_cnt    = [(t, c) for t, c in s["cnt_ts"]
                     if abs(t - onset_t) <= WINDOW_S]

    last_cnt_t = None
    for t, vmax, vmin in window_spread:
        cnt_val = nearest(window_cnt, t)[1] if window_cnt else 0
        soc_val = nearest(s["soc_ts"], t)[1]
        marker = " <-- ONSET" if abs(t - onset_t) < 2.0 and last_cnt_t is None and cnt_val > 0 else ""
        if marker:
            last_cnt_t = t
        print(f"{t - onset_t:>+8.1f}s  {vmax*1000:>8.0f}  {vmin*1000:>8.0f}  "
              f"{(vmax-vmin)*1000:>7.0f}  {cnt_val:>5}  {soc_val:>6.1f}%{marker}")

    print(f"\nStats when cnt=116:")
    frames_116 = [(t, c) for t, c in s["cnt_ts"] if c == 116]
    if not frames_116:
        print("  No cnt=116 frames in this session.")
    else:
        vmaxes = [nearest(s["spread_ts"], t)[1]*1000 for t, _ in frames_116]
        vmins  = [nearest(s["spread_ts"], t)[1+1]*1000 for t, _ in frames_116]
        vmins  = [nearest(s["spread_ts"], t)[2]*1000 for t, _ in frames_116]
        spreads = [vx - vn for vx, vn in zip(vmaxes, vmins)]
        print(f"  cnt=116 frames: {len(frames_116)}")
        print(f"  vmax: min={min(vmaxes):.0f}  max={max(vmaxes):.0f}  mean={sum(vmaxes)/len(vmaxes):.0f} mV")
        print(f"  vmin: min={min(vmins):.0f}  max={max(vmins):.0f}  mean={sum(vmins)/len(vmins):.0f} mV")
        print(f"  spread: min={min(spreads):.0f}  max={max(spreads):.0f}  mean={sum(spreads)/len(spreads):.0f} mV")

    print(f"\nCount distribution (all non-zero values):")
    from collections import Counter
    dist = Counter(c for _, c in s["cnt_ts"] if c > 0)
    for val in sorted(dist):
        bar = "#" * min(40, dist[val] * 40 // max(dist.values()))
        print(f"  cnt={val:3d}: {dist[val]:6d}  {bar}")


def main():
    print("Loading DBC...")
    db = cantools.database.load_file(DBC_PATH)

    sessions = []

    full_charge = os.path.join(LOGS_ROOT, "full-charge-then-fail.log")
    if os.path.exists(full_charge):
        sessions.append(("full_charge_then_fail", [full_charge]))
    else:
        print(f"  Note: {full_charge} not found, skipping.")

    swap_groups = group_files_by_session(Path(SWAP_ROOT))
    for gname, files in sorted(swap_groups.items()):
        sessions.append((f"after_swap_{gname}", files))

    parts_files = collect_parts_charge_files()
    if parts_files:
        sessions.append(("vtrux_charge_M1_jan25", parts_files))
        print(f"  Found {len(parts_files)} vtrux_charge_M1 files (T0-T29 excl T20 drive).")
    else:
        print("  No vtrux_charge_M1 files found.")

    print(f"Sessions: {[s[0] for s in sessions]}")
    print("Processing (two passes per session)...\n")

    for name, files in sessions:
        print(f"  Processing {name} ({len(files)} file(s))...")
        s = process_session(name, files, db)
        if s:
            report_session(s)


if __name__ == "__main__":
    main()
