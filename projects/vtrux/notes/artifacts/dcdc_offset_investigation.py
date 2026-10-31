"""
DCDC calibration offset investigation.

Goal: quantify the systematic bias between the DCDC HV input voltage reading
(0x18FFD6B3 B4-B5, LE signed x0.05 V) and the Bel charger ground truth
(0x18FFD7C0 B0-B1, LE signed x0.05 V) across multiple charging sessions.

The original finding from "full charge then fail.log" was ~7V lower DCDC reading
with MAE=0.94V after correction.  Check whether this offset is consistent across
logs, or whether it varies by session (e.g. temperature-dependent, SoC-dependent,
load-dependent).

Logs with both DCDC and charger active simultaneously = charging logs.
Drive-mode logs have no charger, so they cannot be used for GT comparison.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

DCDC_ID  = 0x18FFD6B3   # B4-B5 LE signed x0.05 V -- HV input voltage
CHGR_ID  = 0x18FFD7C0   # B0-B1 LE signed x0.05 V -- charger GT

LOGS = [
    "projects/vtrux/logs/full charge then fail.log",
    "projects/vtrux/logs/rainychargedebug.log",
    "projects/vtrux/logs/rainychargedebug2.log",
    "projects/vtrux/logs/rainychargedebug3.log",
    "projects/vtrux/logs/rainychargedebug4.log",
    "projects/vtrux/logs/chargingafterturningaroundandnotusingextension.log",
    "projects/vtrux/logs/vtruxchargeafterevaplog-failed.log",
    "projects/vtrux/logs/vtruxchargeafterevaplogattempt2.log",
    "projects/vtrux/logs/unidentified-bus/vtruxunpluggingchargehandleendofcharge.log",
]

def decode_le_signed(b0, b1):
    raw = b0 | (b1 << 8)
    if raw >= 0x8000:
        raw -= 0x10000
    return raw * 0.05

def analyse_log(path):
    """
    Extract paired (charger, DCDC) voltage samples from a charging log.
    Returns dict with stats, or None if either signal absent.
    """
    try:
        frames = list(parse_file(path))
    except Exception as e:
        return {"error": str(e)}

    dcdc_ts = {}
    chgr_ts = {}

    for f in frames:
        if f.arbitration_id == DCDC_ID and len(f.data) >= 6:
            v = decode_le_signed(f.data[4], f.data[5])
            dcdc_ts[f.timestamp] = v
        elif f.arbitration_id == CHGR_ID and len(f.data) >= 2:
            v = decode_le_signed(f.data[0], f.data[1])
            chgr_ts[f.timestamp] = v

    if not dcdc_ts:
        return {"error": "no DCDC frames"}
    if not chgr_ts:
        return {"error": "no charger frames"}

    # Pair each DCDC sample to nearest charger sample (max 0.3s apart)
    chgr_list = sorted(chgr_ts.items())
    chgr_times = [t for t, _ in chgr_list]

    pairs = []
    import bisect
    for t_d, v_d in sorted(dcdc_ts.items()):
        idx = bisect.bisect_left(chgr_times, t_d)
        candidates = []
        for i in (idx - 1, idx):
            if 0 <= i < len(chgr_times):
                dt = abs(chgr_times[i] - t_d)
                if dt < 0.3:
                    candidates.append((dt, chgr_ts[chgr_list[i][0]]))
        if candidates:
            _, v_c = min(candidates)
            pairs.append((v_c, v_d, v_d - v_c))   # (charger, dcdc, bias)

    if not pairs:
        return {"error": "no paired samples within 0.3s"}

    biases = [p[2] for p in pairs]
    chgr_v = [p[0] for p in pairs]
    n = len(pairs)
    mean_bias = sum(biases) / n
    mae = sum(abs(b) for b in biases) / n
    min_b = min(biases)
    max_b = max(biases)

    # Voltage range
    chgr_min = min(chgr_v)
    chgr_max = max(chgr_v)

    # Filter to V >= 350 (avoid pre-contact / startup noise)
    high_pairs = [(c, d, b) for c, d, b in pairs if c >= 350.0]
    if high_pairs:
        hb = [p[2] for p in high_pairs]
        mean_bias_hi = sum(hb) / len(hb)
        mae_hi = sum(abs(b) for b in hb) / len(hb)
        n_hi = len(high_pairs)
    else:
        mean_bias_hi = mae_hi = None
        n_hi = 0

    return {
        "n_pairs": n,
        "chgr_range": (chgr_min, chgr_max),
        "mean_bias_all": mean_bias,
        "mae_all": mae,
        "bias_range": (min_b, max_b),
        "n_hi": n_hi,
        "mean_bias_hi": mean_bias_hi,
        "mae_hi": mae_hi,
    }


def run():
    print("DCDC offset investigation: dcdc_volt - charger_gt (V)")
    print("bias = DCDC - Charger  (negative = DCDC reads low)")
    print()
    fmt_hdr = f"{'Log':<52} {'n':>6}  {'V_range':>14}  {'bias_all':>9}  {'mae_all':>8}  {'n>=350':>7}  {'bias_hi':>9}  {'mae_hi':>8}"
    print(fmt_hdr)
    print("-" * len(fmt_hdr))

    all_biases_hi = []
    for path in LOGS:
        name = os.path.basename(path)[:51]
        r = analyse_log(path)
        if "error" in r:
            print(f"  {name:<52} -- {r['error']}")
            continue

        v_lo, v_hi = r["chgr_range"]
        v_range = f"{v_lo:.1f}-{v_hi:.1f}V"
        bias_all_str  = f"{r['mean_bias_all']:+.2f}V"
        mae_all_str   = f"{r['mae_all']:.3f}V"

        if r["mean_bias_hi"] is not None:
            bias_hi_str = f"{r['mean_bias_hi']:+.2f}V"
            mae_hi_str  = f"{r['mae_hi']:.3f}V"
            all_biases_hi.append(r["mean_bias_hi"])
        else:
            bias_hi_str = "    n/a"
            mae_hi_str  = "   n/a"

        print(f"  {name:<52} {r['n_pairs']:>6}  {v_range:>14}  {bias_all_str:>9}  {mae_all_str:>8}  "
              f"{r['n_hi']:>7}  {bias_hi_str:>9}  {mae_hi_str:>8}")

    if all_biases_hi:
        grand = sum(all_biases_hi) / len(all_biases_hi)
        print()
        print(f"  Grand mean bias (V>=350, {len(all_biases_hi)} logs): {grand:+.3f}V")
        spread = max(all_biases_hi) - min(all_biases_hi)
        print(f"  Spread (max-min across logs): {spread:.3f}V")
        print()
        print("  Interpretation:")
        print(f"    DCDC reads {abs(grand):.2f}V {'lower' if grand < 0 else 'higher'} than charger GT on average.")
        print(f"    Spread of {spread:.3f}V across sessions indicates the offset is "
              + ("consistent (single calibration factor)." if spread < 1.0 else
                 "variable -- may be temperature or load dependent."))


if __name__ == "__main__":
    run()
