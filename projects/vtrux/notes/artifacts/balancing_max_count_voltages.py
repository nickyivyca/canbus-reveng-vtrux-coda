"""
balancing_max_count_voltages.py

Show cell voltages (vmax, vmin, spread) and SOC during frames where
bcm_balancing_cnt == 116 (all cells balancing simultaneously).

Signals:
  0x430: bcm_cell_vmax, bcm_cell_vmin (13-bit Motorola, 1 mV/count)
  0x440: bcm_balancing_cnt (B7, raw count)
  0x410: bcm_soc (B3, *0.5 %)

Usage:
  py -3.12 projects/vtrux/notes/artifacts/balancing_max_count_voltages.py
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
TARGET_CNT = 116


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

    soc_ts    = []   # (t, soc_pct)
    cnt_ts    = []   # (t, cnt)
    spread_ts = []   # (t, vmax_V, vmin_V)

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
                dec = msg_430.decode(frame.data, decode_choices=False)
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
        "pt_bus":    pt_bus,
    }


def nearest(series, t):
    """Return value from series (list of (t, ...)) nearest in time to t."""
    return min(series, key=lambda x: abs(x[0] - t))


def report_session(s):
    name = s["name"]
    t0   = s["t0"]
    print(f"\n{'='*65}")
    print(f"Session: {name}")

    target_cnt_frames = [(t, c) for t, c in s["cnt_ts"] if c == TARGET_CNT]
    if not target_cnt_frames:
        print(f"  No frames with cnt={TARGET_CNT}")
        return

    print(f"  Frames with cnt={TARGET_CNT}: {len(target_cnt_frames)}")

    vmaxes = []
    vmins  = []
    socs   = []
    times  = []

    for t, c in target_cnt_frames:
        _, vmax, vmin = nearest(s["spread_ts"], t)
        _, soc        = nearest(s["soc_ts"], t)
        vmaxes.append(vmax * 1000)
        vmins.append(vmin * 1000)
        socs.append(soc)
        times.append(t - t0)

    print(f"  vmax during cnt=116:  min={min(vmaxes):.0f} mV  max={max(vmaxes):.0f} mV  mean={sum(vmaxes)/len(vmaxes):.0f} mV")
    print(f"  vmin during cnt=116:  min={min(vmins):.0f} mV  max={max(vmins):.0f} mV  mean={sum(vmins)/len(vmins):.0f} mV")
    spreads = [vx - vn for vx, vn in zip(vmaxes, vmins)]
    print(f"  spread (vmax-vmin):   min={min(spreads):.0f} mV  max={max(spreads):.0f} mV  mean={sum(spreads)/len(spreads):.0f} mV")
    print(f"  SOC during cnt=116:   min={min(socs):.1f}%  max={max(socs):.1f}%  mean={sum(socs)/len(socs):.1f}%")
    print(f"  Time range:           t+{min(times):.0f}s  to  t+{max(times):.0f}s")

    # Sample a few representative moments: first, middle, last
    indices = [0, len(target_cnt_frames)//4, len(target_cnt_frames)//2,
               3*len(target_cnt_frames)//4, len(target_cnt_frames)-1]
    indices = sorted(set(indices))
    print(f"\n  Sample moments (first/25%/50%/75%/last):")
    print(f"  {'t+':>8}  {'SOC':>6}  {'vmax mV':>8}  {'vmin mV':>8}  {'spread mV':>10}")
    for i in indices:
        t, c = target_cnt_frames[i]
        print(f"  {times[i]:>8.0f}s  {socs[i]:>5.1f}%  {vmaxes[i]:>8.0f}  {vmins[i]:>8.0f}  {spreads[i]:>10.0f}")

    # Distribution of vmin values in 5 mV buckets to see clustering
    print(f"\n  vmin distribution during cnt=116 (5 mV buckets):")
    bucket_size = 5
    from collections import Counter
    vmin_buckets = Counter(int(v // bucket_size) * bucket_size for v in vmins)
    for bkt in sorted(vmin_buckets):
        bar = "#" * (vmin_buckets[bkt] * 40 // max(vmin_buckets.values()))
        print(f"  {bkt:4d}-{bkt+bucket_size-1:4d} mV: {vmin_buckets[bkt]:5d}  {bar}")

    # Also show what the cnt distribution looks like around the 116 peak
    print(f"\n  Count distribution near peak (110-116):")
    from collections import Counter
    cnt_dist = Counter(c for _, c in s["cnt_ts"] if c >= 110)
    for v in sorted(cnt_dist):
        print(f"  cnt={v}: {cnt_dist[v]} frames")


def main():
    print("Loading DBC...")
    db = cantools.db.load_file(DBC_PATH)

    sessions = []
    full_charge = os.path.join(LOGS_ROOT, "full-charge-then-fail.log")
    if os.path.exists(full_charge):
        sessions.append(("full_charge_then_fail", [full_charge]))
    swap_groups = group_files_by_session(Path(SWAP_ROOT))
    for gname, files in sorted(swap_groups.items()):
        sessions.append((f"after_swap_{gname}", files))

    print(f"Sessions: {[s[0] for s in sessions]}")
    print("Processing...\n")

    for name, files in sessions:
        print(f"  {name}...")
        s = process_session(name, files, db)
        if s:
            report_session(s)
        else:
            print(f"  [{name}] insufficient data, skipped")


if __name__ == "__main__":
    main()
