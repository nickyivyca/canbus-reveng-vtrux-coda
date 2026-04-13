"""
torque_thermal_scan.py

Scan for PT bus bytes that correlate with SMOOTHED MOTOR TORQUE MAGNITUDE
in vtruxunpluggedpumpoverheattest.log.

Motivation: the previous DCDC-temp scan used a smooth monotonic reference, which
would miss IGBT-type temperature signals that are wavy (tracking torque) but also
trend upward overall. This scan uses |torque| convolved with an exponential thermal
kernel (tau=30s and tau=60s) as the reference, which should find signals that
follow motor load with a thermal lag.

Expected signal character:
- Positively correlated with smoothed |torque|: rising IGBT-side temperature
- Negatively correlated: current limit / thermal derating headroom (decreasing as load rises)
- Pump cooling response: should DROP in cycle 2 when pump at full speed (unlike 0x483)

Key timestamps in overheat test log:
  Cycle 1 (no cooling): t=0 - 411.7s
  Key-off gap:          t=411.7 - 471.2s
  Pump reconnect:       t=471.3s
  Pump at full speed:   t~660s
  Log end:              t=705s
"""

import sys
import os
import math
import struct

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file

LOG = os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                   'vtruxunpluggedpumpoverheattest.log')
PT_BUS = 3  # Bus 3 is PT bus (has 0x051)

# Cycle 1 analysis window (before key-off; DCDC temp rises monotonically here)
WIN_START = 100.0
WIN_END   = 411.0

# Cycle 2: compare just before key-off vs pump-at-full-speed window
PRE_KEYOFF_START  = 380.0
PRE_KEYOFF_END    = 411.0
PUMP_FULL_START   = 660.0
PUMP_FULL_END     = 705.0

# Thermal smoothing time constants (seconds)
TAUS = [15.0, 30.0, 60.0]

# Torque reference IDs and byte slices
#   0x471 B0-B1 LE int16: generator inverter torque feedback (90.9 Hz)
#   0x5A2 B4-B5 LE int16: drivetrain torque feedback (20 Hz)
TORQUE_REFS = [
    (0x471, 0, 1, 'gen_torque'),
    (0x5A2, 4, 5, 'drive_torque'),
]

# IDs and bytes already confirmed/attributed -- skip in output
SKIP_IDS = {
    0x18FFD5C0, 0x18FFDAC0, 0x18FFDBC0,  # charger temps (DBC confirmed)
    0x18FFD6B3,  # DCDC measurements incl B6-B7 temperature (confirmed)
    0x18FF0320,  # PE pump feedback (confirmed)
    0x18EF2000,  # VCU pump command (confirmed)
    0x375,       # BMS message counter
}

THRESHOLD_R = 0.40  # min |r| to include in output


# -------------------------------------------------------------------------
def pearsonr(xs, ys):
    n = len(xs)
    if n < 10:
        return float('nan')
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx  = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy  = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx < 1e-9 or dy < 1e-9:
        return float('nan')
    return num / (dx * dy)


def exp_smooth_series(times, values, tau):
    """Apply single-pole exponential (IIR) smoothing to an irregularly-sampled series.
    Returns list of smoothed values at the same timestamps."""
    if not times:
        return []
    out = [values[0]]
    for i in range(1, len(times)):
        dt = times[i] - times[i - 1]
        alpha = 1.0 - math.exp(-dt / tau) if tau > 0 else 1.0
        out.append(out[-1] + alpha * (values[i] - out[-1]))
    return out


def interp(t_ref, t_query, vals_ref):
    """Linear interpolation of (t_ref, vals_ref) at t_query timestamps.
    Returns list of interpolated values (nan for out-of-range)."""
    result = []
    j = 0
    n = len(t_ref)
    for tq in t_query:
        while j < n - 1 and t_ref[j + 1] <= tq:
            j += 1
        if tq < t_ref[0] or tq > t_ref[-1]:
            result.append(float('nan'))
        elif j >= n - 1:
            result.append(vals_ref[-1])
        else:
            frac = (tq - t_ref[j]) / (t_ref[j + 1] - t_ref[j]) if t_ref[j + 1] != t_ref[j] else 0
            result.append(vals_ref[j] + frac * (vals_ref[j + 1] - vals_ref[j]))
    return result


def le_int16(b0, b1):
    raw = b0 | (b1 << 8)
    if raw >= 32768:
        raw -= 65536
    return raw


# -------------------------------------------------------------------------
print("Parsing log file...", flush=True)
frames_by_bus = {}  # bus -> list of (t, arb_id, data)
for frame in parse_file(LOG):
    bus = frame.bus
    if bus not in frames_by_bus:
        frames_by_bus[bus] = []
    frames_by_bus[bus].append((frame.timestamp, frame.arbitration_id, frame.data))

print(f"  Buses found: {sorted(frames_by_bus.keys())}", flush=True)

pt_frames = frames_by_bus.get(PT_BUS, [])
print(f"  PT bus (Bus {PT_BUS}) frames: {len(pt_frames):,}", flush=True)

# Build per-ID frame lists on PT bus
from collections import defaultdict
id_frames = defaultdict(list)  # arb_id -> [(t, data)]
for t, aid, data in pt_frames:
    id_frames[aid].append((t, bytes(data) if not isinstance(data, (bytes, bytearray)) else data))

# -------------------------------------------------------------------------
# Extract torque reference signals
print("\nExtracting torque references...", flush=True)

torque_series = {}  # ref_name -> (times, abs_values)
for (aid, lo_byte, hi_byte, ref_name) in TORQUE_REFS:
    frames = id_frames.get(aid, [])
    times, vals = [], []
    for t, data in frames:
        if len(data) > hi_byte:
            raw = le_int16(data[lo_byte], data[hi_byte])
            times.append(t)
            vals.append(abs(raw))
    torque_series[ref_name] = (times, vals)
    if times:
        print(f"  {ref_name} (0x{aid:X} B{lo_byte}-B{hi_byte}): "
              f"{len(times)} frames, |torque| range {min(vals)}-{max(vals)}", flush=True)
    else:
        print(f"  {ref_name} (0x{aid:X}): NOT FOUND", flush=True)

# -------------------------------------------------------------------------
# Build smoothed reference signals
print("\nBuilding smoothed torque references...", flush=True)
smooth_refs = {}  # (ref_name, tau) -> (times, smoothed_vals)
for ref_name, (times, vals) in torque_series.items():
    if not times:
        continue
    for tau in TAUS:
        smoothed = exp_smooth_series(times, vals, tau)
        smooth_refs[(ref_name, tau)] = (times, smoothed)
        print(f"  {ref_name} tau={tau:.0f}s: smoothed range "
              f"{min(smoothed):.1f}-{max(smoothed):.1f}", flush=True)

# -------------------------------------------------------------------------
# Collect all PT bus bytes as candidates
print("\nCollecting PT bus candidates...", flush=True)
# candidate_data[id][byte_idx] = (times_window, vals_window, times_all, vals_all)
candidates = {}  # (arb_id, byte_idx) -> (t_win, v_win, t_all, v_all)

for aid, frames in id_frames.items():
    if aid in SKIP_IDS:
        continue
    n_bytes = max(len(d) for _, d in frames) if frames else 0
    for bx in range(n_bytes):
        t_win, v_win, t_all, v_all = [], [], [], []
        t_pre, v_pre, t_pump, v_pump = [], [], [], []
        for t, data in frames:
            if len(data) <= bx:
                continue
            val = data[bx]
            t_all.append(t)
            v_all.append(val)
            if WIN_START <= t <= WIN_END:
                t_win.append(t)
                v_win.append(val)
            if PRE_KEYOFF_START <= t <= PRE_KEYOFF_END:
                t_pre.append(t)
                v_pre.append(val)
            if PUMP_FULL_START <= t <= PUMP_FULL_END:
                t_pump.append(t)
                v_pump.append(val)

        if len(set(v_win)) < 5:
            continue  # not enough variation in window

        candidates[(aid, bx)] = (t_win, v_win, t_pre, v_pre, t_pump, v_pump, t_all, v_all)

print(f"  {len(candidates)} candidates with >=5 unique values in window", flush=True)

# -------------------------------------------------------------------------
# Correlation scan
print("\nRunning correlation scan...", flush=True)

results = []  # (arb_id, bx, ref_name, tau, r, pump_delta, n_unique_win)

for (aid, bx), (t_win, v_win, t_pre, v_pre, t_pump, v_pump, t_all, v_all) in candidates.items():
    best_r = 0.0
    best_ref = None
    best_tau = None
    pump_delta = float('nan')

    # Compute pump cooling response
    if t_pre and t_pump:
        mean_pre  = sum(v_pre)  / len(v_pre)
        mean_pump = sum(v_pump) / len(v_pump)
        pump_delta = mean_pump - mean_pre  # negative means dropped with cooling

    for (ref_name, tau), (ref_times, ref_vals) in smooth_refs.items():
        # Interpolate reference to candidate timestamps in window
        ref_at_win = interp(ref_times, t_win, ref_vals)
        # Drop pairs where ref is nan
        pairs = [(v, r) for v, r in zip(v_win, ref_at_win) if not math.isnan(r)]
        if len(pairs) < 10:
            continue
        vv, rr = zip(*pairs)
        r = pearsonr(list(vv), list(rr))
        if math.isnan(r):
            continue
        if abs(r) > abs(best_r):
            best_r = r
            best_ref = ref_name
            best_tau = tau

    if abs(best_r) >= THRESHOLD_R:
        n_unique = len(set(v_win))
        results.append((aid, bx, best_ref, best_tau, best_r, pump_delta, n_unique))

# Sort by |r| descending
results.sort(key=lambda x: -abs(x[4]))

# -------------------------------------------------------------------------
# Output
out_path = os.path.join(os.path.dirname(__file__), 'torque_thermal_candidates.txt')
with open(out_path, 'w') as f:
    header = (
        "Torque-smoothed thermal correlation scan -- vtruxunpluggedpumpoverheattest.log\n"
        "Reference: smoothed |gen_torque| (0x471 B0-1) and |drive_torque| (0x5A2 B4-5)\n"
        f"Taus: {TAUS} seconds\n"
        f"Window: t={WIN_START}-{WIN_END}s  |  Threshold: |r|>={THRESHOLD_R}\n"
        "pump_delta: mean(t=660-705s) - mean(t=380-411s); negative = dropped with cooling\n"
        "\n"
        f"{'ID':<20} {'Byte':>4}  {'BestRef':<15} {'tau':>5}  {'r':>8}  {'pump_delta':>10}  {'n_uniq':>6}\n"
        "-" * 80 + "\n"
    )
    f.write(header)
    print(header, end='')

    for (aid, bx, ref_name, tau, r, pump_delta, n_unique) in results:
        id_str = f"0x{aid:X}" if aid < 0x80000000 else f"0x{aid:X}"
        pd_str = f"{pump_delta:+.1f}" if not math.isnan(pump_delta) else "   n/a"
        line = (f"{id_str:<20} {bx:>4}  {str(ref_name):<15} {tau:>5.0f}"
                f"  {r:>+.4f}  {pd_str:>10}  {n_unique:>6}\n")
        f.write(line)
        print(line, end='')

print(f"\nResults written to: {out_path}", flush=True)
