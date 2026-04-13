"""
check_energy_integral.py

Energy integral test on vtruxevapdrivelog4.log (Part 1 only).

Window: from the first moment the generator comes on, to the last moment
        it is on before the battery trough (deep discharge / hill climb).

Physics check: while generator keeps battery "topped up", net battery
energy should be near zero.  Any mismatch between
  ∫ generator_power dt  and  ∫ drivetrain_power dt - ∫ battery_net dt
indicates either a scale difference or unmeasured losses (DCDC/aux).

Outputs:
  - Console: t_start, t_end, total kWh per channel, balance residual
  - plot_energy_integral.png: cumulative kWh for each channel over the window
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

LOG      = PROJECT_ROOT / "projects" / "vtrux" / "logs" / "vtruxevapdrivelog4.log"
OUT_PNG  = SCRIPT_DIR / "plot_energy_integral.png"

SCALE_A       = 0.04      # A/count (rounded calibration)
GEN_ON_THRESH = -50       # gen_trq counts; below = generator on


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
    d = dict(s598a=[], s598b=[], s598c=[], hv_dcdc=[], hv_482=[], gen_trq=[])
    print(f"Reading {log_path.name} ...", file=sys.stderr)
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
        elif cid == 0x051:
            v = u16_le(dat, 1)
            if v is not None: d["gen_trq"].append((t, v - 32768))
    return d


# ---------- window detection -------------------------------------------------

def find_window(data):
    # t_start: first moment generator comes on
    gen_on_times = [t for t, v in data["gen_trq"] if v < GEN_ON_THRESH]
    if not gen_on_times:
        raise RuntimeError("No generator-on frames found")
    t_start = min(gen_on_times)

    # t_batt_trough: moment of deepest battery discharge (most negative s598a)
    t_batt_trough, _ = min(data["s598a"], key=lambda x: x[1])

    # t_end: last gen-on frame strictly before the battery trough
    gen_on_before = [t for t in gen_on_times if t < t_batt_trough]
    if not gen_on_before:
        raise RuntimeError("No generator-on frames before battery trough")
    t_end = max(gen_on_before)

    return t_start, t_end, t_batt_trough


# ---------- integration ------------------------------------------------------

def integrate_window(data, t_start, t_end):
    """
    Build a 1-Hz anchor series (using s598a timestamps), look up all other
    signals at each anchor, then integrate with the trapezoid rule.

    Returns list of (t, va, vb, vc, v_hv, gen_trq) within the window.
    """
    rows = []
    for t, va in data["s598a"]:
        if t < t_start or t > t_end:
            continue
        vb  = nearest(data["s598b"],  t)
        vc  = nearest(data["s598c"],  t)
        vgt = nearest(data["gen_trq"], t)
        v_hv = nearest(data["hv_dcdc"], t)
        if v_hv is None or v_hv < 100:
            v_hv = nearest(data["hv_482"], t)
        if vb is None or vc is None or v_hv is None or v_hv < 100:
            continue
        rows.append((t, va, vb, vc, v_hv, vgt if vgt is not None else 0))

    rows.sort(key=lambda r: r[0])
    return rows


def cumulative_kwh(rows):
    """Trapezoidal integration. Returns parallel lists: t, cum_A, cum_B, cum_C."""
    t_list  = []
    cumA    = []
    cumB    = []
    cumC    = []
    eA = eB = eC = 0.0
    prev = None
    for row in rows:
        t, va, vb, vc, v_hv, _ = row
        if prev is not None:
            dt_s = t - prev[0]
            # mid-point voltage for the interval
            v_mid = (v_hv + prev[4]) / 2.0
            # mid-point counts
            a_mid = (va + prev[1]) / 2.0
            b_mid = (vb + prev[2]) / 2.0
            c_mid = (vc + prev[3]) / 2.0
            # energy in kWh: counts × A/count × V × dt_s / 3600
            eA += a_mid * SCALE_A * v_mid * dt_s / 3_600_000.0
            eB += b_mid * SCALE_A * v_mid * dt_s / 3_600_000.0
            eC += c_mid * SCALE_A * v_mid * dt_s / 3_600_000.0
        t_list.append(t)
        cumA.append(eA)
        cumB.append(eB)
        cumC.append(eC)
        prev = row
    return t_list, cumA, cumB, cumC


# ---------- main -------------------------------------------------------------

def main():
    data = collect(LOG)

    t_start, t_end, t_trough = find_window(data)
    duration = t_end - t_start
    print(f"\nWindow:")
    print(f"  Generator first on : t = {t_start:.1f} s")
    print(f"  Generator last on  : t = {t_end:.1f} s  (before battery trough)")
    print(f"  Battery trough     : t = {t_trough:.1f} s")
    print(f"  Window duration    : {duration:.1f} s  ({duration/60:.1f} min)")

    rows = integrate_window(data, t_start, t_end)
    print(f"  Samples in window  : {len(rows)}")

    t_list, cumA, cumB, cumC = cumulative_kwh(rows)

    # Final totals
    E_batt  = cumA[-1] if cumA else 0.0
    E_gen   = cumB[-1] if cumB else 0.0
    E_drive = cumC[-1] if cumC else 0.0

    print(f"\nEnergy totals over window (scale = {SCALE_A} A/count):")
    print(f"  Battery  net (A)  : {E_batt:+.3f} kWh  "
          f"({'discharged' if E_batt > 0 else 'charged'} net)")
    print(f"  Generator    (B)  : {E_gen:+.3f} kWh")
    print(f"  Drivetrain   (C)  : {E_drive:+.3f} kWh")
    print()
    balance = E_batt + E_gen - E_drive
    balance_pct = abs(balance) / abs(E_drive) * 100 if E_drive != 0 else 999
    print(f"  Balance A+B-C     : {balance:+.3f} kWh  ({balance_pct:.1f}% of drivetrain)")
    print()

    # What fraction of generator output went to battery vs drivetrain?
    if E_gen > 0:
        print(f"  Generator vs battery net ratio:  E_gen / |E_batt| = "
              f"{E_gen / abs(E_batt):.1f}x" if abs(E_batt) > 0.001 else
              f"  Battery net ≈ 0 (generator all went to drivetrain)")
    print()

    # Also show gen-on fraction
    if rows:
        n_gen_on = sum(1 for r in rows if r[5] < GEN_ON_THRESH)
        print(f"  Gen-on fraction in window: {n_gen_on}/{len(rows)} = "
              f"{100*n_gen_on/len(rows):.0f}%")
    print()

    # ---- plot ---------------------------------------------------------------
    BG_OUTER = "#1a1a2e"; BG_INNER = "#16213e"
    CLR_BATT = "#00b4d8"; CLR_GEN = "#06d6a0"; CLR_DRIVE = "#ffd166"

    fig, ax = plt.subplots(figsize=(14, 5))
    fig.patch.set_facecolor(BG_OUTER)
    ax.set_facecolor(BG_INNER)

    ax.plot(t_list, cumC, color=CLR_DRIVE, linewidth=1.0, label=f"Drivetrain C  total={E_drive:.2f} kWh")
    ax.plot(t_list, cumA, color=CLR_BATT,  linewidth=1.0, label=f"Battery A net total={E_batt:+.2f} kWh")
    ax.plot(t_list, cumB, color=CLR_GEN,   linewidth=1.0, label=f"Generator B   total={E_gen:.2f} kWh")
    ax.axhline(0, color="white", linewidth=0.4, linestyle="--", alpha=0.3)

    ax.axvline(t_start, color="#ff6b6b", linewidth=0.8, linestyle=":", alpha=0.7,
               label=f"gen on  t={t_start:.0f}s")
    ax.axvline(t_end,   color="#ff6b6b", linewidth=0.8, linestyle=":",  alpha=0.7,
               label=f"gen off t={t_end:.0f}s")

    ax.set_xlabel("Time (s)", color="white")
    ax.set_ylabel("Cumulative energy (kWh)\n+ = discharge/generate/consume", color="white")
    ax.tick_params(colors="white")
    for sp in ax.spines.values(): sp.set_edgecolor("#444466")
    ax.legend(facecolor="#0f3460", edgecolor="white", labelcolor="white", fontsize=8)
    ax.set_title(
        f"Cumulative energy integral — evap Part 1  "
        f"[t={t_start:.0f}s to t={t_end:.0f}s,  {duration/60:.1f} min]\n"
        f"Balance A+B-C = {balance:+.3f} kWh  ({balance_pct:.1f}%)",
        color="white", fontsize=10)
    plt.tight_layout()
    plt.savefig(str(OUT_PNG), dpi=150, facecolor=fig.get_facecolor())
    print(f"Saved: {OUT_PNG.name}")


if __name__ == "__main__":
    main()
