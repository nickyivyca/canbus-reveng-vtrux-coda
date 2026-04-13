"""
plot_power.py

Plot all three 0x598 power channels (battery A, generator B, drivetrain C)
on the left Y axis and motor speed (0x5A2 B2-B3) on the right Y axis.

Sign convention (positive = providing power to HV bus):
  A (B0-B1) battery   : + discharge,  - charging/regen
  B (B2-B3) generator : + generating, - motoring/cranking
  C (B4-B5) drivetrain: + consuming,  - regenerating

Scale: 0.04124 A/count  (calibrated from climit log:
       180 kW discharge at +13192 cts/343.6 V → 0.03971
       100 kW regen     at  -5770 cts/405.4 V → 0.04275, mean = 0.04124)

Generates three PNGs in the same folder as this script:
  plot_power_climit.png
  plot_power_evap1.png
  plot_power_evap2.png

Usage:
    python plot_power.py
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

LOGS_DIR = PROJECT_ROOT / "projects" / "vtrux" / "logs"
CLIMIT   = LOGS_DIR / "vtruxcurrentlimitingtest.log"
EVAP1    = LOGS_DIR / "vtruxevapdrivelog4.log"
EVAP2    = LOGS_DIR / "vtruxevapdrivelog4part2.log"

SCALE_A = 0.04124   # A/count


# ---------- helpers ----------------------------------------------------------

def u16_le(data, b):
    if len(data) < b + 2: return None
    return data[b] | (data[b + 1] << 8)

def s16_le(data, b):
    v = u16_le(data, b)
    return None if v is None else (v - 0x10000 if v >= 0x8000 else v)

def nearest(series, t, max_dt=3.0):
    if not series: return None
    lo, hi = 0, len(series) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if series[mid][0] < t: lo = mid + 1
        else: hi = mid
    best_i, best_dt = lo, abs(series[lo][0] - t)
    for i in (lo - 1, lo + 1):
        if 0 <= i < len(series):
            dt = abs(series[i][0] - t)
            if dt < best_dt:
                best_dt, best_i = dt, i
    return series[best_i][1] if best_dt <= max_dt else None


# ---------- collection -------------------------------------------------------

def collect(log_path):
    d = dict(s598a=[], s598b=[], s598c=[], hv_dcdc=[], hv_482=[], mtr_rpm=[])
    print(f"  Reading {log_path.name} ...", file=sys.stderr)
    for frame in parse_file(str(log_path)):
        t   = frame.timestamp
        cid = frame.arbitration_id
        dat = frame.data
        if cid == 0x598 and len(dat) >= 6:
            a = u16_le(dat, 0); b = u16_le(dat, 2); c = u16_le(dat, 4)
            if a is not None: d["s598a"].append((t, a - 32768))
            if b is not None: d["s598b"].append((t, b - 32768))
            if c is not None: d["s598c"].append((t, c - 32768))
        elif cid == 0x18FFD6B3 and len(dat) >= 6:
            v = s16_le(dat, 4)
            if v is not None: d["hv_dcdc"].append((t, v * 0.05))
        elif cid == 0x482 and len(dat) >= 3:
            v = u16_le(dat, 1)
            if v is not None: d["hv_482"].append((t, float(v)))
        elif cid == 0x5A2 and len(dat) >= 4:
            v = u16_le(dat, 2)
            if v is not None: d["mtr_rpm"].append((t, v - 32768))
    return d


def build_power_series(data, slot_key):
    """Convert raw current counts + nearest HV voltage → kW timeseries."""
    pwr_t, pwr_kw = [], []
    for t, cur_counts in data[slot_key]:
        v_hv = nearest(data["hv_dcdc"], t)
        if v_hv is None or v_hv < 100:
            v_hv = nearest(data["hv_482"], t)
        if v_hv is None or v_hv < 100:
            continue
        pwr_kw.append(cur_counts * SCALE_A * v_hv / 1000.0)
        pwr_t.append(t)
    return pwr_t, pwr_kw


# ---------- plotting ---------------------------------------------------------

BG_OUTER  = "#1a1a2e"
BG_INNER  = "#16213e"
CLR_BATT  = "#00b4d8"   # cyan   — battery
CLR_GEN   = "#06d6a0"   # green  — generator
CLR_DRIVE = "#ffd166"   # yellow — drivetrain
CLR_RPM   = "#aaaaaa"   # grey   — motor speed
CLR_ZERO  = "#ffffff"


def make_plot(log_path, title, out_path):
    data = collect(log_path)

    batt_t,  batt_kw  = build_power_series(data, "s598a")
    gen_t,   gen_kw   = build_power_series(data, "s598b")
    drive_t, drive_kw = build_power_series(data, "s598c")
    rpm_t  = [t for t, _ in data["mtr_rpm"]]
    rpm_v  = [v for _, v in data["mtr_rpm"]]

    print(f"  Battery  : {len(batt_t)} samples, "
          f"{min(batt_kw):.1f}–{max(batt_kw):.1f} kW", file=sys.stderr)
    print(f"  Generator: {len(gen_t)} samples, "
          f"{min(gen_kw):.1f}–{max(gen_kw):.1f} kW", file=sys.stderr)
    print(f"  Drivetrain:{len(drive_t)} samples, "
          f"{min(drive_kw):.1f}–{max(drive_kw):.1f} kW", file=sys.stderr)
    print(f"  Motor spd : {len(rpm_t)} samples, "
          f"{min(rpm_v)}–{max(rpm_v)} counts", file=sys.stderr)

    fig, ax1 = plt.subplots(figsize=(18, 5))
    fig.patch.set_facecolor(BG_OUTER)
    ax1.set_facecolor(BG_INNER)

    # Power channels (left axis)
    ax1.plot(drive_t, drive_kw, color=CLR_DRIVE, linewidth=0.6, alpha=0.7,
             label="Drivetrain C (B4-B5)")
    ax1.plot(batt_t,  batt_kw,  color=CLR_BATT,  linewidth=0.8,
             label="Battery A (B0-B1)")
    ax1.plot(gen_t,   gen_kw,   color=CLR_GEN,   linewidth=0.8, alpha=0.9,
             label="Generator B (B2-B3)")
    ax1.axhline(0, color=CLR_ZERO, linewidth=0.4, linestyle="--", alpha=0.35)

    ax1.set_xlabel("Time (s)", color="white")
    ax1.set_ylabel("Power (kW)\n+ = discharge/generate/consume   − = charge/crank/regen",
                   color="white", fontsize=8)
    ax1.tick_params(axis="y", labelcolor="white")
    ax1.tick_params(axis="x", labelcolor="white")
    ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:.0f}"))
    for sp in ax1.spines.values(): sp.set_edgecolor("#444466")

    # Motor speed (right axis)
    ax2 = ax1.twinx()
    ax2.plot(rpm_t, rpm_v, color=CLR_RPM, linewidth=0.5, alpha=0.6,
             label="Motor speed (cts)")
    ax2.set_ylabel("Motor speed (0x5A2 B2-B3, counts)", color=CLR_RPM, fontsize=8)
    ax2.tick_params(axis="y", labelcolor=CLR_RPM)
    ax2.set_facecolor(BG_INNER)
    for sp in ax2.spines.values(): sp.set_edgecolor("#444466")

    # Annotate peaks for battery channel
    if batt_kw:
        i_max = batt_kw.index(max(batt_kw))
        i_min = batt_kw.index(min(batt_kw))
        for i, lbl in [(i_max, f"A peak\n{batt_kw[i_max]:.0f} kW"),
                       (i_min, f"A trough\n{batt_kw[i_min]:.0f} kW")]:
            dy = -18 if batt_kw[i] > 0 else +18
            ax1.annotate(lbl, xy=(batt_t[i], batt_kw[i]),
                         xytext=(batt_t[i] + 20, batt_kw[i] + dy),
                         color=CLR_BATT, fontsize=7,
                         arrowprops=dict(arrowstyle="->", color=CLR_BATT, lw=0.7))

    # Annotate generator peak
    if gen_kw:
        i_max_g = gen_kw.index(max(gen_kw))
        ax1.annotate(f"B peak\n{gen_kw[i_max_g]:.0f} kW",
                     xy=(gen_t[i_max_g], gen_kw[i_max_g]),
                     xytext=(gen_t[i_max_g] + 20, gen_kw[i_max_g] + 10),
                     color=CLR_GEN, fontsize=7,
                     arrowprops=dict(arrowstyle="->", color=CLR_GEN, lw=0.7))

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2,
               loc="upper left", facecolor="#0f3460", edgecolor="white",
               labelcolor="white", fontsize=8)

    ax1.set_title(title, color="white", fontsize=11)
    plt.tight_layout()
    plt.savefig(str(out_path), dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  Saved: {out_path.name}", file=sys.stderr)


# ---------- main -------------------------------------------------------------

if __name__ == "__main__":
    jobs = [
        (CLIMIT, "vtruxcurrentlimitingtest — Battery / Generator / Drivetrain power + Motor speed",
         SCRIPT_DIR / "plot_power_climit.png"),
        (EVAP1,  "vtruxevapdrivelog4 (Part 1) — Battery / Generator / Drivetrain power + Motor speed",
         SCRIPT_DIR / "plot_power_evap1.png"),
        (EVAP2,  "vtruxevapdrivelog4part2 (Part 2) — Battery / Generator / Drivetrain power + Motor speed",
         SCRIPT_DIR / "plot_power_evap2.png"),
    ]
    for log, title, out in jobs:
        if not log.exists():
            print(f"Skipping (not found): {log.name}", file=sys.stderr)
            continue
        print(f"\n--- {log.name} ---", file=sys.stderr)
        make_plot(log, title, out)

    print("\nDone.", file=sys.stderr)
