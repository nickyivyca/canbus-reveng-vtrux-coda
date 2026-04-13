"""
find_drive_cmd_vs_5a2.py

Search for the traction motor torque COMMAND by correlating all PT bus
bytes/words against 0x5A2 B4-B5 LE-32768 (actual bidirectional motor torque).

Reference: 0x5A2 B4-B5 LE-32768
  - Bidirectional: positive = drive, negative = regen
  - Filter: |actual_torque| > TORQUE_THRESH (exclude near-zero idle frames)

Log: vtruxcurrentlimitingtest.log (has both drive and confirmed regen events)

Output: find_drive_cmd_vs_5a2_output.txt

Machine: L-EEHTRBPN2  Python: py -3.12
"""

import re
import math
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]
LOGS_DIR     = PROJECT_ROOT / "projects" / "vtrux" / "logs"

LOG_CLIMIT  = LOGS_DIR / "vtruxcurrentlimitingtest.log"
OUTPUT_FILE = SCRIPT_DIR / "find_drive_cmd_vs_5a2_output.txt"

TORQUE_THRESH = 100   # counts (centered), exclude near-zero frames
MAX_DT        = 0.12  # s -- wide enough for 10 Hz signals (100 ms period)
TOP_N         = 50

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
    if n < 30:
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

    w("find_drive_cmd_vs_5a2.py -- traction torque command search vs actual torque")
    w("Reference: 0x5A2 B4-B5 LE-32768 (actual bidirectional motor torque)")
    w(f"Filter: |actual_torque| > {TORQUE_THRESH} counts  MAX_DT={MAX_DT}s")
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

    # ── Build 0x5A2 actual torque reference -- NO 'or 32768' bug ─────────────
    fl_5a2 = pt_ids.get(0x5A2, [])
    if not fl_5a2:
        w("  ERROR: 0x5A2 not found on PT bus")
        return
    w(f"  0x5A2 frames: {len(fl_5a2)}")

    trq_ts = []  # (t, centered_value) -- raw u16 LE, no OR trick
    for t, d in fl_5a2:
        raw = u16_le(d, 4)
        if raw is None:
            continue
        trq_ts.append((t, raw - 32768))

    raw_vals = [v for _, v in trq_ts]
    w(f"  0x5A2 B4-B5 centered range: {min(raw_vals)} to {max(raw_vals)}")

    # Filter to active torque frames
    t_grid   = [t for t, v in trq_ts if abs(v) > TORQUE_THRESH]
    trq_grid = [v for t, v in trq_ts if abs(v) > TORQUE_THRESH]

    drive_n = sum(1 for v in trq_grid if v > 0)
    regen_n = sum(1 for v in trq_grid if v < 0)
    w(f"  Active frames: {len(t_grid)}  (drive={drive_n}, regen={regen_n})")
    w(f"  Active range: {min(trq_grid)} to {max(trq_grid)}")
    if len(t_grid) < 50:
        w("  WARNING: too few active frames")
        return

    # ── Correlation scan ──────────────────────────────────────────────────────
    w()
    w(f"  {'Msg':>10}  {'Signal':<34}  {'|r|':>8}  {'r':>9}  {'min':>8}  {'max':>8}")
    w("  " + "-" * 85)

    results = []

    for mid, frame_list in pt_ids.items():
        if len(frame_list) < 50:
            continue
        max_dlc = max(len(d) for _, d in frame_list)

        # Per-byte: raw and centered at 128
        for i in range(min(max_dlc, 8)):
            ts_list = [(t, d[i]) for t, d in frame_list if len(d) > i]
            sig = interp_nearest(ts_list, t_grid, MAX_DT)
            if sig is None:
                continue
            sig_c = [v - 128 for v in sig]
            for vals, lbl in [(sig, f'B{i}'), (sig_c, f'B{i} -128')]:
                r = pearson(trq_grid, vals)
                if r is None:
                    continue
                results.append((abs(r), r, mid, lbl, min(vals), max(vals)))

        # 2-byte LE/BE centered at 32768
        for i in range(min(max_dlc, 8) - 1):
            j = i + 1
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
                r = pearson(trq_grid, sig_cen)
                if r is None:
                    continue
                results.append((abs(r), r, mid, lbl, min(sig_cen), max(sig_cen)))

    results.sort(reverse=True)

    seen  = set()
    shown = 0
    for abs_r, r, mid, sig_label, mn, mx in results:
        root = (sig_label.split('-32768')[0]
                         .split(' LE')[0]
                         .split(' BE')[0]
                         .split(' -128')[0])
        key = (mid, root)
        if key in seen:
            continue
        seen.add(key)
        goes_neg = '*' if mn < -50 else ' '
        w(f"  0x{mid:08X}  {sig_label:<34}  {abs_r:8.4f}  {r:+9.4f}  {mn:>8}  {mx:>8} {goes_neg}")
        shown += 1
        if shown >= TOP_N:
            break

    w()
    w("  (* = goes negative, min < -50)")

    # ── Sample regen frames for key candidates ────────────────────────────────
    w()
    w("  Regen sample (actual_trq < -200):")
    w("  " + "-" * 90)

    def ts_cen(mid, byte_off):
        fl = pt_ids.get(mid, [])
        result = []
        for t, d in fl:
            raw = u16_le(d, byte_off)
            if raw is not None:
                result.append((t, raw - 32768))
        return result

    ts_052   = ts_cen(0x052, 2)
    ts_051   = ts_cen(0x051, 3)
    ts_597_34 = ts_cen(0x597, 3)
    ts_597_56 = ts_cen(0x597, 5)
    ts_5a2_ref = trq_ts  # already centered

    header = ("  actual_trq  |  052_cmd  051_B34  597_B34  597_B56")
    w(header)

    regen_shown = 0
    for t, trq in zip(t_grid, trq_grid):
        if trq >= -200:
            continue
        v052     = nearest(ts_052,    t, MAX_DT)
        v051     = nearest(ts_051,    t, MAX_DT)
        v597_34  = nearest(ts_597_34, t, MAX_DT)
        v597_56  = nearest(ts_597_56, t, MAX_DT)
        w(f"  {trq:>10}  |  {str(v052):>8}  {str(v051):>7}  {str(v597_34):>7}  {str(v597_56):>7}")
        regen_shown += 1
        if regen_shown >= 30:
            w("  ... (first 30 regen frames shown)")
            break

    with open(OUTPUT_FILE, 'w', encoding='utf-8', errors='replace') as f:
        f.write('\n'.join(out) + '\n')
    print(f"\nOutput written to: {OUTPUT_FILE.name}")


if __name__ == "__main__":
    main()
