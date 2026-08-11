"""
Find the powertrain bus (bus 3) signal that represents Remy motor RPM.

Approach:
  1. Build a proxy motor RPM timeseries from 0x3E9 vehicle speed on bus 2.
     Sign: positive in Drive/Neutral, negative in Reverse (from 0x1F5 lever pos).
     Scale: ~64.3 RPM per km/h (from measured propshaft ratio x transmission 2.68).
  2. Interpolate all bus-3 byte/word signals onto the same time grid.
  3. Compute Pearson correlation (signed and absolute) for each.
  4. Report top candidates.

Correlation is run against BOTH:
  - Signed motor RPM  (catches signals that go negative in Reverse)
  - |motor RPM|       (catches unsigned magnitude signals)
"""

import re
import numpy as np
from collections import defaultdict

LOG_PATH = r"projects/vtrux/logs/movingaroundindriveway.log"

BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)+)'
)

MOTOR_RATIO = 64.3   # estimated motor RPM per km/h (propshaft x 2.68 transmission)


def parse_ts(ts_str):
    h, m, s, t = ts_str.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001


# ---- Pass 1: collect frames ----
frames_3e9 = []             # bus 2: (t, speed_kmh)
frames_1f5 = []             # bus 2: (t, lever_pos)
frames_pt  = defaultdict(list)  # bus 3: msg_id -> [(t, [bytes])]
t0 = None

with open(LOG_PATH, 'r', errors='replace') as f:
    for line in f:
        m = BUSMASTER_RE.match(line.strip())
        if not m:
            continue
        ts_str, bus_str, id_str, dlc_str, data_str = m.groups()
        bus = int(bus_str)
        msg_id = int(id_str, 16)
        ts = parse_ts(ts_str)
        if t0 is None:
            t0 = ts
        rel = ts - t0
        data = [int(b, 16) for b in data_str.strip().split()]

        if bus == 2:
            if msg_id == 0x3E9 and len(data) >= 2:
                vv = (data[0] >> 7) & 0x1
                vspd_raw = ((data[0] & 0x7F) << 8) | data[1]
                if vv == 0:
                    frames_3e9.append((rel, vspd_raw * 0.015625))
            elif msg_id == 0x1F5 and len(data) >= 4:
                frames_1f5.append((rel, data[3] & 0xF))
        elif bus == 3:
            frames_pt[msg_id].append((rel, data))


# ---- Build signed motor RPM proxy ----
def get_lever_at(t):
    lever = 1  # assume Park
    for ft, lp in frames_1f5:
        if ft <= t:
            lever = lp
        else:
            break
    return lever

motor_ts = []
for t, spd in frames_3e9:
    lever = get_lever_at(t)
    sign = -1 if lever == 2 else 1   # Reverse lever = negative RPM
    motor_ts.append((t, sign * spd * MOTOR_RATIO))

print(f"Motor RPM proxy: {len(motor_ts)} samples")
print(f"  Range: {min(v for _,v in motor_ts):.1f} to {max(v for _,v in motor_ts):.1f} RPM")
print(f"  Peak magnitude: {max(abs(v) for _,v in motor_ts):.1f} RPM")
print()

# ---- Powertrain bus overview ----
print(f"Powertrain bus (bus 3): {len(frames_pt)} unique message IDs")
for mid in sorted(frames_pt):
    print(f"  0x{mid:03X}: {len(frames_pt[mid])} frames")
print()


# ---- Interpolation grid ----
t_arr = np.array([t for t, _ in motor_ts])
t_grid = np.linspace(t_arr[0], t_arr[-1], len(motor_ts))

motor_signed = np.array([v for _, v in motor_ts])
motor_abs    = np.abs(motor_signed)

def interp_signal(ts_list, t_grid):
    if len(ts_list) < 5:
        return None
    times = np.array([t for t, v in ts_list])
    vals  = np.array([v for t, v in ts_list], dtype=float)
    # Only interpolate within data span
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

    # Per-byte (raw value)
    for i in range(min(max_dlc, 8)):
        ts_list = [(t, d[i]) for t, d in frame_list if len(d) > i]
        sig = interp_signal(ts_list, t_grid)
        if sig is None:
            continue
        r_s = pearson(motor_signed, sig)
        r_a = pearson(motor_abs, sig)
        results.append((max(abs(r_s), abs(r_a)), r_s, r_a, mid, f'B{i}'))

        # Also try signed-around-128
        sig_c = sig - 128
        r_s2 = pearson(motor_signed, sig_c)
        r_a2 = pearson(motor_abs, sig_c)
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
                r_s = pearson(motor_signed, sig)
                r_a = pearson(motor_abs, sig)
                results.append((max(abs(r_s), abs(r_a)), r_s, r_a, mid, slabel))

results.sort(reverse=True)

print("=" * 80)
print("TOP 40 CORRELATIONS WITH ESTIMATED MOTOR RPM")
print("  r_signed: correlation with signed RPM (+Drive / -Reverse)")
print("  r_abs:    correlation with |RPM| (unsigned magnitude)")
print("=" * 80)
print(f"  {'Msg':>8}  {'Signal':<28}  {'best|r|':>8}  {'r_signed':>9}  {'r_abs':>9}")
print("-" * 72)

seen = set()
shown = 0
for best_r, r_s, r_a, mid, label in results:
    # Deduplicate: skip '-128'/'-32768' variants if raw version already shown nearby
    key = (mid, label.split('-')[0].split('(')[0])
    if key in seen:
        continue
    seen.add(key)
    print(f"  0x{mid:03X}  {label:<28}  {best_r:8.4f}  {r_s:9.4f}  {r_a:9.4f}")
    shown += 1
    if shown >= 40:
        break
