#!/usr/bin/env python3
"""Correlate voltage/current candidates against charger ground truth."""
import sys
import struct
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from canre.parsers import parse_file


def nearest_match(ref_ts, cand_ts_vals, max_dt=0.1):
    """Match each ref timestamp to nearest candidate value."""
    if not cand_ts_vals:
        return [], []
    cand_idx = 0
    ref_matched = []
    cand_matched = []
    for rt in ref_ts:
        while (cand_idx < len(cand_ts_vals) - 1 and
               abs(cand_ts_vals[cand_idx + 1][0] - rt) < abs(cand_ts_vals[cand_idx][0] - rt)):
            cand_idx += 1
        if abs(cand_ts_vals[cand_idx][0] - rt) <= max_dt:
            ref_matched.append(rt)
            cand_matched.append(cand_ts_vals[cand_idx][1])
    return ref_matched, cand_matched


def pearson(x, y):
    n = len(x)
    if n < 10:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    sx = math.sqrt(max(0, sum((xi - mx) ** 2 for xi in x)))
    sy = math.sqrt(max(0, sum((yi - my) ** 2 for yi in y)))
    if sx == 0 or sy == 0:
        return 0.0
    return sxy / (sx * sy)


def linear_fit(x, y):
    """Return (scale, offset) for y = scale * x + offset."""
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    sxx = sum((xi - mx) ** 2 for xi in x)
    if sxx == 0:
        return 0, 0
    scale = sxy / sxx
    offset = my - scale * mx
    return scale, offset


def main():
    logfile = sys.argv[1] if len(sys.argv) > 1 else "Bel-Inverter/other-logs/truklog_M0_T2.log"

    # Charger ground truth: 0x18FFD7C0 (BELINV_hvBatteryAndCharger)
    #   B0-B1 LE signed * 0.05 = hvBatteryVoltage (V)
    #   B2-B3 LE signed * 0.05 = hvBatteryCurrent (A)
    CHARGER_HV_ID = 0x18FFD7C0

    charger_v = []
    charger_i = []

    candidates = {
        # Voltage candidates
        "0x420_B2B3_LE": [], "0x420_B2B3_BE": [],
        "0x420_B0B1_LE": [], "0x420_B0B1_BE": [],
        "0x420_B3B4_LE": [], "0x420_B3B4_BE": [],
        "0x480_B1B2_BE": [], "0x480_B1B2_LE": [],
        "0x595_B0B1_BE": [], "0x595_B0B1_LE": [],
        "0x644_B0B1_BE": [], "0x644_B0B1_LE": [],
        "0x644_B2B3_BE": [], "0x644_B2B3_LE": [],
        # Current candidates
        "0x639_B5B6_BE": [], "0x639_B5B6_LE": [],
        "0x639_B1B2_BE": [], "0x639_B1B2_LE": [],
        "0x639_B3B4_BE": [], "0x639_B3B4_LE": [],
        "0x592_B0B1_LE": [], "0x592_B0B1_BE": [],
        "0x63A_B0B1_BE": [], "0x63A_B0B1_LE": [],
    }

    for frame in parse_file(logfile):
        d = frame.data
        t = frame.timestamp

        if frame.arbitration_id == CHARGER_HV_ID and len(d) >= 4:
            raw_v = struct.unpack_from("<h", d, 0)[0]
            raw_i = struct.unpack_from("<h", d, 2)[0]
            charger_v.append((t, raw_v * 0.05))
            charger_i.append((t, raw_i * 0.05))

        elif frame.arbitration_id == 0x420 and len(d) >= 5:
            candidates["0x420_B2B3_LE"].append((t, struct.unpack_from("<H", d, 2)[0]))
            candidates["0x420_B2B3_BE"].append((t, struct.unpack_from(">H", d, 2)[0]))
            candidates["0x420_B0B1_LE"].append((t, struct.unpack_from("<H", d, 0)[0]))
            candidates["0x420_B0B1_BE"].append((t, struct.unpack_from(">H", d, 0)[0]))
            candidates["0x420_B3B4_LE"].append((t, struct.unpack_from("<H", d, 3)[0]))
            candidates["0x420_B3B4_BE"].append((t, struct.unpack_from(">H", d, 3)[0]))

        elif frame.arbitration_id == 0x480 and len(d) >= 3:
            candidates["0x480_B1B2_BE"].append((t, struct.unpack_from(">H", d, 1)[0]))
            candidates["0x480_B1B2_LE"].append((t, struct.unpack_from("<H", d, 1)[0]))

        elif frame.arbitration_id == 0x595 and len(d) >= 2:
            candidates["0x595_B0B1_BE"].append((t, struct.unpack_from(">H", d, 0)[0]))
            candidates["0x595_B0B1_LE"].append((t, struct.unpack_from("<H", d, 0)[0]))

        elif frame.arbitration_id == 0x644 and len(d) >= 4:
            candidates["0x644_B0B1_BE"].append((t, struct.unpack_from(">H", d, 0)[0]))
            candidates["0x644_B0B1_LE"].append((t, struct.unpack_from("<H", d, 0)[0]))
            candidates["0x644_B2B3_BE"].append((t, struct.unpack_from(">H", d, 2)[0]))
            candidates["0x644_B2B3_LE"].append((t, struct.unpack_from("<H", d, 2)[0]))

        elif frame.arbitration_id == 0x639 and len(d) >= 7:
            candidates["0x639_B5B6_BE"].append((t, struct.unpack_from(">H", d, 5)[0]))
            candidates["0x639_B5B6_LE"].append((t, struct.unpack_from("<H", d, 5)[0]))
            candidates["0x639_B1B2_BE"].append((t, struct.unpack_from(">H", d, 1)[0]))
            candidates["0x639_B1B2_LE"].append((t, struct.unpack_from("<H", d, 1)[0]))
            candidates["0x639_B3B4_BE"].append((t, struct.unpack_from(">H", d, 3)[0]))
            candidates["0x639_B3B4_LE"].append((t, struct.unpack_from("<H", d, 3)[0]))

        elif frame.arbitration_id == 0x592 and len(d) >= 2:
            candidates["0x592_B0B1_LE"].append((t, struct.unpack_from("<H", d, 0)[0]))
            candidates["0x592_B0B1_BE"].append((t, struct.unpack_from(">H", d, 0)[0]))

        elif frame.arbitration_id == 0x63A and len(d) >= 2:
            candidates["0x63A_B0B1_BE"].append((t, struct.unpack_from(">H", d, 0)[0]))
            candidates["0x63A_B0B1_LE"].append((t, struct.unpack_from("<H", d, 0)[0]))

    print(f"Charger samples: {len(charger_v)} voltage, {len(charger_i)} current")
    if charger_v:
        vs = [v for _, v in charger_v]
        print(f"Charger voltage range: {min(vs):.1f}V to {max(vs):.1f}V (mean {sum(vs)/len(vs):.1f}V)")
    if charger_i:
        cs = [c for _, c in charger_i]
        print(f"Charger current range: {min(cs):.2f}A to {max(cs):.2f}A (mean {sum(cs)/len(cs):.2f}A)")
    print()

    ref_v_ts = [t for t, _ in charger_v]
    ref_v_vals = [v for _, v in charger_v]
    ref_i_ts = [t for t, _ in charger_i]
    ref_i_vals = [v for _, v in charger_i]

    def correlate_against_ref(ref_ts, ref_vals, label, unit):
        print(f"=== {label} ===")
        hdr = f"{'Candidate':>25s}  {'Samples':>7s}  {'Raw Range':>18s}  {'Corr':>6s}  {'Scale':>12s}  {'Offset':>10s}  {'Implied':>12s}"
        print(hdr)
        print("-" * len(hdr))

        results = []
        for name, ts_vals in sorted(candidates.items()):
            if not ts_vals or len(ts_vals) < 10:
                continue
            raw_vals = [v for _, v in ts_vals]
            raw_min, raw_max = min(raw_vals), max(raw_vals)

            matched_ts, matched_raw = nearest_match(ref_ts, ts_vals)
            if len(matched_ts) < 10:
                continue

            # Get ref values at matched timestamps
            matched_ref = []
            ri = 0
            for mt in matched_ts:
                while ri < len(ref_ts) - 1 and abs(ref_ts[ri + 1] - mt) < abs(ref_ts[ri] - mt):
                    ri += 1
                matched_ref.append(ref_vals[ri])
                ri = max(0, ri - 1)

            r = pearson(matched_raw, matched_ref)
            if abs(r) > 0.3:
                scale, offset = linear_fit(matched_raw, matched_ref)
                mean_raw = sum(raw_vals) / len(raw_vals)
                implied = scale * mean_raw + offset
                results.append((abs(r), name, len(ts_vals), raw_min, raw_max, r, scale, offset, implied))

        results.sort(reverse=True)
        for _, name, n, rmin, rmax, r, scale, offset, implied in results:
            print(f"{name:>25s}  {n:>7d}  {rmin:>8d}-{rmax:>8d}  {r:>6.3f}  {scale:>12.8f}  {offset:>10.2f}  {implied:>10.1f}{unit}")
        print()

    correlate_against_ref(ref_v_ts, ref_v_vals, "VOLTAGE CANDIDATES vs Charger hvBatteryVoltage", "V")
    correlate_against_ref(ref_i_ts, ref_i_vals, "CURRENT CANDIDATES vs Charger hvBatteryCurrent", "A")


if __name__ == "__main__":
    main()
