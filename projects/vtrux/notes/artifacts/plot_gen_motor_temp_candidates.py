"""
plot_gen_motor_temp_candidates.py -- v2

Plots thermal candidates from the drivetrain overheat test.
0x483 and 0x484 shown as 9-bit reconstructions (B1[bit0]<<8)|B0.
Other signals shown as raw bytes.

Key timestamps:
  t=393s   -- drivetrain oil pump unplugged
  t=1953s  -- torque cutback onset
  t=2253s  -- pump reconnected

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/plot_gen_motor_temp_candidates.py
"""

import sys, re
from collections import defaultdict
sys.path.insert(0, '.')
from canre.parsers import parse_file

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except ImportError:
    sys.exit("matplotlib not available")

LOG = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"
OUT = "projects/vtrux/notes/artifacts/gen_motor_temp_candidates2.png"

KEY_TIMES = [
    (393,  'pump unplug'),
    (1953, 'torque cutback'),
    (2253, 'pump reconnect'),
]

# Each entry: (id, extraction_spec, label, color)
# extraction_spec:
#   ('raw', byte_idx)           -- plot raw byte
#   ('9bit', b0_idx, b1_idx)    -- (B1[bit0]<<8)|B0
TARGETS = [
    (0x483,      ('9bit', 0, 1), '0x483 9-bit (B1[0]<<8|B0)  [motor temp A?]', 'black'),
    (0x484,      ('9bit', 0, 1), '0x484 9-bit (B1[0]<<8|B0)  [motor temp B?]', 'darkgreen'),
    (0x595,      ('raw',  2),    '0x595 B2  r=+0.790',                          'blue'),
    (0x0870A047, ('raw',  3),    '0x0870A047 B3  r=+0.964',                     'red'),
    (0x390,      ('raw',  2),    '0x390 B2  r=+0.352',                          'purple'),
]


def main():
    print("Parsing log (PT bus)...")
    raw = defaultdict(lambda: defaultdict(list))  # id -> byte_idx -> [(t,v)]
    pt_bus = None
    target_ids = {tid for tid, _, _, _ in TARGETS}

    for frame in parse_file(LOG):
        if pt_bus is None and frame.arbitration_id == 0x051:
            pt_bus = frame.bus
        if pt_bus is not None and frame.bus != pt_bus:
            continue
        if frame.arbitration_id not in target_ids:
            continue
        for bi, bv in enumerate(frame.data):
            raw[frame.arbitration_id][bi].append((frame.timestamp, bv))

    print(f"  PT bus = {pt_bus}")

    fig, axes = plt.subplots(len(TARGETS), 1, figsize=(14, 2.6 * len(TARGETS)), sharex=True)

    for ax, (tid, spec, label, color) in zip(axes, TARGETS):
        if spec[0] == '9bit':
            _, b0i, b1i = spec
            pairs = list(zip(raw[tid][b0i], raw[tid][b1i]))
            times = [t for (t, _), _ in pairs]
            vals  = [(b1 & 1) << 8 | b0 for (_, b0), (_, b1) in pairs]
            ylabel = '9-bit raw'
        else:
            _, bi = spec
            data  = raw[tid][bi]
            times = [t for t, _ in data]
            vals  = [v for _, v in data]
            ylabel = f'B{bi} raw'

        if not times:
            ax.text(0.5, 0.5, 'no data', transform=ax.transAxes, ha='center')
        else:
            ax.plot(times, vals, color=color, linewidth=0.8)
            ymin, ymax = min(vals), max(vals)
            margin = max((ymax - ymin) * 0.1, 1)
            ax.set_ylim(ymin - margin, ymax + margin)

        for kt, klabel in KEY_TIMES:
            ax.axvline(kt, color='gray', linestyle='--', linewidth=0.8, alpha=0.6)

        ax.set_ylabel(ylabel, fontsize=8)
        ax.set_title(label, fontsize=9, loc='left', pad=2)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel('Time (s)', fontsize=9)
    fig.suptitle('Thermal candidates -- vtruxdrivetrainoverheattest.log\n'
                 '0x483/0x484 as 9-bit reconstructions; others raw',
                 fontsize=10, y=1.01)
    plt.tight_layout()
    plt.savefig(OUT, dpi=130, bbox_inches='tight')
    print(f"Saved: {OUT}")


if __name__ == '__main__':
    main()
