"""
Scan all 16-bit pairs (LE and BE) across all DCDC extended IDs (SA=0xB3)
in the parts-truck pump plug-in log, looking for signals that step when
the PE pump is plugged in and unplugged.

Log: vtrux_partstruck_pumpplugin.log
Events (from sidecar .txt):
  - power on
  - sit for a bit
  - plug PE pump (no comms line, runs full speed)
  - drive up/down street
  - come home
  - unplug pump
  - re-plug pump

Detection approach:
  - For each 16-bit pair, compute a rolling median timeseries
  - Score = range_of_rolling_median / (mean_within_window_spread + epsilon)
  - High scores = abrupt sustained level changes (step changes)
  - Also report 12-bit nibble-split pairs per methodology rules
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers.autodetect import parse_file as parse_log
import statistics

LOG = "projects/vtrux/logs/vtrux_partstruck_pumpplugin.log"

def rolling_median(vals, w):
    out = []
    for i in range(len(vals)):
        lo = max(0, i - w // 2)
        hi = min(len(vals), i + w // 2 + 1)
        out.append(statistics.median(vals[lo:hi]))
    return out

def step_score(rm):
    """
    Global range of rolling median divided by mean absolute diff between
    adjacent rolling-median values (proxy for within-window spread).
    Higher => more step-like.
    """
    if len(rm) < 2:
        return 0.0
    grange = max(rm) - min(rm)
    if grange == 0:
        return 0.0
    diffs = [abs(rm[i+1] - rm[i]) for i in range(len(rm) - 1)]
    mean_diff = statistics.mean(diffs) if diffs else 0.0
    return grange / (mean_diff + 0.001)

def extract_16bit_le(b, i):
    return b[i] | (b[i+1] << 8)

def extract_16bit_be(b, i):
    return (b[i] << 8) | b[i+1]

def bimodality(vals):
    """
    Simple bimodality check: if we split at the median, how different are
    the two halves' medians vs the overall spread?
    """
    if len(vals) < 4:
        return 0.0
    med = statistics.median(vals)
    lo = [v for v in vals if v < med]
    hi = [v for v in vals if v >= med]
    if not lo or not hi:
        return 0.0
    lo_med = statistics.median(lo)
    hi_med = statistics.median(hi)
    spread = max(vals) - min(vals)
    if spread == 0:
        return 0.0
    gap = hi_med - lo_med
    return gap / spread

print("Loading log...")
frames = list(parse_log(LOG))
print(f"  Total frames: {len(frames)}")

dcdc_ids = set()
for f in frames:
    if f.is_extended and (f.arbitration_id & 0xFF) == 0xB3:
        dcdc_ids.add(f.arbitration_id)

print(f"\nDCDC IDs found (SA=0xB3): {len(dcdc_ids)}")
for id_ in sorted(dcdc_ids):
    cnt = sum(1 for f in frames if f.arbitration_id == id_)
    print(f"  0x{id_:08X}  ({cnt} frames)")

print("\nScanning 16-bit pairs (LE and BE) in each DCDC ID...")
print("-" * 80)

WINDOW = 15
results = []

for id_ in sorted(dcdc_ids):
    id_frames = [f for f in frames if f.arbitration_id == id_]
    if len(id_frames) < 20:
        continue
    dlc = max(f.dlc for f in id_frames)
    n_bytes = min(dlc, 8)
    times = [f.timestamp for f in id_frames]
    data_list = [f.data for f in id_frames]

    for i in range(n_bytes - 1):
        for enc, label, extractor in [
            ('LE', f'B{i}-B{i+1} LE', lambda b, i=i: extract_16bit_le(b, i)),
            ('BE', f'B{i}-B{i+1} BE', lambda b, i=i: extract_16bit_be(b, i)),
        ]:
            try:
                vals = [extractor(d) for d in data_list if len(d) >= i + 2]
            except Exception:
                continue
            if len(vals) < 20:
                continue
            unique = len(set(vals))
            if unique < 2:
                continue
            rm = rolling_median(vals, WINDOW)
            score = step_score(rm)
            bim = bimodality(vals)
            vmin = min(vals)
            vmax = max(vals)
            vrange = vmax - vmin
            results.append((id_, label, score, bim, vmin, vmax, vrange, unique, vals, times))

results.sort(key=lambda x: -x[2])

print(f"\nTop candidates by step score (WINDOW={WINDOW}):")
print(f"{'ID':12} {'Pair':12} {'StepScore':>10} {'Bimodal':>8} {'Min':>6} {'Max':>6} {'Range':>6} {'Uniq':>5}")
print("-" * 75)
for row in results[:30]:
    id_, label, score, bim, vmin, vmax, vrange, unique, vals, times = row
    print(f"0x{id_:08X}  {label:12} {score:10.1f} {bim:8.3f} {vmin:6} {vmax:6} {vrange:6} {unique:5}")

print("\n--- Also checking 12-bit nibble-split pairs ---")
print("Format: signal_A = (B[i] << 4) | (B[i+1] >> 4)")
print("        signal_B = ((B[i+1] & 0x0F) << 8) | B[i+2]")
print()

nibble_results = []
for id_ in sorted(dcdc_ids):
    id_frames = [f for f in frames if f.arbitration_id == id_]
    if len(id_frames) < 20:
        continue
    n_bytes = min(max(f.dlc for f in id_frames), 8)
    data_list = [f.data for f in id_frames]
    times = [f.timestamp for f in id_frames]
    for i in range(n_bytes - 2):
        try:
            vals_a = [((d[i] << 4) | (d[i+1] >> 4)) for d in data_list if len(d) >= i + 3]
            vals_b = [(((d[i+1] & 0x0F) << 8) | d[i+2]) for d in data_list if len(d) >= i + 3]
        except Exception:
            continue
        for label, vals in [(f'nibA B{i}-{i+1}', vals_a), (f'nibB B{i+1}-{i+2}', vals_b)]:
            if len(vals) < 20:
                continue
            unique = len(set(vals))
            if unique < 2:
                continue
            rm = rolling_median(vals, WINDOW)
            score = step_score(rm)
            bim = bimodality(vals)
            nibble_results.append((id_, label, score, bim, min(vals), max(vals), max(vals)-min(vals), unique))

nibble_results.sort(key=lambda x: -x[2])
print(f"{'ID':12} {'Pair':14} {'StepScore':>10} {'Bimodal':>8} {'Min':>6} {'Max':>6} {'Range':>6} {'Uniq':>5}")
print("-" * 75)
for row in nibble_results[:20]:
    id_, label, score, bim, vmin, vmax, vrange, unique = row
    print(f"0x{id_:08X}  {label:14} {score:10.1f} {bim:8.3f} {vmin:6} {vmax:6} {vrange:6} {unique:5}")

print("\n--- Detailed timeseries for top 10 step-score candidates ---")
print("Showing median values at 10 time slices across the log to reveal transitions")
for row in results[:10]:
    id_, label, score, bim, vmin, vmax, vrange, unique, vals, times = row
    if not times:
        continue
    t0 = min(times)
    t1 = max(times)
    tspan = t1 - t0
    if tspan == 0:
        continue
    n_bins = 10
    bin_meds = []
    for b in range(n_bins):
        lo = t0 + b * tspan / n_bins
        hi = t0 + (b + 1) * tspan / n_bins
        bvals = [v for v, t in zip(vals, times) if lo <= t < hi]
        if bvals:
            bin_meds.append(round(statistics.median(bvals), 1))
        else:
            bin_meds.append(None)
    print(f"  0x{id_:08X} {label:12}  slices: {bin_meds}")
