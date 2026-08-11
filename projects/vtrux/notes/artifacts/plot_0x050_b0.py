"""
plot_0x050_b0.py

Plot 0x050 B0 alongside key reference signals from vtruxevapdrivelog4.log
to determine whether B0 tracks generator torque, traction torque, or something else.

Panels:
  1. 0x050 B0 (centered at 128) -- the mystery signal
  2. Generator torque command (0x051 B1-B2 LE, centered 32768, scaled /256)
  3. Generator torque feedback (0x471 B0-B1 LE, centered 32768, scaled /256)
  4. Traction torque feedback (0x5A2 B4-B5 LE, centered 32768, scaled /64)
  5. Throttle (0x592 B2-B3 LE, centered 32768, scaled /256) + generator active flag

Vertical markers:
  t=431: engine start (generator on)
  t=720: zero-throttle cruise window start
  t=1103: exit cluster (Speed- presses)
  t=1108: brake applied

Output: plot_0x050_b0.png
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG    = 'projects/vtrux/logs/vtruxevapdrivelog4.log'
PT_BUS = 2
OUTPUT = 'projects/vtrux/notes/artifacts/plot_0x050_b0.png'

MARKERS = {
    431:  'gen start',
    720:  'cruise (zero-thr)',
    1103: 'exit (Speed-)',
    1108: 'brake',
}

print("Parsing log...")

sig = {
    '0x050_B0':    [],   # (t, val_centered)
    'gen_cmd':     [],   # 0x051 B1-B2 LE centered
    'gen_fb':      [],   # 0x471 B0-B1 LE centered
    'tract_fb':    [],   # 0x5A2 B4-B5 LE centered
    'throttle':    [],   # 0x592 B2-B3 LE centered
    'gen_active':  [],   # 0x053 B0: 4=EV-only, 52=gen-running
}

frame_count = 0
for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t = frame.timestamp
    d = frame.data
    aid = frame.arbitration_id

    if aid == 0x050 and len(d) >= 1:
        sig['0x050_B0'].append((t, d[0] - 128))

    elif aid == 0x051 and len(d) >= 4:
        gen_cmd = ((d[2] << 8) | d[1]) - 32768
        sig['gen_cmd'].append((t, gen_cmd))

    elif aid == 0x471 and len(d) >= 2:
        gen_fb = ((d[1] << 8) | d[0]) - 32768
        sig['gen_fb'].append((t, gen_fb))

    elif aid == 0x5A2 and len(d) >= 6:
        tract_fb = ((d[5] << 8) | d[4]) - 32768
        sig['tract_fb'].append((t, tract_fb))

    elif aid == 0x592 and len(d) >= 4:
        thr = ((d[3] << 8) | d[2]) - 32768
        sig['throttle'].append((t, thr))

    elif aid == 0x053 and len(d) >= 1:
        sig['gen_active'].append((t, d[0]))

    frame_count += 1
    if frame_count % 500000 == 0:
        print(f"  {frame_count:,} frames...")

print(f"Done. {frame_count:,} total frames.")
for k, v in sig.items():
    print(f"  {k}: {len(v)} samples")

# -----------------------------------------------------------------------
# Plot
# -----------------------------------------------------------------------
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

def unzip(pairs):
    if not pairs:
        return [], []
    ts, vs = zip(*pairs)
    return list(ts), list(vs)

fig, axes = plt.subplots(5, 1, figsize=(18, 14), sharex=True)
fig.suptitle('0x050 B0 vs Reference Signals -- vtruxevapdrivelog4.log', fontsize=13)

marker_colors = {431: 'green', 720: 'blue', 1103: 'orange', 1108: 'red'}

def add_markers(ax):
    for t_m, label in MARKERS.items():
        ax.axvline(t_m, color=marker_colors[t_m], lw=1.0, ls='--', alpha=0.7)

# ---- Panel 1: 0x050 B0 ----
ax = axes[0]
ts, vs = unzip(sig['0x050_B0'])
ax.plot(ts, vs, color='purple', lw=0.7, label='0x050 B0 (centered 128)')
ax.axhline(0, color='k', lw=0.4, ls=':')
ax.set_ylabel('B0 - 128\n(counts)')
ax.set_title('0x050 B0 (mystery signal, 9.1 Hz, VCU-sourced)')
ax.legend(loc='upper left', fontsize=8)
add_markers(ax)

# ---- Panel 2: Generator torque command vs 0x050 B0 overlay ----
ax = axes[1]
ts_b0, vs_b0 = unzip(sig['0x050_B0'])
ts_gc, vs_gc = unzip(sig['gen_cmd'])
ax.plot(ts_gc, [v/256 for v in vs_gc], color='darkorange', lw=0.7, alpha=0.8,
        label='Gen torque cmd (0x051 B1-B2) /256')
ax.plot(ts_b0, vs_b0, color='purple', lw=0.7, alpha=0.7,
        label='0x050 B0 (centered 128)')
ax.axhline(0, color='k', lw=0.4, ls=':')
ax.set_ylabel('counts')
ax.set_title('Gen torque cmd vs 0x050 B0 (gen cmd scaled /256 to match 8-bit range)')
ax.legend(loc='upper left', fontsize=8)
add_markers(ax)

# ---- Panel 3: Generator torque feedback vs 0x050 B0 overlay ----
ax = axes[2]
ts_gf, vs_gf = unzip(sig['gen_fb'])
ax.plot(ts_gf, [v/256 for v in vs_gf], color='teal', lw=0.7, alpha=0.8,
        label='Gen torque feedback (0x471 B0-B1) /256')
ax.plot(ts_b0, vs_b0, color='purple', lw=0.7, alpha=0.7,
        label='0x050 B0 (centered 128)')
ax.axhline(0, color='k', lw=0.4, ls=':')
ax.set_ylabel('counts')
ax.set_title('Gen torque feedback vs 0x050 B0')
ax.legend(loc='upper left', fontsize=8)
add_markers(ax)

# ---- Panel 4: Traction torque feedback vs 0x050 B0 overlay ----
ax = axes[3]
ts_tf, vs_tf = unzip(sig['tract_fb'])
ax.plot(ts_tf, [v/64 for v in vs_tf], color='steelblue', lw=0.7, alpha=0.8,
        label='Traction torque feedback (0x5A2 B4-B5) /64')
ax.plot(ts_b0, vs_b0, color='purple', lw=0.7, alpha=0.7,
        label='0x050 B0 (centered 128)')
ax.axhline(0, color='k', lw=0.4, ls=':')
ax.set_ylabel('counts')
ax.set_title('Traction torque feedback vs 0x050 B0')
ax.legend(loc='upper left', fontsize=8)
add_markers(ax)

# ---- Panel 5: Throttle + gen active flag ----
ax = axes[4]
ts_th, vs_th = unzip(sig['throttle'])
ts_ga, vs_ga = unzip(sig['gen_active'])
ax2 = ax.twinx()
ax.plot(ts_th, [v/256 for v in vs_th], color='green', lw=0.7, alpha=0.8,
        label='Throttle (0x592 B2-B3) /256')
ax2.plot(ts_ga, vs_ga, color='red', lw=0.8, alpha=0.6,
         label='Gen status (0x053 B0)', drawstyle='steps-post')
ax.axhline(0, color='k', lw=0.4, ls=':')
ax.set_ylabel('Throttle (counts)')
ax2.set_ylabel('Gen status byte')
ax.set_xlabel('Time (s)')
ax.set_title('Throttle + Generator active status')
lines1, labels1 = ax.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8)
add_markers(ax)

# Marker legend
legend_patches = [mpatches.Patch(color=c, label=f't={t}: {label}')
                  for t, label in MARKERS.items()
                  for c in [marker_colors[t]]]
fig.legend(handles=legend_patches, loc='lower center', ncol=4, fontsize=8,
           bbox_to_anchor=(0.5, 0.0))

plt.tight_layout(rect=[0, 0.03, 1, 1])
plt.savefig(OUTPUT, dpi=130, bbox_inches='tight')
print(f"\nSaved: {OUTPUT}")
