"""
sample_0x6000002.py

1.  Sample 0x6000002 frames at different torque levels (using 0x5A2 B4-B5 as
    the confirmed traction-motor torque reference) to understand B4 encoding.

2.  Scan for phase-current-RMS analog (correlate |torque| against every byte
    on the PT bus) — analog to 0x395 B7 for the generator.

3.  Explicit r vs |torque| for 0x472 bytes if 0x472 is present.

Machine: the bench PC  Python: py -3.12
Log:     vtruxcurrentlimitingtest.log
"""

import re
import math
import sys
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]
LOG_PATH     = PROJECT_ROOT / "projects" / "vtrux" / "logs" / "vtruxcurrentlimitingtest.log"
OUTPUT_FILE  = SCRIPT_DIR / "sample_0x6000002_output.txt"

# Thresholds matching find_torque_feedback.py
RPM_MTR_MIN = 200
MAX_DT       = 0.12    # s for RPM lookup
TOP_N        = 25

# ── BUSMASTER parser ─────────────────────────────────────────────────────────
BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+'
    r'0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+'
    r'((?:[0-9A-Fa-f]{2}\s*)+)'
)

def parse_ts(ts_str):
    h, m, s, t = ts_str.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001

def parse_log(log_path):
    buses = defaultdict(lambda: defaultdict(list))
    t0 = None
    with open(log_path, 'r', errors='replace') as f:
        for line in f:
            m = BUSMASTER_RE.match(line.strip())
            if not m:
                continue
            ts_str, bus_str, id_str, dlc_str, data_str = m.groups()
            ts = parse_ts(ts_str)
            if t0 is None:
                t0 = ts
            t   = ts - t0
            bus = int(bus_str)
            mid = int(id_str, 16)
            dat = [int(b, 16) for b in data_str.strip().split()]
            buses[bus][mid].append((t, dat))
    return buses

def find_pt_bus(buses):
    for bus, ids in buses.items():
        if 0x051 in ids and len(ids[0x051]) > 10:
            return bus
    return None

def u16_le(data, b):
    if len(data) < b+2:
        return None
    return data[b] | (data[b+1] << 8)

def nearest(ts_vals, t, max_dt=0.5):
    """Return the value nearest to t within max_dt, or None."""
    if not ts_vals:
        return None
    lo, hi = 0, len(ts_vals)-1
    while lo < hi:
        mid = (lo+hi)//2
        if ts_vals[mid][0] < t:
            lo = mid+1
        else:
            hi = mid
    best_i, best_dt = lo, abs(ts_vals[lo][0] - t)
    for i in (lo-1, lo+1):
        if 0 <= i < len(ts_vals):
            dt = abs(ts_vals[i][0] - t)
            if dt < best_dt:
                best_dt, best_i = dt, i
    return ts_vals[best_i][1] if best_dt <= max_dt else None

def pearson(xs, ys):
    n = len(xs)
    if n < 20:
        return None
    mx = sum(xs)/n;  my = sum(ys)/n
    sx = math.sqrt(sum((x-mx)**2 for x in xs)/n)
    sy = math.sqrt(sum((y-my)**2 for y in ys)/n)
    if sx < 1e-9 or sy < 1e-9:
        return None
    return sum((xs[i]-mx)*(ys[i]-my) for i in range(n)) / n / (sx*sy)

def interp_nearest(ts_list, t_grid, max_dt=0.5):
    if len(ts_list) < 5:
        return None
    result = []
    for t in t_grid:
        v = nearest(ts_list, t, max_dt)
        if v is None:
            return None
        result.append(v)
    return result


def main():
    lines = []
    def w(s=""):
        print(s)
        lines.append(s)

    w(f"sample_0x6000002.py — drivetrain torque/phase-RMS probe")
    w(f"Log: {LOG_PATH.name}")

    if not LOG_PATH.exists():
        w(f"ERROR: log not found: {LOG_PATH}")
        return

    w("Parsing log...")
    buses = parse_log(LOG_PATH)
    pt_bus = find_pt_bus(buses)
    if pt_bus is None:
        w("ERROR: PT bus not found (no 0x051)")
        return
    pt_ids = buses[pt_bus]
    w(f"PT bus: {pt_bus}, {len(pt_ids)} unique IDs")

    # ── Build torque reference from 0x5A2 B4-B5 ─────────────────────────────
    # 0x5A2 B4-B5 is the confirmed traction motor torque signal
    # Build (t, trq_raw, rpm_raw) from 0x5A2
    trq_ts  = []   # (t, trq_centered)  — for nearest lookup
    rpm_ts  = []   # (t, rpm_centered)
    for t, dat in pt_ids.get(0x5A2, []):
        rpm_raw = u16_le(dat, 2)
        trq_raw = u16_le(dat, 4)
        if rpm_raw is not None and trq_raw is not None:
            rpm_c = rpm_raw - 32768
            trq_c = trq_raw - 32768
            rpm_ts.append((t, rpm_c))
            trq_ts.append((t, trq_c))

    if not trq_ts:
        w("ERROR: no 0x5A2 data on PT bus")
        return

    # Build filtered reference grid (|RPM| > threshold)
    t_grid, T_ref, ABS_T_ref, RPM_ref = [], [], [], []
    for t, trq_c in trq_ts:
        rpm_c = nearest(rpm_ts, t, MAX_DT)
        if rpm_c is None or abs(rpm_c) < RPM_MTR_MIN:
            continue
        t_grid.append(t)
        T_ref.append(trq_c)
        ABS_T_ref.append(abs(trq_c))
        RPM_ref.append(rpm_c)

    w(f"Torque reference: {len(t_grid)} frames with |RPM|>{RPM_MTR_MIN}")
    w(f"  T range: {min(T_ref)} to {max(T_ref)}")
    w(f"  |T| range: {min(ABS_T_ref)} to {max(ABS_T_ref)}")
    w(f"  RPM range: {min(RPM_ref)} to {max(RPM_ref)}")

    # ── SECTION 1: Sample 0x6000002 frames at different torque levels ────────
    w()
    w("=" * 72)
    w("SECTION 1: 0x6000002 frame samples at different torque levels")
    w("=" * 72)

    frames_6M2 = pt_ids.get(0x6000002, [])
    if not frames_6M2:
        w("  0x6000002 NOT FOUND on PT bus")
    else:
        w(f"  {len(frames_6M2)} frames of 0x6000002")
        # Sort frames into torque buckets
        buckets = {
            "large_neg  (T<-500)":  [],
            "mid_neg    (-500<T<-100)": [],
            "near_zero  (-100<T<100)":  [],
            "mid_pos    (100<T<500)":   [],
            "large_pos  (T>500)":       [],
        }
        for t, dat in frames_6M2:
            trq = nearest(trq_ts, t, MAX_DT)
            if trq is None:
                continue
            if trq < -500:
                buckets["large_neg  (T<-500)"].append((t, trq, dat))
            elif trq < -100:
                buckets["mid_neg    (-500<T<-100)"].append((t, trq, dat))
            elif trq < 100:
                buckets["near_zero  (-100<T<100)"].append((t, trq, dat))
            elif trq < 500:
                buckets["mid_pos    (100<T<500)"].append((t, trq, dat))
            else:
                buckets["large_pos  (T>500)"].append((t, trq, dat))

        w(f"  {'Bucket':<32} {'Frames':>8}")
        for label, frames in buckets.items():
            w(f"  {label:<32} {len(frames):>8}")

        w()
        w(f"  {'Bucket':<32}  T_ref   B0   B1   B2   B3   B4   B5   B6   B7")
        w("  " + "-" * 80)
        for label, frames in buckets.items():
            # Print up to 5 samples per bucket
            for t, trq, dat in frames[:5]:
                byts = "  ".join(f"{b:3d}" for b in dat[:8])
                w(f"  {label:<32}  {trq:+5d}   {byts}")

    # ── SECTION 2: Phase-current-RMS scan (|torque| reference) ──────────────
    w()
    w("=" * 72)
    w("SECTION 2: Phase-current-RMS scan — r vs |torque| for all PT bytes")
    w("=" * 72)
    w(f"  {'Msg':>8}  {'Signal':<28}  {'r vs |T|':>10}  {'r vs T':>10}  {'r vs RPM':>10}")
    w("  " + "-" * 72)

    results = []
    for mid, frame_list in pt_ids.items():
        if len(frame_list) < 30:
            continue
        max_dlc = max(len(d) for _, d in frame_list)
        for i in range(min(max_dlc, 8)):
            ts_list = [(t, d[i]) for t, d in frame_list if len(d) > i]
            sig = interp_nearest(ts_list, t_grid)
            if sig is None:
                continue
            r_abst  = pearson(ABS_T_ref, sig)
            r_t     = pearson(T_ref,     sig)
            r_rpm   = pearson(RPM_ref,   sig)
            if r_abst is None:
                continue
            results.append((abs(r_abst), r_abst, r_t, r_rpm, mid, f'B{i}'))

    results.sort(reverse=True)
    shown = 0
    seen  = set()
    for abs_r, r_abst, r_t, r_rpm, mid, sig_label in results:
        key = (mid, sig_label)
        if key in seen:
            continue
        seen.add(key)
        r_t_s   = f"{r_t:+.4f}"   if r_t   is not None else "     N/A"
        r_rpm_s = f"{r_rpm:+.4f}" if r_rpm is not None else "     N/A"
        w(f"  0x{mid:08X}  {sig_label:<28}  {r_abst:+.4f}      {r_t_s}    {r_rpm_s}")
        shown += 1
        if shown >= TOP_N:
            break

    # ── SECTION 3: Explicit 0x472 byte analysis ──────────────────────────────
    w()
    w("=" * 72)
    w("SECTION 3: Explicit 0x472 byte-by-byte vs signed T and |T|")
    w("=" * 72)
    frames_472 = pt_ids.get(0x472, [])
    if not frames_472:
        w("  0x472 NOT FOUND on PT bus in this log")
    else:
        w(f"  {len(frames_472)} frames of 0x472")
        max_dlc = max(len(d) for _, d in frames_472)
        w(f"  Max DLC: {max_dlc}")
        w()
        w(f"  {'Signal':<28}  {'r vs |T|':>10}  {'r vs T':>10}  {'r vs RPM':>10}")
        w("  " + "-" * 60)
        for i in range(min(max_dlc, 8)):
            ts_list = [(t, d[i]) for t, d in frames_472 if len(d) > i]
            sig = interp_nearest(ts_list, t_grid)
            if sig is None:
                w(f"  B{i:<27}  interp failed (gap/rate)")
                continue
            r_abst = pearson(ABS_T_ref, sig)
            r_t    = pearson(T_ref,     sig)
            r_rpm  = pearson(RPM_ref,   sig)
            r_abst_s = f"{r_abst:+.4f}" if r_abst is not None else "     N/A"
            r_t_s    = f"{r_t:+.4f}"    if r_t    is not None else "     N/A"
            r_rpm_s  = f"{r_rpm:+.4f}"  if r_rpm  is not None else "     N/A"
            w(f"  B{i:<27}  {r_abst_s}      {r_t_s}    {r_rpm_s}")

        # Also LE/BE words centered at 32768
        w()
        w("  2-byte words (LE/BE, centered at 32768):")
        for i in range(min(max_dlc, 8) - 1):
            j = i + 1
            for endian, lbl in [('LE', f'B{i}-B{j} LE-32768'), ('BE', f'B{i}-B{j} BE-32768')]:
                if endian == 'LE':
                    ts_raw = [(t, (d[j]<<8)|d[i]) for t, d in frames_472 if len(d) > j]
                else:
                    ts_raw = [(t, (d[i]<<8)|d[j]) for t, d in frames_472 if len(d) > j]
                sig_raw = interp_nearest(ts_raw, t_grid)
                if sig_raw is None:
                    w(f"  {lbl:<28}  interp failed")
                    continue
                sig_cen = [v-32768 for v in sig_raw]
                for slbl, sig in [(lbl, sig_raw), (lbl+' cen', sig_cen)]:
                    r_abst = pearson(ABS_T_ref, sig)
                    r_t    = pearson(T_ref,     sig)
                    r_rpm  = pearson(RPM_ref,   sig)
                    if r_abst is None:
                        continue
                    r_abst_s = f"{r_abst:+.4f}"
                    r_t_s    = f"{r_t:+.4f}" if r_t else "     N/A"
                    r_rpm_s  = f"{r_rpm:+.4f}" if r_rpm else "     N/A"
                    w(f"  {slbl:<28}  {r_abst_s}      {r_t_s}    {r_rpm_s}")

    # ── SECTION 4: 0x6000002 signed T correlation detail ────────────────────
    w()
    w("=" * 72)
    w("SECTION 4: 0x6000002 per-byte vs signed T, |T|, RPM")
    w("=" * 72)
    if frames_6M2:
        max_dlc = max(len(d) for _, d in frames_6M2)
        w(f"  {len(frames_6M2)} frames, max DLC={max_dlc}")
        w()
        w(f"  {'Signal':<28}  {'r vs |T|':>10}  {'r vs T':>10}  {'r vs RPM':>10}  {'min':>6}  {'max':>6}  {'n_uniq':>6}")
        w("  " + "-" * 80)
        for i in range(min(max_dlc, 8)):
            ts_list = [(t, d[i]) for t, d in frames_6M2 if len(d) > i]
            sig = interp_nearest(ts_list, t_grid)
            if sig is None:
                w(f"  B{i:<27}  interp failed")
                continue
            r_abst = pearson(ABS_T_ref, sig)
            r_t    = pearson(T_ref,     sig)
            r_rpm  = pearson(RPM_ref,   sig)
            n_uniq = len(set(sig))
            r_abst_s = f"{r_abst:+.4f}" if r_abst is not None else "     N/A"
            r_t_s    = f"{r_t:+.4f}"    if r_t    is not None else "     N/A"
            r_rpm_s  = f"{r_rpm:+.4f}"  if r_rpm  is not None else "     N/A"
            w(f"  B{i:<27}  {r_abst_s}      {r_t_s}    {r_rpm_s}  {min(sig):>6}  {max(sig):>6}  {n_uniq:>6}")

        # LE/BE words centered
        w()
        w("  2-byte words centered at 32768:")
        w(f"  {'Signal':<30}  {'r vs |T|':>10}  {'r vs T':>10}  {'r vs RPM':>10}")
        w("  " + "-" * 70)
        for i in range(min(max_dlc, 8) - 1):
            j = i + 1
            for endian, lbl in [('LE', f'B{i}-B{j} LE-32768'), ('BE', f'B{i}-B{j} BE-32768')]:
                if endian == 'LE':
                    ts_raw = [(t, (d[j]<<8)|d[i]) for t, d in frames_6M2 if len(d) > j]
                else:
                    ts_raw = [(t, (d[i]<<8)|d[j]) for t, d in frames_6M2 if len(d) > j]
                sig_raw = interp_nearest(ts_raw, t_grid)
                if sig_raw is None:
                    continue
                sig_cen = [v-32768 for v in sig_raw]
                r_abst = pearson(ABS_T_ref, sig_cen)
                r_t    = pearson(T_ref,     sig_cen)
                r_rpm  = pearson(RPM_ref,   sig_cen)
                if r_abst is None:
                    continue
                r_abst_s = f"{r_abst:+.4f}"
                r_t_s    = f"{r_t:+.4f}" if r_t else "     N/A"
                r_rpm_s  = f"{r_rpm:+.4f}" if r_rpm else "     N/A"
                w(f"  {lbl:<30}  {r_abst_s}      {r_t_s}    {r_rpm_s}")

    # ── write output ─────────────────────────────────────────────────────────
    with open(OUTPUT_FILE, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(f"\nOutput written to: {OUTPUT_FILE.name}")


if __name__ == "__main__":
    main()
