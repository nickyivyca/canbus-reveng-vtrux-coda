"""
rpm_054_calibrate_plot.py

Step 1: Fit linear scale/offset for 0x054 B0-B1 LE uint16 vs OBD RPM
        using vtruxgeneratoroverheattest.log (has high-RPM overflow data).

Step 2: Plot calibrated 0x054 B0-B1 vs OBD RPM for both:
  - vtruxgeneratoroverheattest.log
  - logs/generator on then off.log

Also overlays raw 0x63C B6 (the overflowing signal) for comparison.

Output:
  rpm_054_calibration.txt   -- fit coefficients + residual stats
  rpm_054_verification.png  -- 2-row plot (one row per log)

Usage: run from project root
    py -3.12 projects/vtrux/notes/artifacts/rpm_054_calibrate_plot.py
"""

import math
import sys
from bisect import bisect_left
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from canre.parsers import parse_file

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("WARNING: matplotlib not available, skipping plot", file=sys.stderr)

LOGS = {
    "overheat": "projects/vtrux/logs/vtruxgeneratoroverheattest.log",
    "gen_on_off": "projects/vtrux/logs/generator on then off.log",
}
CAL_LOG   = "overheat"   # derive calibration from this log
OUT_TXT   = "projects/vtrux/notes/artifacts/rpm_054_calibration.txt"
OUT_PNG   = "projects/vtrux/notes/artifacts/rpm_054_verification.png"

PT_ANCHORS     = {0x051}
GM_OBD_ANCHORS = {0x040, 0x041, 0x042, 0x043, 0x044}
GM_UNF_ANCHORS = {0x1E5, 0x500}


def detect_buses(log_path, max_scan=500_000):
    found = {}
    for frame in parse_file(log_path):
        cid = frame.arbitration_id
        b = frame.bus
        if cid in PT_ANCHORS and "PT" not in found:
            found["PT"] = b
        if cid in GM_OBD_ANCHORS and "GM_OBD" not in found:
            found["GM_OBD"] = b
        if cid in GM_UNF_ANCHORS and "GM_UNF" not in found:
            found["GM_UNF"] = b
        if "PT" in found and "GM_OBD" in found:
            break
        max_scan -= 1
        if max_scan <= 0:
            break
    return found


def interp_sorted(xs, ys, x):
    if x < xs[0] or x > xs[-1]:
        return None
    i = bisect_left(xs, x)
    if i == 0:
        return ys[0]
    if i >= len(xs):
        return ys[-1]
    x0, x1 = xs[i-1], xs[i]
    y0, y1 = ys[i-1], ys[i]
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def linreg(xs, ys):
    """Fit y = a*x + b. Returns (a, b, r)."""
    n = len(xs)
    sx  = sum(xs);   sy  = sum(ys)
    sxx = sum(x*x for x in xs)
    sxy = sum(x*y for x, y in zip(xs, ys))
    syy = sum(y*y for y in ys)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return None, None, None
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    # Pearson r
    dx = math.sqrt(max(0, sxx - sx*sx/n))
    dy = math.sqrt(max(0, syy - sy*sy/n))
    r  = (sxy - sx*sy/n) / (dx * dy) if dx > 1e-9 and dy > 1e-9 else 0.0
    return a, b, r


def extract_signals(log_path):
    """
    Parse log, return dict with timeseries arrays:
      obd_ts, obd_rpm          -- OBD 0x0C9 engine RPM
      pt054_ts, pt054_le16     -- PT 0x054 B0-B1 LE uint16 (raw)
      pt63c_ts, pt63c_rpm      -- PT 0x63C B6 RPM (16*B6 - 96, wraps at 255)
    """
    print(f"  Detecting buses for {Path(log_path).name}...", file=sys.stderr)
    buses = detect_buses(log_path)
    print(f"    {buses}", file=sys.stderr)
    pt_bus  = buses.get("PT")
    obd_bus = buses.get("GM_OBD")
    if pt_bus is None or obd_bus is None:
        print(f"  ERROR: bus detection failed for {log_path}", file=sys.stderr)
        return None

    obd_ts, obd_rpm = [], []
    pt054_ts, pt054_le16 = [], []
    pt63c_ts, pt63c_rpm  = [], []

    print(f"  Parsing {Path(log_path).name}...", file=sys.stderr)
    for frame in parse_file(log_path):
        b   = frame.bus
        cid = frame.arbitration_id
        t   = frame.timestamp
        d   = frame.data

        if b == obd_bus and cid == 0x0C9 and len(d) >= 3:
            obd_ts.append(t)
            obd_rpm.append(((d[1] << 8) | d[2]) * 0.25)

        elif b == pt_bus and not frame.is_extended:
            if cid == 0x054 and len(d) >= 2:
                pt054_ts.append(t)
                pt054_le16.append((d[1] << 8) | d[0])   # LE: B0=LSB, B1=MSB

            elif cid == 0x63C and len(d) >= 7:
                pt63c_ts.append(t)
                raw = d[6]
                pt63c_rpm.append(16 * raw - 96)          # wraps above ~4000 RPM

    print(f"    OBD RPM frames: {len(obd_ts)}", file=sys.stderr)
    print(f"    0x054 frames:   {len(pt054_ts)}", file=sys.stderr)
    print(f"    0x63C frames:   {len(pt63c_ts)}", file=sys.stderr)

    return {
        "obd_ts": obd_ts,   "obd_rpm": obd_rpm,
        "054_ts": pt054_ts, "054_le16": pt054_le16,
        "63c_ts": pt63c_ts, "63c_rpm":  pt63c_rpm,
    }


def pair_against_obd(sig_ts, sig_vals, obd_ts, obd_rpm, rpm_min=200):
    """Interpolate OBD RPM onto sig timestamps; return paired lists (engine-running only)."""
    paired_sig, paired_rpm = [], []
    for t, v in zip(sig_ts, sig_vals):
        r = interp_sorted(obd_ts, obd_rpm, t)
        if r is not None and r > rpm_min:
            paired_sig.append(v)
            paired_rpm.append(r)
    return paired_sig, paired_rpm


def main():
    all_data = {}
    for name, path in LOGS.items():
        print(f"\nExtracting {name}...", file=sys.stderr)
        data = extract_signals(path)
        if data:
            all_data[name] = data

    if CAL_LOG not in all_data:
        print("ERROR: calibration log not loaded", file=sys.stderr)
        sys.exit(1)

    # ---- Calibration ----
    print("\nFitting calibration...", file=sys.stderr)
    cal = all_data[CAL_LOG]
    paired_le16, paired_rpm = pair_against_obd(
        cal["054_ts"], cal["054_le16"], cal["obd_ts"], cal["obd_rpm"], rpm_min=200
    )
    # Fit: obd_rpm = a * (le16 - 32768) + b
    # i.e. obd_rpm = a * le16_cent + b  where le16_cent = le16 - 32768
    le16_cent = [v - 32768 for v in paired_le16]
    a, b, r = linreg(le16_cent, paired_rpm)
    print(f"  a={a:.6f}  b={b:.4f}  r={r:.6f}  n={len(paired_rpm)}", file=sys.stderr)

    # Residuals
    pred = [a * v + b for v in le16_cent]
    resid = [p - q for p, q in zip(pred, paired_rpm)]
    rmse = math.sqrt(sum(e*e for e in resid) / len(resid))
    max_err = max(abs(e) for e in resid)
    print(f"  RMSE={rmse:.2f} RPM  max_err={max_err:.2f} RPM", file=sys.stderr)

    # Write calibration text
    with open(OUT_TXT, "w", encoding="ascii") as f:
        f.write("0x054 B0-B1 LE uint16 RPM Calibration\n")
        f.write("Fit: OBD_RPM = a * (le16 - 32768) + b\n")
        f.write(f"  a     = {a:.6f}  RPM/count\n")
        f.write(f"  b     = {b:.4f}  RPM (offset)\n")
        f.write(f"  r     = {r:.6f}\n")
        f.write(f"  n     = {len(paired_rpm)} paired samples\n")
        f.write(f"  RMSE  = {rmse:.2f} RPM\n")
        f.write(f"  max_err = {max_err:.2f} RPM\n")
        f.write("\n")
        f.write(f"At engine off  (le16_cent = -1):   predicted RPM = {a*(-1)+b:.1f}\n")
        f.write(f"At idle        (le16_cent = ?): use OBD cross-reference\n")
        f.write("\n")
        f.write("Note: derived from vtruxgeneratoroverheattest.log\n")
        f.write("      engine-running frames only (OBD RPM > 200)\n")

    print(f"  Calibration written to {OUT_TXT}", file=sys.stderr)

    if not HAS_MPL:
        return

    # ---- Plot ----
    print("\nPlotting...", file=sys.stderr)
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=False)
    fig.suptitle(
        f"0x054 B0-B1 LE16 RPM Calibration Verification\n"
        f"Fit: OBD_RPM = {a:.5f} * (le16 - 32768) + {b:.2f} "
        f"  r={r:.5f}  RMSE={rmse:.1f} RPM",
        fontsize=10
    )

    log_order = ["gen_on_off", "overheat"]
    log_titles = {
        "gen_on_off": "generator on then off.log  (normal operating range)",
        "overheat":   "vtruxgeneratoroverheattest.log  (high-RPM / overflow region)",
    }

    for i, log_name in enumerate(log_order):
        if log_name not in all_data:
            axes[i].set_title(f"{log_titles[log_name]}  [NOT LOADED]")
            continue

        ax = axes[i]
        d = all_data[log_name]

        # OBD RPM (reference)
        t0 = d["obd_ts"][0] if d["obd_ts"] else 0
        ax.plot(
            [t - t0 for t in d["obd_ts"]],
            d["obd_rpm"],
            color="black", linewidth=0.8, alpha=0.85, label="OBD RPM (0x0C9)",
            zorder=3
        )

        # 0x054 B0-B1 calibrated
        cal054 = [a * (v - 32768) + b for v in d["054_le16"]]
        ax.plot(
            [t - t0 for t in d["054_ts"]],
            cal054,
            color="royalblue", linewidth=1.0, alpha=0.75,
            label=f"0x054 B0-B1 calibrated  (a={a:.4f}, b={b:.1f})",
            zorder=2
        )

        # 0x63C B6 raw RPM (overflowing)
        ax.plot(
            [t - t0 for t in d["63c_ts"]],
            d["63c_rpm"],
            color="tomato", linewidth=0.6, alpha=0.55, linestyle="--",
            label="0x63C B6 RPM (16*B6-96, overflows >~4000)",
            zorder=1
        )

        ax.set_title(log_titles[log_name], fontsize=9)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("RPM", fontsize=8)
        ax.legend(fontsize=7, loc="upper left")
        ax.tick_params(labelsize=7)
        ax.grid(True, linewidth=0.4, alpha=0.5)

        # Mark overflow threshold
        ax.axhline(4000, color="orange", linewidth=0.8, linestyle=":", alpha=0.7,
                   label="_0x63C overflow threshold (~4000 RPM)")

    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=140)
    print(f"  Plot saved to {OUT_PNG}", file=sys.stderr)


if __name__ == "__main__":
    main()
