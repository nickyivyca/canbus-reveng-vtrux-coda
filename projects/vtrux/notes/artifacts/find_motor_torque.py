"""
Find the powertrain bus (bus 3) signal that represents Remy motor torque.

Proxy: throttle pedal (0x592 B2-B3 LE, bus 3) signed by direction from
0x1F5 lever position (bus 2).  Positive = Drive + throttle, Negative = Reverse + throttle.

Correlate against every byte/word on bus 3.
"""

import re
import numpy as np
from collections import defaultdict

LOG_PATH = r"projects/vtrux/logs/movingaroundindriveway.log"

BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)+)'
)


def parse_ts(ts_str):
    h, m, s, t = ts_str.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001


# ---- Pass 1: collect frames ----
frames_throttle = []        # bus 3 0x592: (t, raw_throttle)
frames_1f5      = []        # bus 2 0x1F5: (t, lever_pos)
frames_pt       = defaultdict(list)  # bus 3: msg_id -> [(t, [bytes])]
t0 = None

with open(LOG_PATH, 'r', errors='replace') as f:
    for line in f:
        m = BUSMASTER_RE.match(line.strip())
        if not m:
            continue
        ts_str, bus_str, id_str, dlc_str, data_str = m.groups()
        bus    = int(bus_str)
        msg_id = int(id_str, 16)
        ts     = parse_ts(ts_str)
        if t0 is None:
            t0 = ts
        rel  = ts - t0
        data = [int(b, 16) for b in data_str.strip().split()]

        if bus == 2:
            if msg_id == 0x1F5 and len(data) >= 4:
                frames_1f5.append((rel, data[3] & 0xF))
        elif bus == 3:
            if msg_id == 0x592 and len(data) >= 4:
                throttle_raw = (data[3] << 8) | data[2]   # LE
                frames_throttle.append((rel, throttle_raw))
            frames_pt[msg_id].append((rel, data))


# ---- Build signed torque proxy ----
def get_lever_at(t):
    lever = 1
    for ft, lp in frames_1f5:
        if ft <= t:
            lever = lp
        else:
            break
    return lever

# Throttle range
thr_vals = [v for _, v in frames_throttle]
thr_min  = min(thr_vals)
thr_max  = max(thr_vals)
thr_span = thr_max - thr_min
print(f"Throttle (0x592 B2-3 LE): {len(frames_throttle)} frames")
print(f"  Raw range: {thr_min} to {thr_max}  (span={thr_span})")
print()

torque_proxy_ts = []
for t, raw in frames_throttle:
    normalized = (raw - thr_min) / thr_span if thr_span > 0 else 0
    lever = get_lever_at(t)
    sign  = -1 if lever == 2 else 1
    torque_proxy_ts.append((t, sign * normalized))

proxy_vals = [v for _, v in torque_proxy_ts]
print(f"Signed torque proxy range: {min(proxy_vals):.3f} to {max(proxy_vals):.3f}")
print()

# ---- Interpolation grid aligned to throttle samples ----
t_grid   = np.array([t for t, _ in torque_proxy_ts])
proxy_np = np.array([v for _, v in torque_proxy_ts])
proxy_abs = np.abs(proxy_np)

def interp_signal(ts_list, t_grid):
    if len(ts_list) < 5:
        return None
    times = np.array([t for t, v in ts_list])
    vals  = np.array([v for t, v in ts_list], dtype=float)
    if times[-1] < t_grid[0] or times[0] > t_grid[-1]:
        return None
    return np.interp(t_grid, times, vals)

def pearson(a, b):
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


# ---- Scan every byte and word on bus 3 ----
results = []

for mid, frame_list in frames_pt.items():
    if len(frame_list) < 20:
        continue
    max_dlc = max(len(d) for _, d in frame_list)

    # Per-byte
    for i in range(min(max_dlc, 8)):
        ts_list = [(t, d[i]) for t, d in frame_list if len(d) > i]
        sig = interp_signal(ts_list, t_grid)
        if sig is None:
            continue
        r_s = pearson(proxy_np, sig)
        r_a = pearson(proxy_abs, sig)
        results.append((max(abs(r_s), abs(r_a)), r_s, r_a, mid, f'B{i}'))

        sig_c = sig - 128
        r_s2 = pearson(proxy_np, sig_c)
        r_a2 = pearson(proxy_abs, sig_c)
        results.append((max(abs(r_s2), abs(r_a2)), r_s2, r_a2, mid, f'B{i}-128'))

    # 2-byte combinations
    for i in range(min(max_dlc, 8) - 1):
        j = i + 1
        ts_be = [(t, (d[i] << 8) | d[j]) for t, d in frame_list if len(d) > j]
        ts_le = [(t, (d[j] << 8) | d[i]) for t, d in frame_list if len(d) > j]

        for label, ts_list in [(f'B{i}{j}(BE)', ts_be), (f'B{i}{j}(LE)', ts_le)]:
            sig_raw = interp_signal(ts_list, t_grid)
            if sig_raw is None:
                continue
            sig_cen = sig_raw - 32768

            for slabel, sig in [(label, sig_raw), (f'{label}-32768', sig_cen)]:
                r_s = pearson(proxy_np, sig)
                r_a = pearson(proxy_abs, sig)
                results.append((max(abs(r_s), abs(r_a)), r_s, r_a, mid, slabel))

results.sort(reverse=True)

print("=" * 80)
print("TOP 40 CORRELATIONS WITH SIGNED THROTTLE PROXY")
print("  r_signed: correlation with signed proxy (+Drive / -Reverse)")
print("  r_abs:    correlation with |proxy| (unsigned magnitude)")
print("=" * 80)
print(f"  {'Msg':>8}  {'Signal':<28}  {'best|r|':>8}  {'r_signed':>9}  {'r_abs':>9}")
print("-" * 72)

seen  = set()
shown = 0
for best_r, r_s, r_a, mid, label in results:
    key = (mid, label.split('-')[0].split('(')[0])
    if key in seen:
        continue
    seen.add(key)
    print(f"  0x{mid:03X}  {label:<28}  {best_r:8.4f}  {r_s:9.4f}  {r_a:9.4f}")
    shown += 1
    if shown >= 40:
        break
