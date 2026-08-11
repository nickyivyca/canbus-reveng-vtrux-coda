"""
decode_cell_voltages.py — Decode min/max/avg cell voltages from 0x63A (Vtrux powertrain bus)

Strategy:
  1. Extract 0x63A frames from Bus 2 (powertrain bus)
  2. Extract 0x482 HV pack voltage (B1-B2 LE, integer V/count) as ground truth
  3. Compute V_avg_ref = V_pack / 117 (117 cells in series)
  4. Test all 16-bit byte-pair combinations from 0x63A for correlation with V_avg_ref
  5. Plot the top candidates vs V_avg_ref, and (candidate - V_avg_ref) to show spread

Usage:
    py -3.12 projects/vtrux/notes/artifacts/decode_cell_voltages.py

Output:
    projects/vtrux/notes/artifacts/cell_voltage_analysis.txt
    projects/vtrux/notes/artifacts/plot_cell_voltages.png
"""

import sys
import os
import struct
import math
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

LOG_FILE = REPO_ROOT / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
OUT_TXT  = REPO_ROOT / "projects/vtrux/notes/artifacts/cell_voltage_analysis.txt"
OUT_PNG  = REPO_ROOT / "projects/vtrux/notes/artifacts/plot_cell_voltages.png"

from canre.parsers import parse_file as load_log

N_CELLS = 117

# ---------------------------------------------------------------------------
# Parse log
# ---------------------------------------------------------------------------
print("Loading log...", flush=True)
frames = list(load_log(str(LOG_FILE)))
print(f"  {len(frames):,} frames loaded")

# Identify powertrain bus by presence of 0x051
bus_id_counts: dict[int, dict[int, int]] = {}
for f in frames:
    bus_id_counts.setdefault(f.bus, {})
    bus_id_counts[f.bus][f.arbitration_id] = bus_id_counts[f.bus].get(f.arbitration_id, 0) + 1

pt_bus = None
for bus, id_counts in bus_id_counts.items():
    if 0x051 in id_counts:
        pt_bus = bus
        break
if pt_bus is None:
    print("ERROR: Could not find powertrain bus (no 0x051). Aborting.")
    sys.exit(1)
print(f"  Powertrain bus = Bus {pt_bus}")

# ---------------------------------------------------------------------------
# Extract 0x63A frames
# ---------------------------------------------------------------------------
frames_63A = [(f.timestamp, f.data) for f in frames
              if f.bus == pt_bus and f.arbitration_id == 0x63A and len(f.data) == 8]
print(f"  0x63A frames: {len(frames_63A):,}")

# Extract 0x482 frames (HV pack voltage, B1-B2 LE, integer V/count)
frames_482 = [(f.timestamp, f.data) for f in frames
              if f.bus == pt_bus and f.arbitration_id == 0x482 and len(f.data) >= 3]
print(f"  0x482 frames: {len(frames_482):,}")

if not frames_63A or not frames_482:
    print("ERROR: Missing required frames.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Build pack voltage timeseries from 0x482
# V_pack = B1 + B2*256 (LE uint16, integer V)
# V_avg_ref = V_pack / 117
# ---------------------------------------------------------------------------
t_482 = [t for t, _ in frames_482]
v_pack = [d[1] + d[2] * 256 for _, d in frames_482]
v_avg_ref = [v / N_CELLS for v in v_pack]  # in Volts (not mV)

# Filter to valid driving range (330–430V)
valid_mask = [330 <= v <= 430 for v in v_pack]
n_valid = sum(valid_mask)
print(f"  0x482 valid driving frames (330-430V): {n_valid:,}/{len(frames_482):,}")

# Use nearest-neighbor join: for each 0x63A frame, find the nearest 0x482 frame
def build_index(timestamps):
    """Build a simple sorted list for bisect lookup."""
    return timestamps

import bisect

t_482_sorted = t_482  # already in order

def nearest_v_avg(ts):
    """Return V_avg_ref (V) nearest to timestamp ts."""
    idx = bisect.bisect_left(t_482_sorted, ts)
    if idx == 0:
        return v_avg_ref[0]
    if idx >= len(t_482_sorted):
        return v_avg_ref[-1]
    # Pick the closer of idx-1 and idx
    if abs(t_482_sorted[idx-1] - ts) < abs(t_482_sorted[idx] - ts):
        return v_avg_ref[idx-1]
    return v_avg_ref[idx]

# Build merged timeseries
t_merged = []
raw_data = []
ref_vals = []

for ts, data in frames_63A:
    ref = nearest_v_avg(ts)
    if 330 / N_CELLS <= ref <= 430 / N_CELLS:  # only use valid driving data
        t_merged.append(ts)
        raw_data.append(data)
        ref_vals.append(ref)

print(f"  Merged frames (valid driving): {len(t_merged):,}")

if len(t_merged) < 100:
    print("ERROR: Too few valid merged frames for analysis.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Test all 16-bit byte-pair candidates
# ref_vals is in Volts (avg cell voltage)
# We'll test candidates scaled to match — try scales 0.1mV/count, 1mV/count,
# and also 1/count in Volts (for unusual encodings).
# ---------------------------------------------------------------------------

def pearson_r(xs, ys):
    n = len(xs)
    if n < 2:
        return float('nan')
    xm = sum(xs) / n
    ym = sum(ys) / n
    cov = sum((x - xm) * (y - ym) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - xm)**2 for x in xs))
    sy = math.sqrt(sum((y - ym)**2 for y in ys))
    if sx == 0 or sy == 0:
        return float('nan')
    return cov / (sx * sy)

def uint16_be(data, i):
    return data[i] * 256 + data[i+1]

def uint16_le(data, i):
    return data[i] + data[i+1] * 256

candidates = []

# Test all adjacent byte-pair combinations in BE and LE
for i in range(7):
    for endian, fn in [('BE', uint16_be), ('LE', uint16_le)]:
        raw_vals = [fn(d, i) for d in raw_data]
        # Try multiple scales: 0.1mV -> V, 1mV -> V, and raw correlation (arbitrary scale)
        for scale_label, scale in [('x0.1mV_V', 0.0001), ('x1mV_V', 0.001), ('raw', None)]:
            if scale is not None:
                cand_vals = [v * scale for v in raw_vals]
            else:
                cand_vals = raw_vals
            r = pearson_r(cand_vals, ref_vals)
            if not math.isnan(r):
                # Also test inverted
                r_inv = pearson_r([-v for v in cand_vals], ref_vals)
                best_r = r if abs(r) >= abs(r_inv) else -r
                candidates.append({
                    'label': f'B{i}-B{i+1} {endian} {scale_label}',
                    'bytes': (i, i+1),
                    'endian': endian,
                    'scale': scale,
                    'r': best_r,
                    'vals': cand_vals,
                    'inverted': abs(r_inv) > abs(r),
                    'mean': sum(cand_vals)/len(cand_vals) if scale else None,
                })

# Also test single bytes
for i in range(8):
    raw_vals = [d[i] for d in raw_data]
    r = pearson_r(raw_vals, ref_vals)
    if not math.isnan(r):
        candidates.append({
            'label': f'B{i} (uint8)',
            'bytes': (i,),
            'endian': None,
            'scale': None,
            'r': r,
            'vals': raw_vals,
            'inverted': False,
            'mean': None,
        })

candidates.sort(key=lambda c: -abs(c['r']))

# ---------------------------------------------------------------------------
# Write text report
# ---------------------------------------------------------------------------
lines = []
lines.append("=== 0x63A Cell Voltage Decode Analysis ===")
lines.append(f"Log: {LOG_FILE.name}")
lines.append(f"Merged frames (valid driving): {len(t_merged):,}")
lines.append(f"Reference: 0x482 B1-B2 LE / {N_CELLS} cells = V_avg_ref")
lines.append(f"V_avg_ref range: {min(ref_vals)*1000:.1f}–{max(ref_vals)*1000:.1f} mV")
lines.append("")
lines.append("Top 20 candidates by |Pearson r| vs V_avg_ref:")
lines.append(f"{'Rank':>4}  {'Candidate':<30}  {'r':>7}  {'mean(cand)':>12}  Notes")
lines.append("-" * 80)

for rank, c in enumerate(candidates[:20], 1):
    mean_str = f"{c['mean']*1000:.1f} mV" if c['mean'] is not None else "N/A"
    inv_str = " [inverted]" if c.get('inverted') else ""
    lines.append(f"{rank:4}  {c['label']:<30}  {c['r']:7.4f}  {mean_str:>12}{inv_str}")

lines.append("")

# Decode the top candidate
top = candidates[0]
lines.append(f"TOP CANDIDATE: {top['label']}")
if top['scale']:
    top_vals = top['vals']
    if top.get('inverted'):
        top_vals = [-v for v in top_vals]
    diff = [c - r for c, r in zip(top_vals, ref_vals)]
    lines.append(f"  Mean candidate: {sum(top_vals)/len(top_vals)*1000:.2f} mV")
    lines.append(f"  Mean V_avg_ref: {sum(ref_vals)/len(ref_vals)*1000:.2f} mV")
    lines.append(f"  Mean diff: {sum(diff)/len(diff)*1000:.2f} mV")
    lines.append(f"  Max diff: {max(diff)*1000:.2f} mV, Min diff: {min(diff)*1000:.2f} mV")

# Print top 3 by r, check if any could be max (consistently above ref) or min (below ref)
lines.append("")
lines.append("Top 3 candidates — offset from V_avg_ref:")
for c in candidates[:3]:
    if c['scale']:
        vals = c['vals']
        if c.get('inverted'):
            vals = [-v for v in vals]
        diff = [v - r for v, r in zip(vals, ref_vals)]
        mean_diff = sum(diff) / len(diff)
        lines.append(f"  {c['label']}: mean offset = {mean_diff*1000:+.2f} mV (positive=above avg, negative=below avg)")

lines.append("")
lines.append("0x63A raw byte statistics (from this merged dataset):")
for i in range(8):
    vals = [d[i] for d in raw_data]
    mn = min(vals); mx = max(vals); uc = len(set(vals))
    lines.append(f"  B{i}: min={mn:#04x}={mn} max={mx:#04x}={mx} unique={uc}")

out_str = "\n".join(lines)
print(out_str)

with open(OUT_TXT, "w") as f:
    f.write(out_str)
print(f"\nReport saved to: {OUT_TXT}")

# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Pick the top 3 candidates with scale (not raw/uint8) that have different byte positions
    plot_cands = [c for c in candidates if c['scale'] is not None and c['scale'] < 0.001][:3]
    if not plot_cands:
        plot_cands = candidates[:3]

    # Downsample for plotting (max 5000 points)
    step = max(1, len(t_merged) // 5000)
    t_plot = t_merged[::step]
    ref_plot = [r * 1000 for r in ref_vals[::step]]  # mV

    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)

    # Top panel: candidate signals vs V_avg_ref
    ax = axes[0]
    ax.plot(t_plot, ref_plot, 'k-', linewidth=1.5, label='V_avg_ref = V_pack/117 (mV)', zorder=10)
    colors = ['#e74c3c', '#2ecc71', '#3498db']
    for c, col in zip(plot_cands, colors):
        vals = c['vals'][::step]
        if c.get('inverted'):
            vals = [-v for v in vals]
        v_mv = [v * 1000 for v in vals]
        ax.plot(t_plot, v_mv, '-', color=col, linewidth=0.8, alpha=0.8, label=f"{c['label']} (r={c['r']:.4f})")
    ax.set_ylabel("Cell Voltage (mV)")
    ax.set_title("0x63A Byte Candidates vs V_avg_ref (V_pack/117)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # Bottom panel: (candidate - V_avg_ref) deviation
    ax2 = axes[1]
    for c, col in zip(plot_cands, colors):
        vals = c['vals'][::step]
        if c.get('inverted'):
            vals = [-v for v in vals]
        ref_s = ref_vals[::step]
        diff_mv = [(v - r) * 1000 for v, r in zip(vals, ref_s)]
        ax2.plot(t_plot, diff_mv, '-', color=col, linewidth=0.8, alpha=0.8, label=f"{c['label']}")
    ax2.axhline(0, color='k', linewidth=1.0, linestyle='--')
    ax2.set_ylabel("Δ from V_avg_ref (mV)")
    ax2.set_xlabel("Time (s)")
    ax2.set_title("Deviation from average cell voltage (positive = above avg, negative = below avg)")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(str(OUT_PNG), dpi=120)
    plt.close()
    print(f"Plot saved to: {OUT_PNG}")

except ImportError:
    print("matplotlib not available — skipping plot")
