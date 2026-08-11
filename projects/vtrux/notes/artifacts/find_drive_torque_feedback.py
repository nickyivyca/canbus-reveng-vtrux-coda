"""
find_drive_torque_feedback.py

Search for the traction motor torque FEEDBACK signal by correlating all PT
bus bytes/words directly against the traction motor torque COMMAND (0x052
B2-B3 LE-32768), filtering to loaded frames only.

This mirrors the generator search that found 0x471 B0-B1 by correlating
against 0x051 (gen torque command) with a gen-loaded filter.

Traction motor command: 0x052 B2-B3 LE-32768 (100 Hz)
  - At rest: B2=0xFF, B3=0x7F → LE=32767, centered=-1 (neutral)
  - Filter: |cmd| > CMD_THRESHOLD (exclude coasting/idle frames)

Log: vtruxcurrentlimitingtest.log (widest drivetrain dynamic range)
Also runs on vtruxevapdrivelog4part2.log for cross-check.

Output: find_drive_torque_feedback_output.txt

Machine: the bench PC  Python: py -3.12
"""

import re
import math
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]
LOGS_DIR     = PROJECT_ROOT / "projects" / "vtrux" / "logs"

LOG_CLIMIT = LOGS_DIR / "vtruxcurrentlimitingtest.log"
LOG_EVAP   = LOGS_DIR / "vtruxevapdrivelog4part2.log"
OUTPUT_FILE = SCRIPT_DIR / "find_drive_torque_feedback_output.txt"

# Load filter: only use frames where |torque command| > this threshold
CMD_THRESHOLD = 50    # counts (very low — just exclude genuine idle/coast)
MAX_DT        = 0.05  # s — tight sync window (both 0x052 and most signals are >=20 Hz)
TOP_N         = 40

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


def run_scan(log_path, label, out):
    def w(s=""):
        print(s)
        out.append(s)

    w()
    w("=" * 80)
    w(f"DRIVETRAIN TORQUE FEEDBACK SEARCH — {label}")
    w(f"Log: {log_path.name}")
    w("=" * 80)

    if not log_path.exists():
        w(f"  ERROR: log not found: {log_path}")
        return

    w("  Parsing log...")
    buses = parse_log(log_path)
    pt_bus = find_pt_bus(buses)
    if pt_bus is None:
        w("  ERROR: PT bus not found")
        return
    pt_ids = buses[pt_bus]
    w(f"  PT bus: {pt_bus}, {len(pt_ids)} unique IDs")

    # ── Build 0x052 torque command reference ─────────────────────────────────
    cmd_052 = []   # (t, cmd_centered)  ← torque command
    for t, dat in pt_ids.get(0x052, []):
        raw = u16_le(dat, 2)   # B2-B3 LE
        if raw is not None:
            cmd_052.append((t, raw - 32768))

    if not cmd_052:
        w("  ERROR: 0x052 not found on PT bus — cannot build command reference")
        return

    w(f"  0x052 frames: {len(cmd_052)}")
    w(f"  0x052 cmd range: {min(v for _,v in cmd_052)} to {max(v for _,v in cmd_052)}")

    # ── Build t_grid anchored on 0x052 frames where |cmd| > threshold ────────
    t_grid = [t for t, v in cmd_052 if abs(v) > CMD_THRESHOLD]
    cmd_grid = [v for t, v in cmd_052 if abs(v) > CMD_THRESHOLD]

    w(f"  Loaded frames (|cmd|>{CMD_THRESHOLD}): {len(t_grid)}")
    if len(t_grid) < 50:
        w("  WARNING: too few loaded frames — check threshold or log content")
        return

    w(f"  Cmd range (loaded): {min(cmd_grid)} to {max(cmd_grid)}")

    # ── Correlation scan ──────────────────────────────────────────────────────
    w()
    w(f"  {'Msg':>10}  {'Signal':<32}  {'|r| vs cmd':>10}  {'r vs cmd':>10}")
    w("  " + "-" * 70)

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
            r = pearson(cmd_grid, sig)
            r_c = pearson(cmd_grid, [v-128 for v in sig])
            best = max((r, r_c), key=lambda x: abs(x) if x is not None else 0)
            if best is None:
                continue
            results.append((abs(best), best, mid, f'B{i}'))

        # 2-byte LE/BE centered at 32768
        for i in range(min(max_dlc, 8) - 1):
            j = i + 1
            for endian, lbl in [('LE', f'B{i}-B{j} LE-32768'), ('BE', f'B{i}-B{j} BE-32768')]:
                if endian == 'LE':
                    ts_raw = [(t, (d[j]<<8)|d[i]) for t, d in frame_list if len(d) > j]
                else:
                    ts_raw = [(t, (d[i]<<8)|d[j]) for t, d in frame_list if len(d) > j]
                sig_raw = interp_nearest(ts_raw, t_grid, MAX_DT)
                if sig_raw is None:
                    continue
                sig_cen = [v-32768 for v in sig_raw]
                r = pearson(cmd_grid, sig_cen)
                if r is None:
                    continue
                results.append((abs(r), r, mid, lbl))

    results.sort(reverse=True)

    seen  = set()
    shown = 0
    for abs_r, r, mid, sig_label in results:
        root = sig_label.split('-32768')[0].split(' LE')[0].split(' BE')[0]
        key  = (mid, root)
        if key in seen:
            continue
        seen.add(key)
        w(f"  0x{mid:08X}  {sig_label:<32}  {abs_r:10.4f}  {r:+10.4f}")
        shown += 1
        if shown >= TOP_N:
            break

    # ── Explicit check: 0x052 self-correlation and 0x5A2 B4-B5 ──────────────
    w()
    w("  Explicit checks:")
    checks = [
        (0x052, 'B2-B3 LE-32768', lambda d: (u16_le(d,2) or 32768) - 32768),
        (0x5A2, 'B4-B5 LE-32768', lambda d: (u16_le(d,4) or 32768) - 32768),
        (0x472, 'B0-B1 LE-32768', lambda d: (u16_le(d,0) or 32768) - 32768),
        (0x472, 'B2-B3 LE-32768', lambda d: (u16_le(d,2) or 32768) - 32768),
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
        r = pearson(cmd_grid, sig)
        r_s = f"{r:+.4f}" if r is not None else "N/A"
        mn, mx, nu = min(sig), max(sig), len(set(sig))
        w(f"  0x{mid:08X} {lbl}: r={r_s}  range [{mn}, {mx}]  {nu} unique")


def main():
    out = []
    out.append("find_drive_torque_feedback.py — traction motor torque feedback search")
    out.append(f"Reference: 0x052 B2-B3 LE-32768 (traction motor torque command)")
    out.append(f"Filter: |cmd| > {CMD_THRESHOLD} counts")

    run_scan(LOG_CLIMIT, "vtruxcurrentlimitingtest (wide range)", out)
    run_scan(LOG_EVAP,   "vtruxevapdrivelog4part2 (evap/hybrid)", out)

    with open(OUTPUT_FILE, 'w') as f:
        f.write('\n'.join(out) + '\n')
    print(f"\nOutput written to: {OUTPUT_FILE.name}")


if __name__ == "__main__":
    main()
