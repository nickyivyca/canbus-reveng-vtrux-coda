"""
Cross-validate interlock test classifications against driving log correlation.

For each signal classified as POST_CONTACTOR or PRE_CONTACTOR by the interlock
sweep, compute Pearson r against the DCDC HV input reference in a driving log.

Signals that are truly post-contactor voltage should track DCDC tightly (r > 0.90).
"""

import sys
import struct
import math
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from canre.parsers.autodetect import parse_file

# ── Configuration ──────────────────────────────────────────────────────────

DRIVE_LOG = PROJECT_ROOT / "projects" / "vtrux" / "logs" / "debuglog_M0_T2_short.log"
ARTIFACTS_DIR = SCRIPT_DIR

# DCDC reference
DCDC_ID = 0x18FFD6B3
DCDC_BYTES = (4, 5)
DCDC_SCALE = 0.05

# Signals to validate — from interlock sweep results
# (label, arb_id, byte_start, byte_count, endian, signed)
SIGNALS = [
    # Specific candidates — POST_CONTACTOR
    ("0x482_B0B1_LE",   0x482, 0, 2, 'le', False),
    ("0x470_B0B1_LE",   0x470, 0, 2, 'le', False),
    ("0x420_B0B1_BE",   0x420, 0, 2, 'be', False),

    # Broad sweep POST_CONTACTOR — interesting new IDs
    ("0x050_B2B3_LE",   0x050, 2, 2, 'le', False),
    ("0x053_B0B1_LE",   0x053, 0, 2, 'le', False),
    ("0x412_B0B1_BE",   0x412, 0, 2, 'be', False),
    ("0x440_B3B4_LE",   0x440, 3, 2, 'le', False),
    ("0x460_B5B6_LE",   0x460, 5, 2, 'le', False),
    ("0x471_B1B2_LE",   0x471, 1, 2, 'le', False),
    ("0x507_B5B6_LE",   0x507, 5, 2, 'le', False),

    # Integer-volt encodings discovered
    ("0x482_B1B2_LE",   0x482, 1, 2, 'le', False),
    ("0x470_B1B2_LE",   0x470, 1, 2, 'le', False),

    # Broad sweep POST_CONTACTOR — additional byte pairs from 0x410
    ("0x410_B0B1_BE",   0x410, 0, 2, 'be', False),

    # PRE_CONTACTOR from broad sweep
    ("0x053_B4B5_LE",   0x053, 4, 2, 'le', False),
    ("0x619_B5B6_LE",   0x619, 5, 2, 'le', False),
    ("0x63A_B0B1_BE",   0x63A, 0, 2, 'be', False),
    ("0x64A_B1B2_LE",   0x64A, 1, 2, 'le', False),

    # Broad sweep HV_RELATED worth checking
    ("0x440_B4B5_LE",   0x440, 4, 2, 'le', False),
    ("0x470_B4B5_LE",   0x470, 4, 2, 'le', False),
    ("0x592_B3B4_LE",   0x592, 3, 2, 'le', False),
    ("0x646_B6B7_LE",   0x646, 6, 2, 'le', False),

    # NON_VOLTAGE from interlock that had high charge-log r — confirm they DON'T correlate
    ("0x505_B0B1_LE",   0x505, 0, 2, 'le', False),
    ("0x646_B4B5_LE",   0x646, 4, 2, 'le', False),
    ("0x649_B0B1_BE",   0x649, 0, 2, 'be', False),
]


def extract_u16(data, byte_start, endian):
    if len(data) < byte_start + 2:
        return None
    b0 = data[byte_start]
    b1 = data[byte_start + 1]
    return (b0 | (b1 << 8)) if endian == 'le' else ((b0 << 8) | b1)


def extract_s16(data, byte_start, endian):
    val = extract_u16(data, byte_start, endian)
    if val is None:
        return None
    return val - 0x10000 if val >= 0x8000 else val


def pearson_r(xs, ys):
    """Pearson correlation between two equal-length sequences."""
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = math.sqrt(sum((x - mx)**2 for x in xs) / n)
    sy = math.sqrt(sum((y - my)**2 for y in ys) / n)
    if sx == 0 or sy == 0:
        return None
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / n
    return cov / (sx * sy)


def linear_fit(xs, ys):
    """Returns (slope, intercept) for y = slope*x + intercept."""
    n = len(xs)
    if n < 2:
        return None, None
    mx = sum(xs) / n
    my = sum(ys) / n
    ss_xx = sum((x - mx)**2 for x in xs)
    if ss_xx == 0:
        return None, None
    ss_xy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    slope = ss_xy / ss_xx
    intercept = my - slope * mx
    return slope, intercept


def main():
    print(f"Cross-Validation: Interlock -> Driving Log")
    print(f"Drive log: {DRIVE_LOG.name}")
    print()

    # Collect IDs we need
    signal_ids = set()
    for label, arb_id, *_ in SIGNALS:
        signal_ids.add(arb_id)
    signal_ids.add(DCDC_ID)

    # Single pass through drive log
    dcdc_ts = []  # (t, volts)
    signal_ts = defaultdict(list)  # label -> [(t, raw)]

    print("Parsing drive log...")
    frame_count = 0
    for frame in parse_file(str(DRIVE_LOG)):
        frame_count += 1
        arb_id = frame.arbitration_id
        data = frame.data
        t = frame.timestamp

        # DCDC reference
        if arb_id == DCDC_ID and len(data) >= 6:
            raw = extract_s16(data, DCDC_BYTES[0], 'le')
            if raw is not None:
                dcdc_ts.append((t, raw * DCDC_SCALE))

        # Candidate signals
        if arb_id in signal_ids:
            for label, sig_id, byte_start, byte_count, endian, signed in SIGNALS:
                if sig_id != arb_id:
                    continue
                if signed:
                    raw = extract_s16(data, byte_start, endian)
                else:
                    raw = extract_u16(data, byte_start, endian)
                if raw is not None:
                    signal_ts[label].append((t, raw))

    print(f"Done. {frame_count:,} frames. DCDC samples: {len(dcdc_ts)}")
    if not dcdc_ts:
        print("ERROR: No DCDC reference found in drive log!")
        return

    dcdc_min = min(v for _, v in dcdc_ts)
    dcdc_max = max(v for _, v in dcdc_ts)
    print(f"DCDC voltage range: {dcdc_min:.1f}V – {dcdc_max:.1f}V "
          f"({dcdc_max - dcdc_min:.1f}V spread)")
    print()

    # Build DCDC lookup for nearest-match pairing
    dcdc_sorted = sorted(dcdc_ts, key=lambda x: x[0])

    def find_nearest_dcdc(t, max_dt=0.2):
        """Binary search for nearest DCDC sample within max_dt."""
        lo, hi = 0, len(dcdc_sorted) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if dcdc_sorted[mid][0] < t:
                lo = mid + 1
            else:
                hi = mid
        best_idx = lo
        if best_idx > 0 and abs(dcdc_sorted[best_idx-1][0] - t) < abs(dcdc_sorted[best_idx][0] - t):
            best_idx -= 1
        if abs(dcdc_sorted[best_idx][0] - t) <= max_dt:
            return dcdc_sorted[best_idx][1]
        return None

    # Correlate each signal against DCDC
    print(f"{'Label':<22} {'N':>6} {'r':>7}  {'Slope':>10}  {'Offset':>10}  "
          f"{'Raw@387V':>10}  {'Raw Range':>15}  {'Interlock'}")
    print("=" * 110)

    for label, arb_id, byte_start, byte_count, endian, signed in SIGNALS:
        ts = signal_ts.get(label, [])
        if not ts:
            print(f"{label:<22} {'N/A':>6}  -- signal not present in drive log --")
            continue

        # Pair with DCDC
        paired_dcdc = []
        paired_sig = []
        for t, raw in ts:
            dcdc_v = find_nearest_dcdc(t)
            if dcdc_v is not None:
                paired_dcdc.append(dcdc_v)
                paired_sig.append(raw)

        n = len(paired_dcdc)
        if n < 5:
            print(f"{label:<22} {n:6}  -- too few paired samples --")
            continue

        r = pearson_r(paired_dcdc, paired_sig)
        slope, intercept = linear_fit(paired_dcdc, paired_sig)

        raw_min = min(v for v in paired_sig)
        raw_max = max(v for v in paired_sig)

        # Implied raw value at 387V
        raw_at_387 = slope * 387 + intercept if slope is not None else None

        r_str = f"{r:+.4f}" if r is not None else "   N/A"
        slope_str = f"{slope:.4f}" if slope is not None else "N/A"
        offset_str = f"{intercept:.1f}" if intercept is not None else "N/A"
        raw387_str = f"{raw_at_387:.1f}" if raw_at_387 is not None else "N/A"

        print(f"{label:<22} {n:6} {r_str}  {slope_str:>10}  {offset_str:>10}  "
              f"{raw387_str:>10}  {raw_min:>6}-{raw_max:<6}")

    # Save report
    report_path = ARTIFACTS_DIR / "interlock-drive-correlation.txt"
    with open(report_path, 'w') as f:
        f.write(f"Cross-Validation: Interlock Classifications vs Drive Log Correlation\n")
        f.write(f"Drive log: {DRIVE_LOG.name}\n")
        f.write(f"DCDC range: {dcdc_min:.1f}-{dcdc_max:.1f}V\n\n")

        f.write(f"{'Label':<22} {'N':>6} {'r':>7}  {'Slope':>10}  {'Offset':>10}\n")
        f.write("-" * 60 + "\n")

        for label, arb_id, byte_start, byte_count, endian, signed in SIGNALS:
            ts = signal_ts.get(label, [])
            if not ts:
                f.write(f"{label:<22}  N/A\n")
                continue

            paired_dcdc = []
            paired_sig = []
            for t, raw in ts:
                dcdc_v = find_nearest_dcdc(t)
                if dcdc_v is not None:
                    paired_dcdc.append(dcdc_v)
                    paired_sig.append(raw)

            n = len(paired_dcdc)
            if n < 5:
                f.write(f"{label:<22} {n:6}  insufficient\n")
                continue

            r = pearson_r(paired_dcdc, paired_sig)
            slope, intercept = linear_fit(paired_dcdc, paired_sig)
            r_str = f"{r:+.4f}" if r is not None else "N/A"
            slope_str = f"{slope:.4f}" if slope is not None else "N/A"
            offset_str = f"{intercept:.1f}" if intercept is not None else "N/A"
            f.write(f"{label:<22} {n:6} {r_str}  {slope_str:>10}  {offset_str:>10}\n")

    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    main()
