"""
plot_batt_temps.py  --  V1 + V2 battery temperature visualization

Plots 0x373 B3, 0x507 B0/B1, 0x430 B4/B5 for:
  - Stitched evap log (part1 + part2, generator on then off)
  - Current limiting test log (high I^2*t stress)

V2 check: look for B0/B1 of 0x507 delta widening during generator operation.

Usage:
  py -3.12 plot_batt_temps.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from canre.parsers.autodetect import parse_file
import matplotlib
matplotlib.use("Agg")          # non-interactive backend -- saves to file
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

ARTIFACTS = Path(__file__).parent
LOG_EVAP1  = ROOT / "projects/vtrux/logs/vtruxevapdrivelog4.log"
LOG_EVAP2  = ROOT / "projects/vtrux/logs/vtruxevapdrivelog4part2.log"
LOG_CURR   = ROOT / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"

ANCHOR_ID  = 0x051

# Signals to extract: (can_id, byte, label, color, invalid_sentinels)
SIGNALS = [
    (0x373, 3, "0x373 B3 (enclosure/board)", "black",       set()),
    (0x506, 1, "0x506 B1",                   "tab:cyan",    set()),
    (0x506, 2, "0x506 B2",                   "tab:olive",   set()),
    (0x506, 3, "0x506 B3",                   "tab:brown",   set()),
    (0x507, 0, "0x507 B0",                   "tab:blue",    {127}),
    (0x507, 1, "0x507 B1",                   "tab:red",     {127}),
    (0x430, 4, "0x430 B4 (raw)",             "tab:green",   {254}),
    (0x430, 5, "0x430 B5 (raw)",             "tab:orange",  {254}),
]


def find_pt_bus(path):
    for frame in parse_file(path):
        if frame.arbitration_id == ANCHOR_ID:
            return frame.bus
    return None


def extract_signals(path, t_offset=0.0):
    """
    Stream log, return dict: (can_id, byte) -> [(t, raw_val), ...]
    t_offset is added to all timestamps (for stitching).
    Only returns values on the PT bus. Filters sentinel values.
    """
    # Two-pass: first find PT bus, then collect
    pt_bus = find_pt_bus(path)
    if pt_bus is None:
        print("  WARNING: PT bus not found in {}".format(path.name))
        pt_bus = -1

    result = {(cid, b): [] for cid, b, *_ in SIGNALS}
    sentinels = {(cid, b): inv for cid, b, _, _, inv in SIGNALS}

    for frame in parse_file(path):
        if frame.bus != pt_bus:
            continue
        for cid, b, *_ in SIGNALS:
            if frame.arbitration_id == cid and len(frame.data) > b:
                val = frame.data[b]
                if val not in sentinels[(cid, b)]:
                    result[(cid, b)].append((frame.timestamp + t_offset, val))

    return result


def merge(d1, d2):
    out = {}
    for k in d1:
        out[k] = d1[k] + d2.get(k, [])
    for k in d2:
        if k not in out:
            out[k] = d2[k]
    return out


def ts_to_xy(series):
    if not series:
        return [], []
    t, v = zip(*series)
    return list(t), list(v)


def plot_panel(ax, data, title, markers=None):
    """
    data: dict (can_id, byte) -> [(t, raw), ...]
    markers: list of (t, label) for vertical lines
    """
    legend_patches = []
    for cid, b, label, color, _ in SIGNALS:
        series = data.get((cid, b), [])
        if not series:
            continue
        t, v = ts_to_xy(series)

        # Secondary axis for 0x430 (different raw scale)
        if cid == 0x430:
            # raw-100 = degC  ->  plot on right axis if available, else just raw
            ax.plot(t, v, '.', color=color, markersize=2, alpha=0.7,
                    label=label + " [raw, right scale]")
        else:
            # x-40 = degC
            ax.plot(t, [rv - 40 for rv in v], '-', color=color, linewidth=1.2,
                    label=label + " (degC, x-40)")

        legend_patches.append(mpatches.Patch(color=color, label=label))

    if markers:
        for t_mark, lbl in markers:
            ax.axvline(t_mark, color='gray', linestyle='--', linewidth=0.8, alpha=0.6)
            ax.text(t_mark + 2, ax.get_ylim()[0] if ax.get_ylim()[0] != 0 else 15,
                    lbl, fontsize=7, color='gray', rotation=90, va='bottom')

    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Temperature (0x373/0x507: degC via x-40)")
    ax.legend(fontsize=7, loc='upper left')
    ax.grid(True, alpha=0.3)

    # Add raw right axis label for 0x430
    ax.set_ylabel("degC (0x373/507 x-40)  |  raw (0x430 right)", fontsize=8)


def main():
    print("Extracting evap log part 1...")
    d1 = extract_signals(LOG_EVAP1)
    # Duration of part 1 (last timestamp)
    t_end_p1 = max(
        (series[-1][0] for series in d1.values() if series),
        default=0.0
    )
    print("  Part 1 duration: {:.1f}s".format(t_end_p1))

    print("Extracting evap log part 2 (offset {:.1f}s)...".format(t_end_p1))
    d2 = extract_signals(LOG_EVAP2, t_offset=t_end_p1)

    evap_data = merge(d1, d2)

    print("Extracting current limiting test...")
    curr_data = extract_signals(LOG_CURR)

    # ---- Plot ----
    fig, axes = plt.subplots(2, 1, figsize=(14, 9))
    fig.suptitle("Battery Temperature Candidates -- Vtrux\n"
                 "0x373 B3 / 0x506 B1-B3 / 0x507 B0-B1: degC via raw-40  |  "
                 "0x430 B4-B5: raw (right axis, raw-100=degC provisional)",
                 fontsize=10)

    # Evap panel markers: generator on/off transition at part1/part2 boundary
    evap_markers = [
        (t_end_p1, "gen off / part2 start"),
    ]
    plot_panel(axes[0], evap_data,
               "Stitched Evap Drive (part1 + part2)  --  "
               "generator running ~part1, off at {:.0f}s".format(t_end_p1),
               markers=evap_markers)

    plot_panel(axes[1], curr_data,
               "Current Limiting Test (high I^2*t, 1809s)")

    # Add a secondary y-axis for 0x430 raw values on each panel
    for ax in axes:
        ax2 = ax.twinx()
        ax2.set_ylabel("0x430 B4/B5 raw (raw-100=degC?)", fontsize=8, color='gray')
        ax2.tick_params(axis='y', labelcolor='gray')
        # Set limits to roughly match raw values (121-141 nominal range)
        ax2.set_ylim(100, 160)

    plt.tight_layout()

    out_png = ARTIFACTS / "batt_temps_evap_and_currentlimit.png"
    fig.savefig(str(out_png), dpi=150, bbox_inches='tight')
    print("Saved: {}".format(out_png.name))

    # ---- V2: delta plot (B1-B0 of 0x507) on evap log ----
    b0_series = evap_data.get((0x507, 0), [])
    b1_series = evap_data.get((0x507, 1), [])

    if b0_series and b1_series:
        # Forward-fill B0 at B1 sample times to compute delta
        b0_iter = iter(b0_series)
        t0_cur, v0_cur = next(b0_iter, (None, None))
        t0_next_pair = next(b0_iter, None)

        deltas = []
        for t1, v1 in b1_series:
            # Advance B0 to just past t1
            while t0_next_pair and t0_next_pair[0] <= t1:
                t0_cur, v0_cur = t0_next_pair
                t0_next_pair = next(b0_iter, None)
            if v0_cur is not None:
                deltas.append((t1, v1 - v0_cur))

        if deltas:
            fig2, ax = plt.subplots(figsize=(14, 4))
            td, vd = ts_to_xy(deltas)
            ax.plot(td, vd, '-', color='purple', linewidth=1.2)
            ax.axhline(0, color='black', linewidth=0.5)
            ax.axvline(t_end_p1, color='gray', linestyle='--', linewidth=0.8, alpha=0.7)
            ax.text(t_end_p1 + 2, max(vd) * 0.9 if vd else 1,
                    "gen off", fontsize=8, color='gray')
            ax.set_title("0x507 B1 - B0 delta (degC) -- Stitched Evap Log\n"
                         "Widening delta = exhaust-side sensor heating faster",
                         fontsize=10)
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("B1 - B0 (raw counts = degC at x-40)")
            ax.grid(True, alpha=0.3)
            fig2.tight_layout()
            out2 = ARTIFACTS / "batt_temps_exhaust_delta.png"
            fig2.savefig(str(out2), dpi=150, bbox_inches='tight')
            print("Saved: {}".format(out2.name))
    else:
        print("  Skipped delta plot: 0x507 not found in evap log")

    plt.close('all')
    print("Done.")


if __name__ == "__main__":
    main()
