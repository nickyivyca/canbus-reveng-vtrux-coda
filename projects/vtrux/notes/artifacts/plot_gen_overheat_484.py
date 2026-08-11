"""
plot_gen_overheat_484.py

Plot all gen_overheat_corr_484 scan candidates + known reference signals from
thermal-investigation.md against vtruxgeneratoroverheattest.log.

Layout:
  - Top section  (green bg label): Known signals from thermal-investigation.md
  - Bottom section (blue bg label): All 50 scan candidates in descending |r| order

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/plot_gen_overheat_484.py
"""

import sys
sys.path.insert(0, '.')
from canre.parsers import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = "projects/vtrux/logs/vtruxgeneratoroverheattest.log"
OUT = "projects/vtrux/notes/artifacts/gen_overheat_corr_484_plot.png"

MAX_PTS = 4000   # max points per panel (stride-downsample for fast plotting)

# ---------------------------------------------------------------------------
# Signal definitions
# Each entry: (arbitration_id, decode_spec, label, r_value_or_None)
#   decode_spec = int   -> extract single byte at that index (raw)
#                'int16_B67' -> LE int16 from bytes 6-7, scale 0.1
#                '9bit_B12'  -> (B2[0]<<8)|B1
#                'zone_B2'   -> (B2>>4)&0x0F
#                '10bit_B56' -> (B6<<2)|(B5>>6), scale 2.0
# ---------------------------------------------------------------------------

# Known reference signals (green section)
REF_PANELS = [
    (0x484,       0,           "0x484 B0 -- gen motor temp [REFERENCE]",                None),
    (0x483,       0,           "0x483 B0 -- unknown temp A (raw-100=C, r=+0.911)",       +0.911),
    (0x483,       '9bit_B12',  "0x483 (B2[0]<<8)|B1 -- temp A fine 9-bit",               None),
    (0x483,       'zone_B2',   "0x483 B2[7:4] -- thermal derating zone (3-6)",           None),
    (0x06000002,  '10bit_B56', "0x06000002 (B6<<2)|(B5>>6) x2.0 -- winding temp (C)",   None),
    (0x18FF0320,  3,           "0x18FF0320 B3 -- PE coolant temp (r=-0.044)",            -0.044),
    (0x18FF0320,  5,           "0x18FF0320 B5 -- PE pump speed 0-241 (r=-0.136)",        -0.136),
    (0x18FFD6B3,  'int16_B67', "0x18FFD6B3 B6-B7 LE int16 x0.1 -- DCDC temp (C)",       None),
    (0x595,       2,           "0x595 B2 -- PE glycol temp candidate (r=-0.086)",        -0.086),
    (0x619,       2,           "0x619 B2 -- thermal fault accum {0,46,59,84,99,109}",    None),
    (0x619,       5,           "0x619 B5 -- current headroom / IGBT limit",              None),
    (0x430,       4,           "0x430 B4 -- T_max cell (raw-100=C)",                     None),
    (0x430,       5,           "0x430 B5 -- T_min cell (raw-100=C)",                     None),
    (0x373,       3,           "0x373 B3 -- battery sys temp (raw-40=C)",                None),
    (0x507,       0,           "0x507 B0 -- batt temp sensor A (raw-40=C)",              None),
    (0x507,       1,           "0x507 B1 -- batt temp sensor B (raw-40=C)",              None),
]

# Scan candidates (blue section) - top 50 ordered by abs(r) descending
SCAN_PANELS = [
    (0x483,       0,    "0x483 B0",        +0.911),
    (0x483,       7,    "0x483 B7",        +0.907),
    (0x625,       2,    "0x625 B2",        +0.777),
    (0x06000001,  1,    "0x06000001 B1",   +0.756),
    (0x06000002,  6,    "0x06000002 B6",   +0.727),
    (0x483,       1,    "0x483 B1",        +0.645),
    (0x0870A047,  1,    "0x0870A047 B1",   +0.638),
    (0x594,       2,    "0x594 B2",        +0.602),
    (0x053,       1,    "0x053 B1",        +0.568),
    (0x18FFD6B3,  3,    "0x18FFD6B3 B3",   +0.499),
    (0x0870A047,  2,    "0x0870A047 B2",   +0.451),
    (0x592,       1,    "0x592 B1",        +0.391),
    (0x592,       6,    "0x592 B6",        +0.391),
    (0x06000001,  3,    "0x06000001 B3",   +0.391),
    (0x06000002,  5,    "0x06000002 B5",   -0.335),
    (0x054,       0,    "0x054 B0",        +0.301),
    (0x592,       0,    "0x592 B0",        -0.262),
    (0x483,       6,    "0x483 B6",        +0.241),
    (0x18FFD6B3,  5,    "0x18FFD6B3 B5",   +0.230),
    (0x050,       0,    "0x050 B0",        +0.212),
    (0x594,       0,    "0x594 B0",        +0.210),
    (0x06000001,  6,    "0x06000001 B6",   +0.207),
    (0x594,       5,    "0x594 B5",        -0.186),
    (0x0C0CA040,  3,    "0x0C0CA040 B3",   -0.174),
    (0x592,       5,    "0x592 B5",        -0.167),
    (0x06000002,  2,    "0x06000002 B2",   +0.164),
    (0x06000002,  3,    "0x06000002 B3",   +0.155),
    (0x390,       2,    "0x390 B2",        +0.142),
    (0x18FF0320,  5,    "0x18FF0320 B5",   -0.136),
    (0x390,       3,    "0x390 B3",        +0.132),
    (0x18FF0320,  2,    "0x18FF0320 B2",   -0.107),
    (0x18FF0320,  7,    "0x18FF0320 B7",   -0.106),
    (0x18FF0320,  1,    "0x18FF0320 B1",   -0.106),
    (0x050,       1,    "0x050 B1",        -0.096),
    (0x483,       4,    "0x483 B4",        -0.086),
    (0x595,       2,    "0x595 B2",        -0.086),
    (0x06000002,  0,    "0x06000002 B0",   -0.079),
    (0x483,       5,    "0x483 B5",        -0.078),
    (0x06000002,  4,    "0x06000002 B4",   -0.078),
    (0x0870A047,  3,    "0x0870A047 B3",   -0.061),
    (0x18FF0320,  3,    "0x18FF0320 B3",   -0.044),
    (0x06000001,  4,    "0x06000001 B4",   +0.037),
    (0x625,       4,    "0x625 B4",        +0.034),
    (0x18FF0320,  0,    "0x18FF0320 B0",   -0.034),
    (0x0C0CA040,  1,    "0x0C0CA040 B1",   -0.030),
    (0x000,       1,    "0x000 B1",        +0.023),
    (0x050,       2,    "0x050 B2",        -0.017),
    (0x592,       3,    "0x592 B3",        +0.016),
    (0x390,       5,    "0x390 B5",        +0.014),
    (0x594,       4,    "0x594 B4",        +0.013),
]


def decode_frame(data, spec):
    """Apply decode_spec to frame data bytes. Returns float or None if insufficient data."""
    try:
        if isinstance(spec, int):
            return float(data[spec])
        if spec == '9bit_B12':
            return float(((data[2] & 0x01) << 8) | data[1])
        if spec == 'zone_B2':
            return float((data[2] >> 4) & 0x0F)
        if spec == '10bit_B56':
            raw = (data[6] << 2) | (data[5] >> 6)
            return raw * 2.0
        if spec == 'int16_B67':
            raw = (data[7] << 8) | data[6]
            if raw >= 0x8000:
                raw -= 0x10000
            return raw * 0.1
    except (IndexError, TypeError):
        return None
    return None


def downsample(ts, vs, max_pts):
    """Stride-downsample to at most max_pts points."""
    n = len(ts)
    if n <= max_pts:
        return ts, vs
    step = n // max_pts
    return ts[::step], vs[::step]


def main():
    # Collect all IDs we need to plot
    needed_ids = set()
    all_panels = REF_PANELS + SCAN_PANELS
    for aid, spec, label, r in all_panels:
        needed_ids.add(aid)

    # ------------------------------------------------------------------
    # Pass 1: find PT bus
    # ------------------------------------------------------------------
    print("Pass 1: identifying PT bus ...")
    pt_bus = None
    for frame in parse_file(LOG):
        if frame.arbitration_id == 0x051:
            pt_bus = frame.bus
            break
    if pt_bus is None:
        sys.exit("ERROR: 0x051 not found -- PT bus unknown")
    print(f"  PT bus = {pt_bus}")

    # ------------------------------------------------------------------
    # Pass 2: collect frame data for needed IDs on PT bus
    # ------------------------------------------------------------------
    print("Pass 2: collecting signal data ...")
    # frames_data[(bus, aid)] = list of (t, data_bytes)
    frames_data = {aid: [] for aid in needed_ids}

    for frame in parse_file(LOG):
        if frame.bus != pt_bus:
            continue
        aid = frame.arbitration_id
        if aid in needed_ids:
            frames_data[aid].append((frame.timestamp, bytes(frame.data)))

    for aid, lst in frames_data.items():
        print(f"  0x{aid:X}: {len(lst)} frames")

    # ------------------------------------------------------------------
    # Build timeseries per panel
    # ------------------------------------------------------------------
    def get_ts(aid, spec):
        raw = frames_data.get(aid, [])
        ts, vs = [], []
        for t, data in raw:
            v = decode_frame(data, spec)
            if v is not None:
                ts.append(t)
                vs.append(v)
        return downsample(ts, vs, MAX_PTS)

    # ------------------------------------------------------------------
    # Plot
    # ------------------------------------------------------------------
    n_ref  = len(REF_PANELS)
    n_scan = len(SCAN_PANELS)
    n_total = n_ref + n_scan

    # Height ratios: each signal panel = 1.0; tiny divider rows for section labels
    panel_h = 1.2   # inches per signal panel
    fig_h = n_total * panel_h + 1.5  # 1.5 extra for title + spacing
    fig_w = 20.0

    print(f"Building figure ({n_total} panels, {fig_h:.0f} x {fig_w:.0f} inches) ...")
    fig, axes = plt.subplots(
        n_total, 1,
        figsize=(fig_w, fig_h),
        sharex=True,
    )

    fig.suptitle(
        "Vtrux Generator Overheat Test -- 0x484 B0 Correlation Scan\n"
        "Top: known signals from thermal-investigation.md  |  Bottom: scan candidates by |r|",
        fontsize=11, y=1.0,
    )

    # Color scheme
    REF_COLOR   = '#2ca02c'   # green for reference/known signals
    SCAN_COLOR  = '#1f77b4'   # blue for scan candidates
    HIGH_R_COLOR = '#d62728'  # red for candidates with |r| >= 0.6

    for i, (aid, spec, label, r) in enumerate(REF_PANELS + SCAN_PANELS):
        ax = axes[i]
        ts, vs = get_ts(aid, spec)

        is_ref_section = (i < n_ref)
        if is_ref_section:
            color = REF_COLOR
            lw    = 1.0
        elif r is not None and abs(r) >= 0.6:
            color = HIGH_R_COLOR
            lw    = 1.0
        else:
            color = SCAN_COLOR
            lw    = 0.8

        if ts:
            ax.plot(ts, vs, color=color, linewidth=lw, rasterized=True)
        else:
            ax.text(0.5, 0.5, 'no data', transform=ax.transAxes,
                    ha='center', va='center', fontsize=7, color='grey')

        # Section divider label
        if i == 0:
            ax.set_title("-- Known reference signals (thermal-investigation.md) --",
                         fontsize=8, color='white', loc='left',
                         bbox=dict(facecolor='#2ca02c', pad=2, edgecolor='none'))
        elif i == n_ref:
            ax.set_title("-- Scan candidates: 0x484 B0 correlation, ordered by |r| --",
                         fontsize=8, color='white', loc='left',
                         bbox=dict(facecolor='#1f77b4', pad=2, edgecolor='none'))

        # Panel label: r value in brackets if present
        r_str = f"  r={r:+.3f}" if r is not None else ""
        ax.set_ylabel(label + r_str, fontsize=6.5, rotation=0,
                      ha='right', va='center', labelpad=4)
        ax.yaxis.set_label_coords(-0.01, 0.5)

        if ts and vs:
            lo, hi = min(vs), max(vs)
            pad = (hi - lo) * 0.1 if hi > lo else 1.0
            ax.set_ylim(lo - pad, hi + pad)
        ax.tick_params(axis='y', labelsize=6)
        ax.tick_params(axis='x', labelsize=6)
        ax.grid(axis='x', linestyle=':', linewidth=0.4, alpha=0.5)

    axes[-1].set_xlabel("Time (s)", fontsize=8)

    plt.tight_layout(rect=[0.18, 0, 1, 0.995])

    print(f"Saving to {OUT} ...")
    fig.savefig(OUT, dpi=100, bbox_inches='tight')
    plt.close(fig)
    print("Done.")


if __name__ == '__main__':
    main()
