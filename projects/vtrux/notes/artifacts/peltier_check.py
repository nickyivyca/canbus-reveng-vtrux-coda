"""
peltier_check.py  --  Phase 2C: Peltier heater existence check

Plots battery temperature trajectory over full charge sessions for:
  Cold sessions (Jan 2026, after battery swap):
    - charge_M0  T0-T59  (Jan 16 2026, started warm from driving)
    - another_M0 T1-T55  (Jan 23 2026, cold-soaked pack)
  Warm session (single file):
    - full charge then fail (Aug 22 2025; only 0x430 B4/B5 available)

Right axis: 0x18FFD6B3 B2-B3 (LE unsigned x0.05 A = DCDC 12V output current).
  Confirmed present in all sessions; cold-soaked session shows ~9.6A at start
  dropping to ~4.5A -- consistent with a battery heater running hard then backing off.
  Also plots 0x598 battery current (charging proxy) as a thin dashed line.

Goal: compare temperature rise rate and 12V load between cold and warm sessions.
If Peltier active during cold charging: elevated 12V draw early + faster temp rise.

Usage:
  py -3.12 peltier_check.py
"""
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from canre.parsers.autodetect import parse_file
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ARTIFACTS = Path(__file__).parent
VTRUX     = ROOT / "projects/vtrux"
ANCHOR_ID = 0x051

# Battery temperature signals
SIG_507_B0 = (0x507, 0, 40,  {127})   # raw-40=degC, sentinel 127
SIG_430_B5 = (0x430, 5, 100, {254})   # raw-100=degC provisional, sentinel 254
SIG_430_B4 = (0x430, 4, 100, {254})

# Battery current: 0x598 B0-B1 LE unsigned, centered at 32768, scale ~0.04 A/count
# Positive = discharging; during charging this will be negative (pack receiving current)
CURRENT_ID     = 0x598
CURRENT_OFFSET = 32768
CURRENT_SCALE  = 0.04

# DCDC 12V output current: 0x18FFD6B3 B2-B3 LE unsigned x0.05 A (medium confidence)
DCDC_ID    = 0x18FFD6B3
DCDC_SCALE = 0.05

SESSIONS = [
    {
        "label": "charge_M0 (Jan 16 2026, cold -- warm start)",
        "color_temp": "tab:blue",
        "color_curr": "tab:cyan",
        "color_dcdc": "tab:purple",
        "chunks": sorted(
            (VTRUX / "logs/after-battery-swap-charges").glob("charge_M0_T*.log"),
            key=lambda p: int(re.search(r'_T(\d+)', p.stem).group(1))
        ),
        "temp_sig": SIG_507_B0,
        "temp_label": "0x507 B0 (x-40)",
    },
    {
        "label": "another_M0 (Jan 23 2026, cold-soaked)",
        "color_temp": "tab:green",
        "color_curr": "lime",
        "color_dcdc": "tab:olive",
        "chunks": sorted(
            (VTRUX / "logs/after-battery-swap-charges").glob("another_M0_T*.log"),
            key=lambda p: int(re.search(r'_T(\d+)', p.stem).group(1))
        ),
        "temp_sig": SIG_507_B0,
        "temp_label": "0x507 B0 (x-40)",
    },
    {
        "label": "full charge then fail (Aug 22 2025, warm)",
        "color_temp": "tab:red",
        "color_curr": "tab:orange",
        "color_dcdc": "tab:brown",
        "chunks": [VTRUX / "logs/full charge then fail.log"],
        "temp_sig": SIG_430_B5,
        "temp_label": "0x430 B5 (x-100, provisional)",
    },
]


def find_pt_bus(path, max_frames=5000):
    n = 0
    try:
        for frame in parse_file(path):
            if frame.arbitration_id == ANCHOR_ID:
                return frame.bus
            n += 1
            if n >= max_frames:
                break
    except Exception:
        pass
    return None


def extract_chunk(path, pt_bus, temp_sig, t_offset=0.0):
    """
    Returns (temp_series, curr_series, dcdc_series, last_t).
    Each series is [(t, val), ...].
    last_t is the last timestamp seen (for stitching offset).
    """
    cid, byte, offset, sentinels = temp_sig
    temp_out = []
    curr_out = []
    dcdc_out = []
    last_t = 0.0
    try:
        for frame in parse_file(path):
            if frame.bus != pt_bus:
                continue
            t = frame.timestamp + t_offset
            if t > last_t:
                last_t = t
            aid = frame.arbitration_id
            if aid == cid and len(frame.data) > byte:
                val = frame.data[byte]
                if val not in sentinels:
                    temp_out.append((t, val - offset))
            elif aid == CURRENT_ID and len(frame.data) >= 2:
                raw = frame.data[0] | (frame.data[1] << 8)
                amps = (raw - CURRENT_OFFSET) * CURRENT_SCALE
                curr_out.append((t, amps))
            elif aid == DCDC_ID and len(frame.data) >= 4:
                raw = frame.data[2] | (frame.data[3] << 8)
                dcdc_out.append((t, raw * DCDC_SCALE))
    except Exception as e:
        print("    chunk error {}: {}".format(path.name, e))
    return temp_out, curr_out, dcdc_out, last_t


def process_session(session):
    chunks = session["chunks"]
    if not chunks:
        print("  No chunks found for: {}".format(session["label"]))
        return [], [], []

    print("  {} chunks".format(len(chunks)))
    all_temp = []
    all_curr = []
    all_dcdc = []
    t_offset = 0.0

    # Use PT bus from first chunk
    pt_bus = None
    for chunk in chunks[:5]:
        pt_bus = find_pt_bus(chunk)
        if pt_bus is not None:
            break
    if pt_bus is None:
        print("  WARNING: PT bus not found, using bus 0")
        pt_bus = 0

    for i, chunk in enumerate(chunks):
        if i % 10 == 0:
            print("    chunk {}/{}...".format(i + 1, len(chunks)))
        temp, curr, dcdc, last_t = extract_chunk(chunk, pt_bus, session["temp_sig"],
                                                  t_offset=t_offset)
        all_temp.extend(temp)
        all_curr.extend(curr)
        all_dcdc.extend(dcdc)
        # Advance offset by duration of this chunk
        if last_t > t_offset:
            t_offset = last_t

    print("    {} temp, {} batt-curr, {} dcdc-curr samples, span {:.1f}h".format(
        len(all_temp), len(all_curr), len(all_dcdc),
        (t_offset / 3600) if t_offset > 0 else 0))
    return all_temp, all_curr, all_dcdc


def plot_session(ax_temp, ax_curr, ax_dcdc, temp_series, curr_series, dcdc_series, session):
    if temp_series:
        ts, vs = zip(*temp_series)
        ts_h = [t / 3600 for t in ts]
        ax_temp.plot(ts_h, vs, '-', color=session["color_temp"], linewidth=1.0,
                     label="{} -- {}".format(session["label"], session["temp_label"]),
                     alpha=0.9)
    if dcdc_series:
        ts, vs = zip(*dcdc_series)
        ts_h = [t / 3600 for t in ts]
        ax_dcdc.plot(ts_h, vs, '-', color=session["color_dcdc"], linewidth=1.0,
                     alpha=0.85, label="{} -- DCDC 12V current".format(session["label"]))
    if curr_series:
        ts, vs = zip(*curr_series)
        ts_h = [t / 3600 for t in ts]
        ax_curr.plot(ts_h, vs, '--', color=session["color_curr"], linewidth=0.6,
                     alpha=0.45, label="{} -- batt current (proxy)".format(session["label"]))


def main():
    fig, axes = plt.subplots(3, 1, figsize=(16, 14), sharex=False)

    # Right axis: DCDC 12V current (primary right)
    axes_dcdc = [ax.twinx() for ax in axes]
    # Far-right axis: battery current (secondary, offset outward)
    axes_curr = []
    for ax in axes:
        ax3 = ax.twinx()
        ax3.spines['right'].set_position(('outward', 60))
        axes_curr.append(ax3)

    for i, session in enumerate(SESSIONS):
        print("Processing: {}".format(session["label"]))
        temp_series, curr_series, dcdc_series = process_session(session)

        ax_t = axes[i]
        ax_d = axes_dcdc[i]
        ax_c = axes_curr[i]

        plot_session(ax_t, ax_c, ax_d, temp_series, curr_series, dcdc_series, session)

        ax_t.set_title(session["label"], fontsize=9)
        ax_t.set_ylabel("Battery Temp (degC)", fontsize=8, color=session["color_temp"])
        ax_t.tick_params(axis='y', labelcolor=session["color_temp"])
        ax_t.set_xlabel("Time (hours)", fontsize=8)
        ax_t.grid(True, alpha=0.3)
        ax_t.legend(fontsize=7, loc='upper left')

        ax_d.set_ylabel("DCDC 12V current (A)", fontsize=8, color=session["color_dcdc"])
        ax_d.tick_params(axis='y', labelcolor=session["color_dcdc"])
        ax_d.legend(fontsize=7, loc='upper right')

        ax_c.set_ylabel("Batt current (A, +ve=discharge)", fontsize=7,
                        color=session["color_curr"])
        ax_c.tick_params(axis='y', labelcolor=session["color_curr"], labelsize=6)
        ax_c.legend(fontsize=6, loc='lower right')

    fig.suptitle("Peltier Check -- Battery Temperature + DCDC 12V Current\n"
                 "Cold sessions (Jan 2026) vs Warm session (Aug 2025)\n"
                 "Peltier signature: elevated 12V draw early in cold session, "
                 "decaying as pack warms",
                 fontsize=9)
    plt.tight_layout()

    out = ARTIFACTS / "peltier_check.png"
    fig.savefig(str(out), dpi=150, bbox_inches='tight')
    print("Saved: {}".format(out.name))
    plt.close('all')


if __name__ == "__main__":
    main()
