"""
find_regen_cmd.py

Search for a signal that correlates with the REGEN half of traction motor
torque only (not the brake pedal, not a full bidirectional signal).

Strategy:
  - Reference: 0x5A2 B4-B5 LE-32768 (actual motor torque, bidirectional)
  - Filter:    only frames where actual_torque < -REGEN_THRESH (regen only)
  - Correlation target: regen magnitude = -(actual_torque), so a signal that
    gets MORE POSITIVE as regen deepens has r > 0, one that goes NEGATIVE
    (tracking the sign) has r < 0.
  - Excludes: 0x592 B4-B5 (brake pedal -- the obvious driver input)

Output: find_regen_cmd_output.txt

Machine: the bench PC  Python: py -3.12
"""

import re
import math
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]
LOGS_DIR     = PROJECT_ROOT / "projects" / "vtrux" / "logs"

LOG_CLIMIT  = LOGS_DIR / "vtruxcurrentlimitingtest.log"
OUTPUT_FILE = SCRIPT_DIR / "find_regen_cmd_output.txt"

REGEN_THRESH = 100   # counts (centered) -- only use frames where torque < -100
MAX_DT       = 0.12  # s -- wide enough for 10 Hz signals
TOP_N        = 50

EXCLUDE = {(0x592, 4)}   # (mid, byte_offset) pairs to suppress from top list

# ── BUSMASTER parser ──────────────────────────────────────────────────────────
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
    if not ts_vals:
        return None
    lo, hi = 0, len(ts_vals)-1
    while lo < hi:
        mid_i = (lo+hi)//2
        if ts_vals[mid_i][0] < t:
            lo = mid_i+1
        else:
            hi = mid_i
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

def interp_nearest(ts_list, t_grid, max_dt):
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
    out = []
    def w(s=""):
        print(s)
        out.append(s)

    w("find_regen_cmd.py -- regen-only torque signal search")
    w("Reference: 0x5A2 B4-B5 (actual motor torque), filtered to regen frames only")
    w("Correlation target: regen_magnitude = -(actual_torque) > 0")
    w("Excludes: 0x592 B4-B5 (brake pedal)")
    w(f"REGEN_THRESH={REGEN_THRESH}  MAX_DT={MAX_DT}s")
    w()
    w("=" * 80)
    w(f"Log: {LOG_CLIMIT.name}")
    w("=" * 80)

    if not LOG_CLIMIT.exists():
        w(f"ERROR: log not found: {LOG_CLIMIT}")
        return

    w("  Parsing log...")
    buses = parse_log(LOG_CLIMIT)
    pt_bus = find_pt_bus(buses)
    if pt_bus is None:
        w("  ERROR: PT bus not found")
        return
    pt_ids = buses[pt_bus]
    w(f"  PT bus: {pt_bus}, {len(pt_ids)} unique IDs")

    # ── Build 0x5A2 actual torque reference ───────────────────────────────────
    fl_5a2 = pt_ids.get(0x5A2, [])
    if not fl_5a2:
        w("  ERROR: 0x5A2 not found")
        return
    w(f"  0x5A2 frames: {len(fl_5a2)}")

    trq_ts = [(t, u16_le(d, 4) - 32768) for t, d in fl_5a2 if u16_le(d, 4) is not None]

    # Filter to regen-only frames
    t_grid   = [t   for t, v in trq_ts if v < -REGEN_THRESH]
    trq_grid = [v   for t, v in trq_ts if v < -REGEN_THRESH]
    # Regen magnitude (positive, increasing as regen deepens)
    mag_grid = [-v  for v in trq_grid]

    w(f"  Regen frames (torque < -{REGEN_THRESH}): {len(t_grid)}")
    w(f"  Actual torque range (regen): {min(trq_grid)} to {max(trq_grid)}")
    w(f"  Regen magnitude range: {min(mag_grid)} to {max(mag_grid)}")
    if len(t_grid) < 20:
        w("  WARNING: too few regen frames")
        return

    # ── Correlation scan (vs regen magnitude) ─────────────────────────────────
    w()
    w(f"  {'Msg':>10}  {'Signal':<34}  {'|r|':>8}  {'r vs mag':>10}  {'sig_min':>8}  {'sig_max':>8}  note")
    w("  " + "-" * 95)

    results = []

    for mid, frame_list in pt_ids.items():
        if len(frame_list) < 20:
            continue
        max_dlc = max(len(d) for _, d in frame_list)

        # Per-byte: raw and centered at 128
        for i in range(min(max_dlc, 8)):
            skip = (mid, i) in EXCLUDE
            ts_list = [(t, d[i]) for t, d in frame_list if len(d) > i]
            sig = interp_nearest(ts_list, t_grid, MAX_DT)
            if sig is None:
                continue
            sig_c = [v - 128 for v in sig]
            for vals, lbl in [(sig, f'B{i}'), (sig_c, f'B{i} -128')]:
                r = pearson(mag_grid, vals)
                if r is None:
                    continue
                results.append((abs(r), r, mid, lbl, min(vals), max(vals), skip))

        # 2-byte LE/BE centered at 32768
        for i in range(min(max_dlc, 8) - 1):
            j = i + 1
            skip = (mid, i) in EXCLUDE or (mid, j) in EXCLUDE
            for endian, lbl in [('LE', f'B{i}-B{j} LE-32768'),
                                 ('BE', f'B{i}-B{j} BE-32768')]:
                if endian == 'LE':
                    ts_raw = [(t, (d[j]<<8)|d[i]) for t, d in frame_list if len(d) > j]
                else:
                    ts_raw = [(t, (d[i]<<8)|d[j]) for t, d in frame_list if len(d) > j]
                sig_raw = interp_nearest(ts_raw, t_grid, MAX_DT)
                if sig_raw is None:
                    continue
                sig_cen = [v - 32768 for v in sig_raw]
                r = pearson(mag_grid, sig_cen)
                if r is None:
                    continue
                results.append((abs(r), r, mid, lbl, min(sig_cen), max(sig_cen), skip))

    results.sort(reverse=True)

    seen  = set()
    shown = 0
    for abs_r, r, mid, sig_label, mn, mx, skip in results:
        root = (sig_label.split('-32768')[0]
                         .split(' LE')[0]
                         .split(' BE')[0]
                         .split(' -128')[0])
        key = (mid, root)
        if key in seen:
            continue
        seen.add(key)
        note = '[BRAKE PEDAL - excluded]' if skip else ''
        moves = '+' if mx > 50 else ('-' if mn < -50 else '~0')
        w(f"  0x{mid:08X}  {sig_label:<34}  {abs_r:8.4f}  {r:+10.4f}  {mn:>8}  {mx:>8}  {moves} {note}")
        shown += 1
        if shown >= TOP_N:
            break

    w()
    w("  (r vs mag: positive = signal goes up as regen deepens, negative = signal goes down)")
    w("  (+ = signal goes positive, - = signal goes negative, ~0 = near-zero range during regen)")

    # ── Sample table for top candidates ───────────────────────────────────────
    w()
    w("  Sample during regen (torque < -200): actual_trq | brake_B45 | 052_cmd | candidates")

    def ts_cen(mid, byte_off):
        fl = pt_ids.get(mid, [])
        result = []
        for t, d in fl:
            raw = u16_le(d, byte_off)
            if raw is not None:
                result.append((t, raw - 32768))
        return result

    # Pick top 3 non-brake, non-self candidates from results
    candidates = []
    seen2 = set()
    for abs_r, r, mid, sig_label, mn, mx, skip in results:
        if skip or mid == 0x5A2:
            continue
        root = (sig_label.split('-32768')[0]
                         .split(' LE')[0]
                         .split(' BE')[0]
                         .split(' -128')[0])
        key = (mid, root)
        if key in seen2:
            continue
        seen2.add(key)
        # Determine byte offset from label
        try:
            byte_i = int(root.replace('B','').split('-')[0])
        except Exception:
            continue
        # Only 2-byte LE for the sample table
        if 'LE-32768' in sig_label or 'LE' in sig_label:
            candidates.append((mid, byte_i, sig_label, abs_r, r))
        if len(candidates) >= 3:
            break

    ts_052   = ts_cen(0x052, 2)
    ts_brake = ts_cen(0x592, 4)
    cand_ts  = [ts_cen(mid, bi) for mid, bi, lbl, ar, r in candidates]

    hdr = "  actual  brake_B45  052_cmd"
    for mid, bi, lbl, ar, r in candidates:
        hdr += f"  0x{mid:X}_{lbl[:10]}"
    w(hdr)

    shown_rows = 0
    for t, trq in zip(t_grid, trq_grid):
        if trq >= -200:
            continue
        brake = nearest(ts_brake, t, MAX_DT)
        cmd   = nearest(ts_052,   t, MAX_DT)
        row = f"  {trq:>6}  {str(brake):>9}  {str(cmd):>7}"
        for cts in cand_ts:
            v = nearest(cts, t, MAX_DT)
            row += f"  {str(v):>14}"
        w(row)
        shown_rows += 1
        if shown_rows >= 30:
            w("  ... (first 30 regen frames)")
            break

    with open(OUTPUT_FILE, 'w', encoding='utf-8', errors='replace') as f:
        f.write('\n'.join(out) + '\n')
    print(f"\nOutput written to: {OUTPUT_FILE.name}")


if __name__ == "__main__":
    main()
