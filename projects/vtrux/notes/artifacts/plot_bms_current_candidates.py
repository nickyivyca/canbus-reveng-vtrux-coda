"""
plot_bms_current_candidates.py

Plot BMS-tier current candidates from bms_current_source_sweep.py alongside
the confirmed 0x598 battery and drivetrain current channels across the full
vtruxcurrentlimitingtest.log.

Panels (shared x-axis):
  1. 0x598 B0-B1 -- battery current (LE uint16 - 32768)
  2. 0x598 B4-B5 -- drivetrain current (LE uint16 - 32768)
  3. 0x420 B3    -- byte (raw); strong battery/drivetrain correlator in sweep
  4. 0x420 B4    -- byte (raw); secondary 0x420 correlator
  5. 0x411 B0-B1 -- BE uint16 (raw); r=-0.962 vs battery in W1
  6. 0x410 B6-B7 -- BE uint16 (raw); consistent 4-window correlator
  7. 0x430 B0-B1 -- BE uint16 (raw); labeled as V_max cell (known voltage)
  8. 0x440 B4    -- byte (raw); consistent 4-window negative correlator

Event shading (from current-limits-investigation.md):
  t=30-72s    downhill unrestricted regen (green)
  t=348-366s  regen limit active (orange) -- corrected window
  t=598-780s  highway discharge limit (red)
  t=~1400s+   generator on (~20% SoC)

Output: artifacts/bms_current_candidates_plot.png
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
OUT = Path(__file__).parent / "bms_current_candidates_plot.png"

# ---------- signals to collect ------------------------------------------------
# Each entry: (arb_id, label, fn)
# fn(data) -> float value, or None if DLC too short

def le16c(lo, hi):
    """LE uint16 centered at 32768."""
    return lambda d: ((d[hi] << 8) | d[lo]) - 32768 if len(d) > hi else None

def be16r(lo, hi):
    """BE uint16 raw (no centering)."""
    return lambda d: (d[lo] << 8) | d[hi] if len(d) > hi else None

def byter(b):
    """Single byte raw."""
    return lambda d: d[b] if len(d) > b else None

SIGNALS = [
    (0x598, '0x598 B0-B1\nbattery current\n(LE-32768)',    le16c(0, 1)),
    (0x598, '0x598 B4-B5\ndrivetrain current\n(LE-32768)', le16c(4, 5)),
    (0x420, '0x420 B3\n(byte raw)',                         byter(3)),
    (0x420, '0x420 B4\n(byte raw)',                         byter(4)),
    (0x411, '0x411 B0-B1\n(BE16 raw)',                      be16r(0, 1)),
    (0x410, '0x410 B6-B7\n(BE16 raw)',                      be16r(6, 7)),
    (0x430, '0x430 B0-B1\n(BE16 raw)\n[known: V_max cell]', be16r(0, 1)),
    (0x440, '0x440 B4\n(byte raw)',                          byter(4)),
]

# ---------- parse log ----------------------------------------------------------
print("Parsing log...")
data = defaultdict(list)   # signal_index -> [(t, val)]

seen_ids = set(aid for aid, *_ in SIGNALS)

frame_count = 0
for frame in parse_file(str(LOG)):
    aid = frame.arbitration_id
    if aid not in seen_ids:
        continue
    t = frame.timestamp
    d = frame.data
    for i, (sig_id, label, fn) in enumerate(SIGNALS):
        if sig_id != aid:
            continue
        v = fn(d)
        if v is not None:
            data[i].append((t, v))
    frame_count += 1
    if frame_count % 500000 == 0:
        print(f"  {frame_count:,} frames...")

print(f"Done. Samples per signal:")
for i, (aid, label, _) in enumerate(SIGNALS):
    print(f"  [{i}] 0x{aid:03X} {label.split(chr(10))[0]}: {len(data[i])}")

# ---------- plot --------------------------------------------------------------
n = len(SIGNALS)
fig, axes = plt.subplots(n, 1, figsize=(18, 2.8 * n), sharex=True)
fig.suptitle(
    'BMS current candidates vs 0x598 current channels\n'
    'Log: vtruxcurrentlimitingtest.log  (full session)',
    fontsize=13, y=1.001
)

# Event windows: (t_start, t_end, label, color, alpha)
EVENTS = [
    (30,   72,   'unrestricted regen',  'green',  0.12),
    (348,  366,  'regen limit active',  'orange', 0.20),
    (598,  780,  'discharge limit',     'red',    0.12),
]

for i, ax in enumerate(axes):
    aid, label, _ = SIGNALS[i]
    tv = data[i]
    if tv:
        ts = [x[0] for x in tv]
        vs = [x[1] for x in tv]
        ax.plot(ts, vs, linewidth=0.6, color='steelblue', rasterized=True)
        ax.set_ylabel(label, fontsize=7.5, labelpad=4)
    else:
        ax.set_ylabel(label + '\n(NO DATA)', fontsize=7.5, color='red')

    # Shade event windows
    for t0, t1, ev_label, color, alpha in EVENTS:
        ax.axvspan(t0, t1, color=color, alpha=alpha, zorder=0)
        if i == 0:
            ax.text((t0 + t1) / 2, ax.get_ylim()[1] if tv else 0,
                    ev_label, ha='center', va='top', fontsize=6.5,
                    color=color, clip_on=True)

    ax.tick_params(labelsize=7)
    ax.grid(True, linewidth=0.3, alpha=0.5)

axes[-1].set_xlabel('Time (s)', fontsize=9)

plt.tight_layout()
fig.savefig(str(OUT), dpi=120, bbox_inches='tight')
print(f"\nSaved: {OUT}")
