"""
find_drive_cmd_bidirectional.py

Search for a true BIDIRECTIONAL traction motor torque command by building a
signed driver-demand reference from the throttle/brake pedal message (0x592)
and correlating all PT bus bytes/words against it.

Driver demand reference:
  - 0x592 B2-B3 LE  -> throttle_raw  (positive demand)
  - 0x592 B4-B5 LE  -> brake_raw     (negative demand)
  - demand = +throttle_raw  if throttle_raw > THROTTLE_THRESH
             -brake_raw     if brake_raw    > BRAKE_THRESH
             0              otherwise

This reference is signed and captures driver intent before any power/current
limiting is applied. Any VCM torque command message should track it.

Log: vtruxcurrentlimitingtest.log (has both drive and regen events)

Output: find_drive_cmd_bidirectional_output.txt

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
OUTPUT_FILE = SCRIPT_DIR / "find_drive_cmd_bidirectional_output.txt"

THROTTLE_THRESH = 50    # counts above which throttle is "active"
BRAKE_THRESH    = 50    # counts above which brake is "active"
MAX_DT          = 0.08  # s sync window (0x592 is 20 Hz -> 50 ms period, allow jitter)
TOP_N           = 50

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
    if n < 30:
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
    out = []
    def w(s=""):
        print(s)
        out.append(s)

    w("find_drive_cmd_bidirectional.py -- signed driver demand correlation scan")
    w(f"Reference: 0x592 throttle (B2-B3 LE) / brake (B4-B5 LE) -> signed demand")
    w(f"Throttle thresh: {THROTTLE_THRESH}  Brake thresh: {BRAKE_THRESH}")
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

    # ── Build 0x592 pedal reference ───────────────────────────────────────────
    ped_592 = pt_ids.get(0x592, [])
    if not ped_592:
        w("  ERROR: 0x592 not found on PT bus")
        return
    w(f"  0x592 frames: {len(ped_592)}")

    # Characterise throttle and brake ranges
    thr_vals = []
    brk_vals = []
    for t, d in ped_592:
        thr = u16_le(d, 2)
        brk = u16_le(d, 4)
        if thr is not None:
            thr_vals.append(thr)
        if brk is not None:
            brk_vals.append(brk)
    w(f"  0x592 throttle (B2-B3 LE) range: {min(thr_vals)} to {max(thr_vals)}")
    w(f"  0x592 brake    (B4-B5 LE) range: {min(brk_vals)} to {max(brk_vals)}")

    # Build signed demand time series
    demand_ts = []  # (t, demand_value)
    for t, d in ped_592:
        thr = u16_le(d, 2)
        brk = u16_le(d, 4)
        if thr is None or brk is None:
            continue
        if thr > THROTTLE_THRESH:
            demand = thr
        elif brk > BRAKE_THRESH:
            demand = -brk
        else:
            demand = 0
        demand_ts.append((t, demand))

    # Filter to frames with |demand| > threshold (active pedal)
    t_grid    = [t for t, v in demand_ts if abs(v) > max(THROTTLE_THRESH, BRAKE_THRESH)]
    dem_grid  = [v for t, v in demand_ts if abs(v) > max(THROTTLE_THRESH, BRAKE_THRESH)]

    drive_frames = sum(1 for v in dem_grid if v > 0)
    regen_frames = sum(1 for v in dem_grid if v < 0)
    w(f"  Active demand frames: {len(t_grid)} (drive={drive_frames}, regen={regen_frames})")
    w(f"  Demand range (active): {min(dem_grid)} to {max(dem_grid)}")
    if len(t_grid) < 50:
        w("  WARNING: too few active frames")
        return

    # ── Correlation scan ──────────────────────────────────────────────────────
    w()
    w(f"  {'Msg':>10}  {'Signal':<34}  {'|r| vs dem':>10}  {'r vs dem':>10}  {'range':>20}")
    w("  " + "-" * 90)

    results = []

    for mid, frame_list in pt_ids.items():
        if len(frame_list) < 50:
            continue
        max_dlc = max(len(d) for _, d in frame_list)

        # Per-byte (raw and centered at 128)
        for i in range(min(max_dlc, 8)):
            ts_list = [(t, d[i]) for t, d in frame_list if len(d) > i]
            sig = interp_nearest(ts_list, t_grid, MAX_DT)
            if sig is None:
                continue
            r     = pearson(dem_grid, sig)
            r_c   = pearson(dem_grid, [v-128 for v in sig])
            for candidate, label_suffix in [(r, 'B%d' % i), (r_c, 'B%d -128' % i)]:
                if candidate is None:
                    continue
                sig_for_range = sig if label_suffix == 'B%d' % i else [v-128 for v in sig]
                results.append((abs(candidate), candidate, mid,
                                label_suffix, min(sig_for_range), max(sig_for_range)))

        # 2-byte LE/BE centered at 32768
        for i in range(min(max_dlc, 8) - 1):
            j = i + 1
            for endian, lbl in [('LE', 'B%d-B%d LE-32768' % (i, j)),
                                 ('BE', 'B%d-B%d BE-32768' % (i, j))]:
                if endian == 'LE':
                    ts_raw = [(t, (d[j]<<8)|d[i]) for t, d in frame_list if len(d) > j]
                else:
                    ts_raw = [(t, (d[i]<<8)|d[j]) for t, d in frame_list if len(d) > j]
                sig_raw = interp_nearest(ts_raw, t_grid, MAX_DT)
                if sig_raw is None:
                    continue
                sig_cen = [v-32768 for v in sig_raw]
                r = pearson(dem_grid, sig_cen)
                if r is None:
                    continue
                results.append((abs(r), r, mid, lbl, min(sig_cen), max(sig_cen)))

    results.sort(reverse=True)

    seen  = set()
    shown = 0
    for abs_r, r, mid, sig_label, mn, mx in results:
        # Deduplicate: strip encoding suffix to get base signal location
        root = sig_label.split('-32768')[0].split(' LE')[0].split(' BE')[0].split(' -128')[0]
        key  = (mid, root)
        if key in seen:
            continue
        seen.add(key)
        rng_str = f"[{mn}, {mx}]"
        w(f"  0x{mid:08X}  {sig_label:<34}  {abs_r:10.4f}  {r:+10.4f}  {rng_str:>20}")
        shown += 1
        if shown >= TOP_N:
            break

    # ── Explicit checks on candidates ─────────────────────────────────────────
    w()
    w("  Explicit checks (demand correlation + sample during regen):")
    checks = [
        (0x052, 'B2-B3 LE', lambda d: u16_le(d,2)),
        (0x051, 'B3-B4 LE', lambda d: u16_le(d,3)),
        (0x597, 'B3-B4 LE', lambda d: u16_le(d,3)),
        (0x597, 'B5-B6 LE', lambda d: u16_le(d,5)),
        (0x5A2, 'B4-B5 LE', lambda d: u16_le(d,4)),
    ]
    for mid, lbl, extractor in checks:
        fl = pt_ids.get(mid, [])
        if not fl:
            w(f"  0x{mid:08X} {lbl}: NOT PRESENT")
            continue
        ts_list = [(t, extractor(d)) for t, d in fl]
        ts_list = [(t, v) for t, v in ts_list if v is not None]
        sig = interp_nearest(ts_list, t_grid, MAX_DT)
        if sig is None:
            w(f"  0x{mid:08X} {lbl}: interp failed (gap/rate)")
            continue
        sig_cen = [v-32768 for v in sig]
        r = pearson(dem_grid, sig_cen)
        r_s = f"{r:+.4f}" if r is not None else "N/A"
        mn, mx = min(sig_cen), max(sig_cen)
        w(f"  0x{mid:08X} {lbl}: r={r_s}  centered range [{mn}, {mx}]")

    # ── Sample regen-period frames for top candidates ─────────────────────────
    w()
    w("  Regen sample (demand < -200): demand | 052_cmd_cen | 051_B34_cen | 597_B34_cen | 597_B56_cen | 5A2_B45_cen")
    w("  " + "-" * 90)

    # Build lookup ts_lists centered
    def build_ts_cen(mid, byte_offset):
        fl = pt_ids.get(mid, [])
        return [(t, (u16_le(d, byte_offset) or 32768) - 32768) for t, d in fl if u16_le(d, byte_offset) is not None]

    ts_052 = build_ts_cen(0x052, 2)
    ts_051 = build_ts_cen(0x051, 3)
    ts_597_34 = build_ts_cen(0x597, 3)
    ts_597_56 = build_ts_cen(0x597, 5)
    ts_5a2 = build_ts_cen(0x5A2, 4)

    regen_samples = [(t, v) for t, v in zip(t_grid, dem_grid) if v < -200]
    shown_regen = 0
    for t, demand in regen_samples:
        v052 = nearest(ts_052, t, MAX_DT)
        v051 = nearest(ts_051, t, MAX_DT)
        v597_34 = nearest(ts_597_34, t, MAX_DT)
        v597_56 = nearest(ts_597_56, t, MAX_DT)
        v5a2 = nearest(ts_5a2, t, MAX_DT)
        row = (f"  dem={demand:+6d}"
               f"  052={str(v052):>6}"
               f"  051B34={str(v051):>6}"
               f"  597B34={str(v597_34):>7}"
               f"  597B56={str(v597_56):>7}"
               f"  5A2={str(v5a2):>7}")
        w(row)
        shown_regen += 1
        if shown_regen >= 30:
            w("  ... (showing first 30 regen samples)")
            break

    with open(OUTPUT_FILE, 'w', encoding='utf-8', errors='replace') as f:
        f.write('\n'.join(out) + '\n')
    print(f"\nOutput written to: {OUTPUT_FILE.name}")


if __name__ == "__main__":
    main()
