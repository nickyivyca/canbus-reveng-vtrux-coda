"""
check_evap_scale.py

Process each evap log part independently (avoids timestamp discontinuity).
For each part, report:
  - Peak power for all three 0x598 slots (A=B0-B1, B=B2-B3, C=B4-B5)
  - Sign patterns during gen-on vs gen-off periods
  - Balance check
  - Cross-check with 0.041 A/count scale vs known ~45-50 kW generator peak

Sign convention (corrected):
  Positive = providing power TO HV bus (battery discharging, generator generating, drivetrain regen)
  Negative = consuming FROM HV bus (battery charging, motor driving)
  ... but we're also verifying this here.

Usage:
    python check_evap_scale.py
"""

import sys
import math
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from canre.parsers.autodetect import parse_file

LOGS_DIR = PROJECT_ROOT / "projects" / "vtrux" / "logs"
EVAP1    = LOGS_DIR / "vtruxevapdrivelog4.log"
EVAP2    = LOGS_DIR / "vtruxevapdrivelog4part2.log"

SCALE_A = 0.04124       # A/count (mean calibration from climit regen + discharge)
GEN_ON_THRESH = -50     # 0x051 gen_trq counts; < this = generator actively generating


def u16_le(data, b):
    if len(data) < b + 2: return None
    return data[b] | (data[b + 1] << 8)

def s16_le(data, b):
    v = u16_le(data, b)
    return None if v is None else (v - 0x10000 if v >= 0x8000 else v)

def stats(vals):
    if not vals: return None, None, None, None
    n = len(vals)
    mu = sum(vals) / n
    sd = math.sqrt(sum((v - mu)**2 for v in vals) / n)
    return mu, sd, min(vals), max(vals)

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

def collect_one(log_path):
    """Single-file collect — timestamps are self-consistent within one file."""
    d = dict(s598a=[], s598b=[], s598c=[], hv_dcdc=[], hv_482=[],
             gen_trq=[], mtr_rpm=[])
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
        elif cid == 0x5A2 and len(dat) >= 4:
            v = u16_le(dat, 2)
            if v is not None: d["mtr_rpm"].append((t, v - 32768))
    return d

def hv_at(data, t):
    for key in ("hv_dcdc", "hv_482"):
        v = nearest(data[key], t, max_dt=3.0)
        if v is not None and v > 100:
            return v, key
    return None, None

def peak_power(data, slot_key):
    """Find peak positive and peak negative power for a slot."""
    samples = data[slot_key]
    if not samples: return None
    results = {}
    for sign, label in [(+1, "max"), (-1, "min")]:
        best_t, best_raw = max(samples, key=lambda x: sign * x[1])
        v_hv, vsrc = hv_at(data, best_t)
        i_a = best_raw * SCALE_A
        pwr_kw = i_a * v_hv / 1000.0 if v_hv else None
        vgt = nearest(data["gen_trq"], best_t, max_dt=3.0)
        gen_state = "gen-ON" if (vgt is not None and vgt < GEN_ON_THRESH) else "gen-off"
        results[label] = dict(t=best_t, raw=best_raw, v_hv=v_hv, vsrc=vsrc,
                               pwr_kw=pwr_kw, gen_state=gen_state, vgt=vgt)
    return results

def analyze_log(name, log_path):
    print(f"\n{'='*68}")
    print(f"=== {name}: {log_path.name} ===")
    print()
    data = collect_one(log_path)

    t_vals = [t for k in data for t, _ in data[k]]
    if not t_vals:
        print("  No data.")
        return
    print(f"  Time range: {min(t_vals):.1f} – {max(t_vals):.1f} s  "
          f"({(max(t_vals)-min(t_vals))/60:.1f} min)")

    # Generator torque overview
    gt = [v for _, v in data["gen_trq"]]
    if gt:
        n_on = sum(1 for v in gt if v < GEN_ON_THRESH)
        print(f"  Gen torque range: {min(gt):+.0f} to {max(gt):+.0f} counts  "
              f"({n_on}/{len(gt)} frames gen-on)")
    print()

    # Per-slot peak power
    slot_labels = [("s598a", "A = B0-B1"), ("s598b", "B = B2-B3"), ("s598c", "C = B4-B5")]
    print(f"  {'Slot':<12}  {'peak':>6}  {'raw':>7}  {'V_hv':>6}  {'kW':>8}  {'t':>7}  gen-state   vgt")
    print("  " + "-" * 80)
    for key, label in slot_labels:
        pk = peak_power(data, key)
        if not pk: continue
        for which in ("max", "min"):
            r = pk[which]
            kw_s = f"{r['pwr_kw']:+.1f}" if r['pwr_kw'] is not None else "   N/A"
            vhv_s = f"{r['v_hv']:.1f}" if r['v_hv'] else "  N/A"
            vgt_s = f"{r['vgt']:+.0f}" if r['vgt'] is not None else " N/A"
            print(f"  {label:<12}  {which:>6}  {r['raw']:>7}  {vhv_s:>6}  {kw_s:>8}  "
                  f"{r['t']:>7.1f}s  {r['gen_state']:<11} {vgt_s}")
    print()

    # Paired segment analysis (gen-on vs gen-off)
    rows = []
    for t, va in data["s598a"]:
        vb  = nearest(data["s598b"], t)
        vc  = nearest(data["s598c"], t)
        vgt = nearest(data["gen_trq"], t)
        if vb is None or vc is None or vgt is None: continue
        rows.append((t, va, vb, vc, vgt))

    gen_off = [(va, vb, vc) for t, va, vb, vc, vgt in rows if vgt >= GEN_ON_THRESH]
    gen_on  = [(va, vb, vc) for t, va, vb, vc, vgt in rows if vgt <  GEN_ON_THRESH]
    print(f"  Paired samples: {len(rows)}  (gen-off: {len(gen_off)},  gen-on: {len(gen_on)})")

    for seg_label, seg in [("GEN OFF", gen_off), ("GEN ON ", gen_on)]:
        if len(seg) < 5: continue
        A = [r[0] for r in seg]; B = [r[1] for r in seg]; C = [r[2] for r in seg]
        muA, sdA, mnA, mxA = stats(A)
        muB, sdB, mnB, mxB = stats(B)
        muC, sdC, mnC, mxC = stats(C)
        print(f"  [{seg_label}] ({len(seg)} samples)")
        print(f"    {'Slot':<10}  {'mean':>8}  {'std':>8}  {'min':>8}  {'max':>8}  {'peak kW (approx @375V)':>24}")
        for lbl, vals, mu, sd, mn, mx in [
            ("A B0-B1", A, muA, sdA, mnA, mxA),
            ("B B2-B3", B, muB, sdB, mnB, mxB),
            ("C B4-B5", C, muC, sdC, mnC, mxC),
        ]:
            peak_pos = mx * SCALE_A * 375 / 1000
            peak_neg = mn * SCALE_A * 375 / 1000
            print(f"    {lbl:<10}  {mu:>8.1f}  {sd:>8.1f}  {mn:>8.0f}  {mx:>8.0f}  "
                  f"+{peak_pos:.1f} / {peak_neg:.1f} kW")
        print()


def main():
    for name, path in [("Part 1", EVAP1), ("Part 2", EVAP2)]:
        if path.exists():
            analyze_log(name, path)
        else:
            print(f"\n{name} not found: {path}")


if __name__ == "__main__":
    main()
