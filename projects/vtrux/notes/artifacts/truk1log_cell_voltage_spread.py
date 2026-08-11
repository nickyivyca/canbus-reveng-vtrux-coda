"""
Cell voltage spread for truk1log M1 (parts truck, imbalanced battery charge session).
Decodes bcm_cell_vmax and bcm_cell_vmin (0x430) via DBC across all T chunks.

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/truk1log_cell_voltage_spread.py
"""
import sys, os, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

import cantools
from canre.utils.merge import merge_files
from pathlib import Path

ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')
DBC  = os.path.join(ROOT, 'projects', 'vtrux', 'epri-pt-bus.dbc')

db  = cantools.db.load_file(DBC)
msg = db.get_message_by_frame_id(1072)  # 0x430

# Collect all M1 T-chunks in order
chunk_paths = sorted(
    Path(ROOT, 'projects', 'vtrux', 'logs').glob('truk1log_M1_T*.log'),
    key=lambda p: int(p.stem.split('_T')[1])
)
print(f"Chunks: {len(chunk_paths)}  ({chunk_paths[0].name} .. {chunk_paths[-1].name})")

timestamps, vmax_vals, vmin_vals = [], [], []

for frame in merge_files(chunk_paths):
    if frame.arbitration_id != 0x430 or len(frame.data) < 4:
        continue
    try:
        dec = msg.decode(bytes(frame.data), decode_choices=False)
    except Exception:
        continue
    vmax = dec.get('bcm_cell_vmax')
    vmin = dec.get('bcm_cell_vmin')
    if vmax is None or vmin is None:
        continue
    vmax, vmin = float(vmax), float(vmin)
    if vmax > 3.8 or vmin > 3.8:  # skip sentinel
        continue
    timestamps.append(frame.timestamp)
    vmax_vals.append(vmax)
    vmin_vals.append(vmin)

if not timestamps:
    print("No valid 0x430 frames decoded.")
    sys.exit(1)

spreads = [mx - mn for mx, mn in zip(vmax_vals, vmin_vals)]
n = len(spreads)

print(f"Frames decoded : {n}")
print(f"Time range     : {timestamps[0]:.1f}s -- {timestamps[-1]:.1f}s  ({timestamps[-1]-timestamps[0]:.1f}s total)")
print()
print(f"bcm_cell_vmax  : min={min(vmax_vals):.3f} V  max={max(vmax_vals):.3f} V  mean={sum(vmax_vals)/n:.3f} V")
print(f"bcm_cell_vmin  : min={min(vmin_vals):.3f} V  max={max(vmin_vals):.3f} V  mean={sum(vmin_vals)/n:.3f} V")
print(f"spread (vmax-vmin): min={min(spreads):.3f} V  max={max(spreads):.3f} V  mean={sum(spreads)/n:.3f} V")
print()

# Time-sampled spread every ~5 minutes
print("-- Spread over time (sampled every ~300 s) --")
print(f"{'time(s)':>9}  {'vmax(V)':>8}  {'vmin(V)':>8}  {'spread(V)':>10}")
print("-" * 44)
last_t = None
for t, vmax, vmin, sp in zip(timestamps, vmax_vals, vmin_vals, spreads):
    if last_t is None or t - last_t >= 300.0:
        print(f"{t:9.1f}  {vmax:8.3f}  {vmin:8.3f}  {sp:10.3f}")
        last_t = t
