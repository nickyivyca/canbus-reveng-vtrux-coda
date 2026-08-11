"""
plot_climit.py

Plot battery power (left Y) and motor speed (right Y) vs time
for vtruxcurrentlimitingtest.log.

Battery power: 0x598 B0-B1 (battery current counts) x nearest HV voltage
               (preferred source: 0x18FFD6B3 B4-B5, fallback 0x482 B1-B2)
Motor speed:   0x5A2 B2-B3 (raw counts, LE u16 - 32768)

Output: artifacts/plot_climit.png
"""

import sys
import math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from canre.parsers.autodetect import parse_file

LOG = PROJECT_ROOT / "projects" / "vtrux" / "logs" / "vtruxcurrentlimitingtest.log"
OUT = SCRIPT_DIR / "plot_climit.png"

SCALE_A_PER_COUNT = 0.02206   # A/count (from regen peak calibration)


def u16_le(data, b):
    if len(data) < b + 2:
        return None
    return data[b] | (data[b + 1] << 8)


def s16_le(data, b):
    v = u16_le(data, b)
    return None if v is None else (v - 0x10000 if v >= 0x8000 else v)


def collect(log_path):
    batt_cur  = []   # (t, counts)  0x598 B0-B1
    hv_dcdc   = []   # (t, V)       0x18FFD6B3 B4-B5
    hv_482    = []   # (t, V)       0x482 B1-B2
    mtr_rpm   = []   # (t, counts)  0x5A2 B2-B3

    print(f"Reading {log_path.name} ...", file=sys.stderr)
    for frame in parse_file(str(log_path)):
        t   = frame.timestamp
        cid = frame.arbitration_id
        dat = frame.data

        if cid == 0x598 and len(dat) >= 2:
            v = u16_le(dat, 0)
            if v is not None:
                batt_cur.append((t, v - 32768))

        elif cid == 0x18FFD6B3 and len(dat) >= 6:
            v = s16_le(dat, 4)
            if v is not None:
                hv_dcdc.append((t, v * 0.05))

        elif cid == 0x482 and len(dat) >= 3:
            v = u16_le(dat, 1)
            if v is not None:
                hv_482.append((t, float(v)))

        elif cid == 0x5A2 and len(dat) >= 4:
            v = u16_le(dat, 2)
            if v is not None:
                mtr_rpm.append((t, v - 32768))

    return batt_cur, hv_dcdc, hv_482, mtr_rpm


def interp_nearest(series, t, max_dt=3.0):
    """Binary search for nearest sample within max_dt seconds."""
    if not series:
        return None
    lo, hi = 0, len(series) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if series[mid][0] < t:
            lo = mid + 1
        else:
            hi = mid
    best_i, best_dt = lo, abs(series[lo][0] - t)
    for i in (lo - 1, lo + 1):
        if 0 <= i < len(series):
            dt = abs(series[i][0] - t)
            if dt < best_dt:
                best_dt, best_i = dt, i
    return series[best_i][1] if best_dt <= max_dt else None


def main():
    batt_cur, hv_dcdc, hv_482, mtr_rpm = collect(LOG)

    # Build power timeseries: for each battery current sample, look up HV voltage
    # Prefer hv_dcdc (higher fidelity), fall back to hv_482
    pwr_t   = []
    pwr_kw  = []
    for t, cur_counts in batt_cur:
        v_hv = interp_nearest(hv_dcdc, t)
        if v_hv is None or v_hv < 100:
            v_hv = interp_nearest(hv_482, t)
        if v_hv is None or v_hv < 100:
            continue
        # Positive counts = discharging; negate so graph convention is:
        #   positive = discharge (motor drawing power)
        #   negative = regen    (motor returning power)
        i_a = cur_counts * SCALE_A_PER_COUNT
        pwr_kw.append(i_a * v_hv / 1000.0)
        pwr_t.append(t)

    rpm_t = [t for t, _ in mtr_rpm]
    rpm_v = [v for _, v in mtr_rpm]

    print(f"Battery power samples : {len(pwr_t)}", file=sys.stderr)
    print(f"Motor speed samples   : {len(rpm_t)}", file=sys.stderr)
    if pwr_kw:
        print(f"Power range : {min(pwr_kw):.1f} to {max(pwr_kw):.1f} kW", file=sys.stderr)
    if rpm_v:
        print(f"RPM range   : {min(rpm_v)} to {max(rpm_v)} counts", file=sys.stderr)

    # ---- plot ----------------------------------------------------------------
    fig, ax1 = plt.subplots(figsize=(16, 5))
    fig.patch.set_facecolor("#1a1a2e")
    ax1.set_facecolor("#16213e")

    color_pwr = "#00b4d8"
    color_rpm = "#f77f00"

    ax1.plot(pwr_t, pwr_kw, color=color_pwr, linewidth=0.7, label="Battery power (kW)")
    ax1.axhline(0, color="white", linewidth=0.4, linestyle="--", alpha=0.4)
    ax1.set_xlabel("Time (s)", color="white")
    ax1.set_ylabel("Battery power (kW)\n+ = discharging   − = regen/charging", color=color_pwr)
    ax1.tick_params(axis="y", labelcolor=color_pwr)
    ax1.tick_params(axis="x", labelcolor="white")
    ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:.0f}"))

    ax2 = ax1.twinx()
    ax2.plot(rpm_t, rpm_v, color=color_rpm, linewidth=0.6, alpha=0.85, label="Motor speed (counts)")
    ax2.set_ylabel("Motor speed (0x5A2 B2-B3, counts)", color=color_rpm)
    ax2.tick_params(axis="y", labelcolor=color_rpm)
    ax2.set_facecolor("#16213e")

    # Annotate peak regen and peak discharge
    if pwr_kw:
        i_max = pwr_kw.index(max(pwr_kw))
        i_min = pwr_kw.index(min(pwr_kw))
        ax1.annotate(f"peak discharge\n{pwr_kw[i_max]:.0f} kW",
                     xy=(pwr_t[i_max], pwr_kw[i_max]),
                     xytext=(pwr_t[i_max] + 30, pwr_kw[i_max] - 15),
                     color=color_pwr, fontsize=8,
                     arrowprops=dict(arrowstyle="->", color=color_pwr, lw=0.8))
        ax1.annotate(f"peak regen\n{pwr_kw[i_min]:.0f} kW",
                     xy=(pwr_t[i_min], pwr_kw[i_min]),
                     xytext=(pwr_t[i_min] + 30, pwr_kw[i_min] + 15),
                     color=color_pwr, fontsize=8,
                     arrowprops=dict(arrowstyle="->", color=color_pwr, lw=0.8))

    # Combine legends
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2,
               loc="upper left", facecolor="#0f3460", edgecolor="white",
               labelcolor="white", fontsize=8)

    ax1.set_title("vtruxcurrentlimitingtest — Battery power vs Motor speed",
                  color="white", fontsize=11)
    for spine in list(ax1.spines.values()) + list(ax2.spines.values()):
        spine.set_edgecolor("#444466")

    plt.tight_layout()
    plt.savefig(str(OUT), dpi=150, facecolor=fig.get_facecolor())
    print(f"Saved: {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
