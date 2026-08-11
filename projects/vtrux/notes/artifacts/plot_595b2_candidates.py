"""
plot_595b2_candidates.py

Plot top candidates from the 0x595 B2 windowed correlation scan.
Full overheat log shown; 1700-2300s correlation window shaded in blue.

Skipped: 0x18FFD6B3 B6 (DCDC output -- not a temperature candidate).

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/plot_595b2_candidates.py
"""

import sys
sys.path.insert(0, '.')
from canre.parsers import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = "projects/vtrux/logs/vtruxgeneratoroverheattest.log"
OUT = "projects/vtrux/notes/artifacts/595b2_candidates.png"

WIN_LO = 1700.0
WIN_HI = 2300.0
MAX_PTS = 5000

# (aid, byte_index, label, r_vs_595b2, color)
PANELS = [
    (0x595,      2, "0x595 B2  [REFERENCE]\nPE glycol temp candidate",         None,    '#1f77b4'),
    (0x594,      5, "0x594 B5  r=-0.768\n20 Hz, range 0-255",                  -0.768,  '#d62728'),
    (0x0870A047, 1, "0x0870A047 B1  r=-0.669\n10 Hz, range 84-90 (7 uniq)",    -0.669,  '#ff7f0e'),
    (0x625,      2, "0x625 B2  r=+0.620\n1 Hz, range 56-62 (7 uniq)",          +0.620,  '#2ca02c'),
    (0x594,      0, "0x594 B0  r=-0.591\n20 Hz, range 0-62",                   -0.591,  '#9467bd'),
    (0x06000001, 6, "0x06000001 B6  r=-0.591\n20 Hz, range 0-31",              -0.591,  '#8c564b'),
    (0x06000002, 3, "0x06000002 B3  r=-0.522\n20 Hz, range 31-35 (5 uniq)",    -0.522,  '#e377c2'),
    (0x06000001, 1, "0x06000001 B1  r=-0.514\n20 Hz, range 220-252",           -0.514,  '#17becf'),
    (0x18FF0320, 3, "0x18FF0320 B3  r=-0.463\n1 Hz -- PE pump coolant temp",   -0.463,  '#bcbd22'),
    (0x484,      0, "0x484 B0  r=+0.454\n1 Hz -- gen motor temp ref",          +0.454,  '#aec7e8'),
    (0x483,      0, "0x483 B0  r=-0.447\n1 Hz -- unknown temp A coarse",       -0.447,  '#98df8a'),
    (0x0870A047, 2, "0x0870A047 B2  r=+0.208\n10 Hz, range 93-99",             +0.208,  '#c5b0d5'),
]

COLLECT_IDS = {aid for aid, _, _, _, _ in PANELS}


def main():
    # Pass 1: find PT bus
    print("Pass 1: finding PT bus ...")
    pt_bus = None
    for frame in parse_file(LOG):
        if frame.arbitration_id == 0x051:
            pt_bus = frame.bus
            break
    print(f"  PT bus = {pt_bus}")

    # Pass 2: collect frames
    print("Pass 2: collecting signals ...")
    raw = {aid: [] for aid in COLLECT_IDS}
    for frame in parse_file(LOG):
        if frame.bus == pt_bus and frame.arbitration_id in COLLECT_IDS:
            raw[frame.arbitration_id].append((frame.timestamp, bytes(frame.data)))

    for aid in COLLECT_IDS:
        print(f"  0x{aid:X}: {len(raw[aid])} frames")

    # Build per-panel timeseries (stride-downsampled)
    def extract(aid, bi):
        ts, vs = [], []
        for t, d in raw[aid]:
            if len(d) > bi:
                ts.append(t)
                vs.append(float(d[bi]))
        n = len(ts)
        if n > MAX_PTS:
            s = n // MAX_PTS
            ts, vs = ts[::s], vs[::s]
        return ts, vs

    # Plot
    n = len(PANELS)
    fig, axes = plt.subplots(n, 1, figsize=(22, n * 1.5), sharex=True)
    fig.suptitle(
        "0x595 B2 correlation candidates -- vtruxgeneratoroverheattest.log\n"
        "Blue shading: correlation window (t=1700-2300s)  |  Negative r = signal decreases as glycol temp rises",
        fontsize=10
    )

    for i, (aid, bi, label, r, color) in enumerate(PANELS):
        ax = axes[i]
        ts, vs = extract(aid, bi)

        if ts:
            ax.plot(ts, vs, color=color, linewidth=0.85, rasterized=True)
        else:
            ax.text(0.5, 0.5, 'no data', transform=ax.transAxes,
                    ha='center', va='center', fontsize=8, color='grey')

        # Correlation window
        ax.axvspan(WIN_LO, WIN_HI, alpha=0.12, color='#1f77b4', linewidth=0)

        r_str = f"  r={r:+.3f}" if r is not None else ""
        ax.set_ylabel(label + r_str, fontsize=7, rotation=0,
                      ha='right', va='center', labelpad=4)
        ax.yaxis.set_label_coords(-0.01, 0.5)
        if ts and vs:
            lo, hi = min(vs), max(vs)
            pad = (hi - lo) * 0.08 if hi > lo else 1.0
            ax.set_ylim(lo - pad, hi + pad)
            ax.text(0.998, 0.88, f"{lo:.0f}-{hi:.0f}  n={len(ts)}",
                    transform=ax.transAxes, fontsize=6,
                    ha='right', va='top', color='#555', style='italic')
        ax.tick_params(labelsize=6)
        ax.grid(axis='x', linestyle=':', linewidth=0.4, alpha=0.5)

    axes[-1].set_xlabel("Time (s)", fontsize=8)
    plt.tight_layout(rect=[0.17, 0, 1, 0.995])
    print(f"Saving {OUT} ...")
    fig.savefig(OUT, dpi=110, bbox_inches='tight')
    plt.close(fig)
    print("Done.")


if __name__ == '__main__':
    main()
