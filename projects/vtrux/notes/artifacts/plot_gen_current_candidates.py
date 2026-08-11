"""
plot_gen_current_candidates.py

Plot generator current candidates from inverter_current_sweep.py alongside
the confirmed 0x598 generator channel and gen RPM reference.

Panels (shared x-axis):
  1. 0x598 B2-B3  -- generator current reference (LE uint16 - 32768)
  2. 0x63C B5-B6  -- generator RPM (confirmed; used to mark gen-on periods)
  3. 0x1ED B4     -- byte raw; W1=0, W2-W4=r~0.99 (exact zero when gen off)
  4. 0x0BE B2     -- byte raw; W1=0, W2-W4=r~0.97
  5. 0x051 B1-B2  -- LE16 raw; confirmed gen torque cmd; r~-0.97 when gen on
  6. 0x471 B0-B1  -- LE16 raw; GMLAN mirror; r~-0.97 when gen on
  7. 0x040 B2-B3  -- LE16 raw; W1=+0.41, W2-W4=r~0.99
  8. 0x597 B3-B4  -- LE16 raw; r~0.97 all windows (not purely gen-specific)
  9. 0x483 B3-B4  -- LE16 raw; W1~0, W2-W4=r~0.95

Event shading:
  t=0-431.7s    generator OFF (no shade)
  t=431.7s+     generator ON (light green)

Log: logs/vtruxevapdrivelog4.log
Output: artifacts/gen_current_candidates_plot.png
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
OUT = Path(__file__).parent / "gen_current_candidates_plot.png"

GEN_START = 431.7  # confirmed from evap-cycle-analysis.md

def le16r(lo, hi):
    """LE uint16 raw."""
    return lambda d: ((d[hi] << 8) | d[lo]) if len(d) > hi else None

def le16c(lo, hi):
    """LE uint16 centered at 32768."""
    return lambda d: (((d[hi] << 8) | d[lo]) - 32768) if len(d) > hi else None

def be16r(lo, hi):
    """BE uint16 raw."""
    return lambda d: ((d[lo] << 8) | d[hi]) if len(d) > hi else None

def byter(b):
    return lambda d: d[b] if len(d) > b else None

SIGNALS = [
    (0x598, '0x598 B2-B3\ngen current ref\n(LE-32768)',      le16c(2, 3)),
    (0x63C, '0x63C B5-B6\ngen RPM\n(BE16 raw)',              be16r(5, 6)),
    (0x1ED, '0x1ED B4\n(byte raw)\nW1=0.000, W2=+0.990',    byter(4)),
    (0x0BE, '0x0BE B2\n(byte raw)\nW1=0.000, W2=+0.968',    byter(2)),
    (0x051, '0x051 B1-B2\n(LE16 raw)\nW1=0.000, W2=-0.976', le16r(1, 2)),
    (0x471, '0x471 B0-B1\n(LE16 raw)\nW1=+0.035, W2=-0.976',le16r(0, 1)),
    (0x040, '0x040 B2-B3\n(LE16 raw)\nW1=+0.407, W2=+0.996',le16r(2, 3)),
    (0x597, '0x597 B3-B4\n(LE16 raw)\nW1=+0.969, W2=+0.996',le16r(3, 4)),
    (0x483, '0x483 B3-B4\n(LE16 raw)\nW1=+0.019, W2=+0.957',le16r(3, 4)),
]

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

print(f"Done.")
for i, (aid, label, _) in enumerate(SIGNALS):
    print(f"  [{i}] 0x{aid:03X} {label.split(chr(10))[0]}: {len(data[i])} samples")

n = len(SIGNALS)
fig, axes = plt.subplots(n, 1, figsize=(18, 2.8 * n), sharex=True)
fig.suptitle(
    'Generator current candidates vs 0x598 generator channel\n'
    'Log: vtruxevapdrivelog4.log  (full session)\n'
    'Green shading = generator ON (t > 431.7s)',
    fontsize=12, y=1.001
)

log_end = max(max(x[0] for x in data[i]) for i in range(n) if data[i])

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

    # Generator ON shading
    ax.axvspan(GEN_START, log_end, color='green', alpha=0.07, zorder=0)
    ax.axvline(GEN_START, color='green', linewidth=0.8, linestyle='--', alpha=0.6)

    ax.tick_params(labelsize=7)
    ax.grid(True, linewidth=0.3, alpha=0.5)

axes[-1].set_xlabel('Time (s)', fontsize=9)

plt.tight_layout()
fig.savefig(str(OUT), dpi=120, bbox_inches='tight')
print(f"\nSaved: {OUT}")
