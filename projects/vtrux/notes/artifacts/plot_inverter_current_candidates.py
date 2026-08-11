"""
plot_inverter_current_candidates.py

Plot PT-bus-only generator and drivetrain current candidates from
inverter_current_sweep.py (bus-2 filter + gen-discriminant Pass B).

Generator panels (shared x-axis, top half):
  1.  0x598 B2-B3  -- gen current ref (LE uint16 - 32768)
  2.  0x63C B5-B6  -- gen RPM (BE16r; shading reference)
  3.  0x395 B7     -- byte; W2-W4 r~+0.96
  4.  0x395 B6-B7  -- LE16r; W2-W4 r~+0.96
  5.  0x395 B5-B6  -- LE16r; W2-W4 r~+0.95
  6.  0x645 B1-B2  -- LE16r; W2-W4 r~+0.95
  7.  0x600 B2-B3  -- LE16r; W2-W4 r~-0.95
  8.  0x596 B0-B1  -- LE16r; W2-W4 r~+0.94
  9.  0x64A B6-B7  -- BE16r; W2-W4 r~+0.91
  10. 0x483 B3-B4  -- LE16r; W2-W4 r~+0.91
  11. 0x481 B0-B1  -- LE16r; W2-W4 r~+0.89
  12. 0x054 B0-B1  -- LE16r; W2-W4 r~+0.89
  13. 0x63F B1-B2  -- LE16r; W2-W4 r~-0.87

Drivetrain panels:
  14. 0x598 B4-B5  -- drivetrain current ref (LE uint16 - 32768)
  15. 0x596 B0-B1  -- LE16r; drivetrain r~+0.79
  16. 0x482 B3-B4  -- LE16r; drivetrain r~-0.79
  17. 0x470 B3-B4  -- LE16r; drivetrain r~-0.79
  18. 0x597 B3-B4  -- LE16r; drivetrain r~+0.78

Green shading: t > 431.7s (generator ON).

Log: logs/vtruxevapdrivelog4.log
Output: artifacts/inverter_current_candidates_plot.png
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxevapdrivelog4.log"
OUT = Path(__file__).parent / "inverter_current_candidates_plot.png"

GEN_START = 431.7

def le16r(lo, hi):
    return lambda d: ((d[hi] << 8) | d[lo]) if len(d) > hi else None

def le16c(lo, hi):
    return lambda d: (((d[hi] << 8) | d[lo]) - 32768) if len(d) > hi else None

def be16r(lo, hi):
    """BE uint16: lo=high-byte index, hi=low-byte index."""
    return lambda d: ((d[lo] << 8) | d[hi]) if len(d) > hi else None

def byter(b):
    return lambda d: d[b] if len(d) > b else None

SIGNALS = [
    # --- Generator reference + context ---
    (0x598, '0x598 B2-B3\ngen current ref\n(LE-32768)',           le16c(2, 3)),
    (0x63C, '0x63C B5-B6\ngen RPM\n(BE16r)',                      be16r(5, 6)),
    # --- Top generator candidates (PT bus only) ---
    (0x395, '0x395 B7\n(byte)\nW2-W4 r~+0.96',                   byter(7)),
    (0x395, '0x395 B6-B7\n(LE16r)\nW2-W4 r~+0.96',              le16r(6, 7)),
    (0x395, '0x395 B5-B6\n(LE16r)\nW2-W4 r~+0.95',              le16r(5, 6)),
    (0x645, '0x645 B1-B2\n(LE16r)\nW2-W4 r~+0.95',              le16r(1, 2)),
    (0x600, '0x600 B2-B3\n(LE16r)\nW2-W4 r~-0.95',              le16r(2, 3)),
    (0x596, '0x596 B0-B1\n(LE16r)\nW2-W4 r~+0.94',              le16r(0, 1)),
    (0x64A, '0x64A B6-B7\n(BE16r)\nW2-W4 r~+0.91',              be16r(6, 7)),
    (0x483, '0x483 B3-B4\n(LE16r)\nW2-W4 r~+0.91',              le16r(3, 4)),
    (0x481, '0x481 B0-B1\n(LE16r)\nW2-W4 r~+0.89',              le16r(0, 1)),
    (0x054, '0x054 B0-B1\n(LE16r)\nW2-W4 r~+0.89',              le16r(0, 1)),
    (0x63F, '0x63F B1-B2\n(LE16r)\nW2-W4 r~-0.87',              le16r(1, 2)),
    # --- Drivetrain reference + candidates ---
    (0x598, '0x598 B4-B5\ndrivetrain current ref\n(LE-32768)',    le16c(4, 5)),
    (0x596, '0x596 B0-B1\n(LE16r)\ndrv r~+0.79',                 le16r(0, 1)),
    (0x482, '0x482 B3-B4\n(LE16r)\ndrv r~-0.79',                 le16r(3, 4)),
    (0x470, '0x470 B3-B4\n(LE16r)\ndrv r~-0.79',                 le16r(3, 4)),
    (0x597, '0x597 B3-B4\n(LE16r)\ndrv r~+0.78',                 le16r(3, 4)),
]

# Multiple entries can share the same aid; track by signal index.
print("Parsing log...")
data = defaultdict(list)
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

print("Done.")
for i, (aid, label, _) in enumerate(SIGNALS):
    print(f"  [{i:02d}] 0x{aid:03X} {label.split(chr(10))[0]}: {len(data[i])} samples")

n = len(SIGNALS)
fig, axes = plt.subplots(n, 1, figsize=(18, 2.8 * n), sharex=True)
fig.suptitle(
    'PT-bus inverter current candidates vs 0x598 generator/drivetrain channels\n'
    'Log: vtruxevapdrivelog4.log  (bus 2 only)\n'
    'Green shading = generator ON (t > 431.7s)',
    fontsize=12, y=1.001
)

log_end = max(max(x[0] for x in data[i]) for i in range(n) if data[i])

# Divider between generator and drivetrain sections (panel index 13 = drivetrain ref)
DRV_START_IDX = 13

for i, ax in enumerate(axes):
    aid, label, _ = SIGNALS[i]
    tv = data[i]

    # Highlight drivetrain section with slightly different background
    if i >= DRV_START_IDX:
        ax.set_facecolor('#f8f4ff')

    if tv:
        ts = [x[0] for x in tv]
        vs = [x[1] for x in tv]
        ax.plot(ts, vs, linewidth=0.6, color='steelblue', rasterized=True)
        ax.set_ylabel(label, fontsize=7.5, labelpad=4)
    else:
        ax.set_ylabel(label + '\n(NO DATA)', fontsize=7.5, color='red')

    ax.axvspan(GEN_START, log_end, color='green', alpha=0.07, zorder=0)
    ax.axvline(GEN_START, color='green', linewidth=0.8, linestyle='--', alpha=0.6)
    ax.tick_params(labelsize=7)
    ax.grid(True, linewidth=0.3, alpha=0.5)

axes[-1].set_xlabel('Time (s)', fontsize=9)

plt.tight_layout()
fig.savefig(str(OUT), dpi=120, bbox_inches='tight')
print(f"\nSaved: {OUT}")
