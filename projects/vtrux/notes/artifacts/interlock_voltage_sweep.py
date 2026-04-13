"""
Single-pass interlock test voltage sweep.

Reads vtruxinterlocktest.log once. For each candidate (id, byte_pair, endian),
extracts timeseries. Uses DCDC HV input as the reference to auto-detect HV
disconnection/reconnection events, then classifies each candidate by its
step response behavior.

Classification categories:
  POST_CONTACTOR  - drops on HVAC pull AND HVD pull; does NOT recover after HVD reconnect
  PRE_CONTACTOR   - survives HVAC pull; drops on HVD pull; recovers after HVD reconnect
  HV_RELATED      - responds to some but not all events (partial match)
  NON_VOLTAGE     - no significant response to HV events
  CURRENT         - inverts during events (goes to 0 from nonzero, but wrong sign/shape)

Also runs a broad sweep of all standard-frame byte pairs on the powertrain bus.
"""

import sys
import os
import struct
import csv
from collections import defaultdict
from pathlib import Path

# Add project root to path for canre imports
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]  # artifacts -> notes -> vtrux -> projects -> root
sys.path.insert(0, str(PROJECT_ROOT))

from canre.parsers.autodetect import parse_file

# ── Configuration ──────────────────────────────────────────────────────────

LOG_PATH = PROJECT_ROOT / "projects" / "vtrux" / "logs" / "vtruxinterlocktest.log"
ARTIFACTS_DIR = SCRIPT_DIR  # same as script location (artifacts/)

# Bus number for powertrain (from Phase 0 survey)
POWERTRAIN_BUS = 2

# DCDC reference signal
DCDC_ID = 0x18FFD6B3
DCDC_BYTES = (4, 5)
DCDC_SCALE = 0.05  # LE signed int16 * 0.05 = Volts

# Event windows derived from Phase 1 DCDC timeline analysis:
#   t~5.7s:   Key on, contactors close -> ~387V
#   t~63s:    HVAC pull -> contactor open -> slow decay
#   t~175-211s: 12V disconnect gap (no logging)
#   t~211s:   Fault cleared, key on -> ~387V
#   t~241s:   HVD pull -> slow decay
#   t~315s:   End of log, ~3.8V (never recovers)

# Windows for measuring signal level (before/after each event)
WINDOWS = {
    "hv_live_1":       (15, 55),     # stable HV before HVAC pull
    "post_hvac_pull":  (100, 170),   # after HVAC pull, caps discharged, HVD still in
    "hv_live_2":       (215, 235),   # stable HV after fault clear
    "post_hvd_pull":   (270, 310),   # after HVD pull, caps discharged
}

# Thresholds
VOLTAGE_PLAUSIBLE_MIN = 100   # raw value range that could be HV voltage
STEP_RATIO_THRESHOLD = 0.50   # >50% drop = significant step response
BROAD_SWEEP_MIN_FRAMES = 100  # minimum frames to include in broad sweep

# ── Candidate definitions ──────────────────────────────────────────────────

# Each candidate: (label, arb_id, byte_start, byte_count, endian, signed, scale)
# endian: 'le' or 'be'
CANDIDATES = [
    # Known / confirmed
    ("DCDC_B4B5",       0x18FFD6B3, 4, 2, 'le', True,  0.05),

    # Strong drive-log candidates (GMLAN mirror)
    ("0x482_B0B1_LE",   0x482, 0, 2, 'le', False, 1),
    ("0x470_B0B1_LE",   0x470, 0, 2, 'le', False, 1),

    # Charge-log candidates
    ("0x505_B0B1_LE",   0x505, 0, 2, 'le', False, 1),
    ("0x646_B4B5_LE",   0x646, 4, 2, 'le', False, 1),
    ("0x649_B0B1_BE",   0x649, 0, 2, 'be', False, 1),
    ("0x411_B0B1_BE",   0x411, 0, 2, 'be', False, 1),
    ("0x410_B2B3_LE",   0x410, 2, 2, 'le', False, 1),
    ("0x440_B1B2_LE",   0x440, 1, 2, 'le', False, 1),

    # Previously rejected — re-examine for pre/post classification
    ("0x420_B0B1_BE",   0x420, 0, 2, 'be', False, 1),
    ("0x480_B1B2_BE",   0x480, 1, 2, 'be', False, 1),
    ("0x595_B0B1_BE",   0x595, 0, 2, 'be', False, 1),
    ("0x644_B2B3_LE",   0x644, 2, 2, 'le', False, 1),
    ("0x63A_B0B1_LE",   0x63A, 0, 2, 'le', False, 1),
    ("0x600_B5B6_LE",   0x600, 5, 2, 'le', False, 1),

    # Negative-r / current candidates (should NOT classify as voltage)
    ("0x412_B4B5_LE",   0x412, 4, 2, 'le', False, 1),
    ("0x597_B1B2_LE",   0x597, 1, 2, 'le', False, 1),
    ("0x597_B1B2_BE",   0x597, 1, 2, 'be', False, 1),
    ("0x598_B0B1_BE",   0x598, 0, 2, 'be', False, 1),

    # BMS cluster — hunt for pre-contactor pack voltage
    ("0x639_B0B1_LE",   0x639, 0, 2, 'le', False, 1),
    ("0x639_B0B1_BE",   0x639, 0, 2, 'be', False, 1),
    ("0x639_B2B3_LE",   0x639, 2, 2, 'le', False, 1),
    ("0x639_B2B3_BE",   0x639, 2, 2, 'be', False, 1),
    ("0x639_B5B6_LE",   0x639, 5, 2, 'le', False, 1),
    ("0x640_B2B3_LE",   0x640, 2, 2, 'le', False, 1),
    ("0x640_B2B3_BE",   0x640, 2, 2, 'be', False, 1),
    ("0x640_B4B5_LE",   0x640, 4, 2, 'le', False, 1),
    ("0x640_B4B5_BE",   0x640, 4, 2, 'be', False, 1),
    ("0x596_B0B1_LE",   0x596, 0, 2, 'le', False, 1),
    ("0x596_B2B3_LE",   0x596, 2, 2, 'le', False, 1),
    ("0x63D_B0B1_LE",   0x63D, 0, 2, 'le', False, 1),
    ("0x63D_B0B1_BE",   0x63D, 0, 2, 'be', False, 1),
]


# ── Helpers ────────────────────────────────────────────────────────────────

def extract_u16(data, byte_start, endian):
    """Extract unsigned 16-bit value from data bytes."""
    if len(data) < byte_start + 2:
        return None
    b0 = data[byte_start]
    b1 = data[byte_start + 1]
    if endian == 'le':
        return b0 | (b1 << 8)
    else:
        return (b0 << 8) | b1


def extract_s16(data, byte_start, endian):
    """Extract signed 16-bit value from data bytes."""
    val = extract_u16(data, byte_start, endian)
    if val is None:
        return None
    if val >= 0x8000:
        val -= 0x10000
    return val


def mean_in_window(timeseries, t_start, t_end):
    """Compute mean value of (timestamp, value) pairs within a time window."""
    vals = [v for t, v in timeseries if t_start <= t <= t_end]
    if not vals:
        return None
    return sum(vals) / len(vals)


def count_in_window(timeseries, t_start, t_end):
    """Count samples within a time window."""
    return sum(1 for t, v in timeseries if t_start <= t <= t_end)


def classify_candidate(means):
    """
    Classify a candidate based on its mean values in the four windows.

    means = {window_name: mean_value_or_None}

    Logic:
      hv_live_1:      Baseline voltage when truck is on, HV live
      post_hvac_pull:  After HVAC pull (contactors open, HVD still in)
      hv_live_2:      Second baseline after fault clear
      post_hvd_pull:   After HVD pull (everything disconnected)

    POST_CONTACTOR:  high in live windows, low after HVAC pull AND HVD pull
    PRE_CONTACTOR:   high in live windows, STILL HIGH after HVAC pull, low after HVD pull
    """
    live1 = means.get("hv_live_1")
    post_hvac = means.get("post_hvac_pull")
    live2 = means.get("hv_live_2")
    post_hvd = means.get("post_hvd_pull")

    # Need at least the key windows
    if live1 is None or post_hvac is None or post_hvd is None:
        return "INSUFFICIENT_DATA", ""

    # Check if signal has meaningful values during HV live
    if live1 == 0:
        return "NO_SIGNAL", ""

    # Compute drop ratios
    hvac_drop_ratio = 1 - (post_hvac / live1) if live1 != 0 else 0
    hvd_drop_ratio = 1 - (post_hvd / live1) if live1 != 0 else 0

    # Recovery check: if live2 is available, check it recovered
    recovered = True
    if live2 is not None:
        recovery_ratio = live2 / live1 if live1 != 0 else 0
        recovered = recovery_ratio > 0.7

    detail = f"hvac_drop={hvac_drop_ratio:+.2f} hvd_drop={hvd_drop_ratio:+.2f}"

    # POST_CONTACTOR: drops on both HVAC and HVD
    if hvac_drop_ratio > STEP_RATIO_THRESHOLD and hvd_drop_ratio > STEP_RATIO_THRESHOLD:
        return "POST_CONTACTOR", detail

    # PRE_CONTACTOR: survives HVAC pull, drops on HVD pull
    if hvac_drop_ratio < 0.20 and hvd_drop_ratio > STEP_RATIO_THRESHOLD:
        return "PRE_CONTACTOR", detail

    # HV_RELATED: partial response
    if hvac_drop_ratio > 0.20 or hvd_drop_ratio > 0.20:
        return "HV_RELATED", detail

    return "NON_VOLTAGE", detail


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print(f"Interlock Voltage Sweep")
    print(f"Log: {LOG_PATH}")
    print(f"Powertrain bus: {POWERTRAIN_BUS}")
    print()

    # Build lookup: which IDs to collect for specific candidates
    candidate_ids = set()
    for label, arb_id, *_ in CANDIDATES:
        candidate_ids.add(arb_id)

    # Storage for candidate timeseries: label -> [(t, raw_value)]
    candidate_ts = defaultdict(list)

    # Broad sweep storage: (bus, arb_id) -> {byte_idx: [(t, byte_val)]}
    # We only collect for powertrain bus standard frames
    broad_data = defaultdict(lambda: defaultdict(list))
    broad_frame_counts = defaultdict(int)

    # Single pass through the log
    print("Parsing log (single pass)...")
    frame_count = 0
    downsample_counter = defaultdict(int)

    for frame in parse_file(str(LOG_PATH)):
        frame_count += 1
        if frame_count % 500000 == 0:
            print(f"  ...{frame_count:,} frames processed (t={frame.timestamp:.1f}s)")

        arb_id = frame.arbitration_id
        data = frame.data
        t = frame.timestamp

        # ── Specific candidate extraction ──
        if arb_id in candidate_ids:
            for label, cand_id, byte_start, byte_count, endian, signed, scale in CANDIDATES:
                if cand_id != arb_id:
                    continue
                if len(data) < byte_start + byte_count:
                    continue

                if signed:
                    raw = extract_s16(data, byte_start, endian)
                else:
                    raw = extract_u16(data, byte_start, endian)
                if raw is None:
                    continue

                candidate_ts[label].append((t, raw * scale))

        # ── Broad sweep: collect all powertrain bus standard frames ──
        if frame.bus == POWERTRAIN_BUS and not frame.is_extended:
            broad_frame_counts[arb_id] += 1
            # Downsample broad sweep to every 10th frame per ID
            downsample_counter[arb_id] += 1
            if downsample_counter[arb_id] % 10 == 0:
                for bi in range(len(data)):
                    broad_data[arb_id][bi].append((t, data[bi]))

    print(f"Done. {frame_count:,} total frames.")
    print(f"Specific candidates collected: {len(candidate_ts)}")
    print(f"Broad sweep IDs: {len(broad_data)} (powertrain bus, standard frame)")
    print()

    # ── Classify specific candidates ───────────────────────────────────────

    print("=" * 100)
    print("SPECIFIC CANDIDATE CLASSIFICATION")
    print("=" * 100)
    print()
    print(f"{'Label':<22} {'Class':<16} {'N':>6}  {'Live1':>9}  {'PostHVAC':>9}  "
          f"{'Live2':>9}  {'PostHVD':>9}  {'Detail'}")
    print("-" * 110)

    results = []
    for label, arb_id, byte_start, byte_count, endian, signed, scale in CANDIDATES:
        ts = candidate_ts.get(label, [])
        n = len(ts)

        means = {}
        for wname, (t0, t1) in WINDOWS.items():
            means[wname] = mean_in_window(ts, t0, t1)

        classification, detail = classify_candidate(means)

        def fmt_v(v):
            return f"{v:9.1f}" if v is not None else "     N/A"

        print(f"{label:<22} {classification:<16} {n:6}  "
              f"{fmt_v(means.get('hv_live_1'))}  {fmt_v(means.get('post_hvac_pull'))}  "
              f"{fmt_v(means.get('hv_live_2'))}  {fmt_v(means.get('post_hvd_pull'))}  "
              f"{detail}")

        results.append((label, arb_id, classification, n, means, detail))

    # ── Broad sweep classification ─────────────────────────────────────────

    print()
    print("=" * 100)
    print("BROAD SWEEP — ALL POWERTRAIN BUS BYTE PAIRS WITH STEP RESPONSE")
    print("=" * 100)
    print()

    broad_hits = []

    for arb_id in sorted(broad_data.keys()):
        if broad_frame_counts[arb_id] < BROAD_SWEEP_MIN_FRAMES:
            continue

        byte_indices = sorted(broad_data[arb_id].keys())

        # Check adjacent byte pairs
        for bi in byte_indices:
            if bi + 1 not in broad_data[arb_id]:
                continue

            # Construct 16-bit values (both LE and BE) from single-byte timeseries
            lo_ts = broad_data[arb_id][bi]
            hi_ts = broad_data[arb_id][bi + 1]

            # Align by index (both are downsampled identically per ID)
            n_samples = min(len(lo_ts), len(hi_ts))
            if n_samples < 10:
                continue

            for endian_label, combine in [("LE", lambda lo, hi: lo | (hi << 8)),
                                           ("BE", lambda lo, hi: (lo << 8) | hi)]:
                ts_16 = [(lo_ts[i][0], combine(lo_ts[i][1], hi_ts[i][1]))
                         for i in range(n_samples)]

                means = {}
                for wname, (t0, t1) in WINDOWS.items():
                    means[wname] = mean_in_window(ts_16, t0, t1)

                classification, detail = classify_candidate(means)

                if classification in ("POST_CONTACTOR", "PRE_CONTACTOR", "HV_RELATED"):
                    label = f"0x{arb_id:03X}_B{bi}B{bi+1}_{endian_label}"
                    # Skip if it's already in the specific candidate list
                    already_known = any(c[0] == label for c in results)
                    broad_hits.append((label, arb_id, classification, n_samples,
                                       means, detail, already_known))

    # Print broad sweep results, known candidates first then new discoveries
    known_hits = [h for h in broad_hits if h[6]]
    new_hits = [h for h in broad_hits if not h[6]]

    print(f"Total byte pairs with step response: {len(broad_hits)} "
          f"({len(known_hits)} already in candidate list, {len(new_hits)} NEW)")
    print()

    if new_hits:
        print(f"{'Label':<22} {'Class':<16} {'N':>6}  {'Live1':>9}  {'PostHVAC':>9}  "
              f"{'Live2':>9}  {'PostHVD':>9}  {'Detail'}")
        print("-" * 110)
        for label, arb_id, classification, n, means, detail, _ in sorted(
                new_hits, key=lambda x: x[2]):
            def fmt_v(v):
                return f"{v:9.1f}" if v is not None else "     N/A"
            print(f"{label:<22} {classification:<16} {n:6}  "
                  f"{fmt_v(means.get('hv_live_1'))}  {fmt_v(means.get('post_hvac_pull'))}  "
                  f"{fmt_v(means.get('hv_live_2'))}  {fmt_v(means.get('post_hvd_pull'))}  "
                  f"{detail}")
    else:
        print("No new discoveries beyond the specific candidate list.")

    # ── Save candidate timeseries to CSV ───────────────────────────────────

    csv_path = ARTIFACTS_DIR / "interlock-candidate-timeseries.csv"
    # Downsample to ~1 Hz for the CSV
    with open(csv_path, 'w', newline='') as f:
        # Collect all unique timestamps at ~1s resolution
        all_labels = [r[0] for r in results]
        writer = csv.writer(f)
        writer.writerow(["timestamp"] + all_labels)

        # Build per-label lookup at 1s bins
        binned = defaultdict(dict)  # {time_bin: {label: value}}
        for label in all_labels:
            for t, v in candidate_ts.get(label, []):
                time_bin = round(t)
                binned[time_bin][label] = v

        for time_bin in sorted(binned.keys()):
            row = [time_bin]
            for label in all_labels:
                row.append(f"{binned[time_bin].get(label, '')}")
            writer.writerow(row)

    print(f"\nTimeseries CSV saved to: {csv_path}")

    # ── Save classification report ─────────────────────────────────────────

    report_path = ARTIFACTS_DIR / "interlock-voltage-classification.txt"
    with open(report_path, 'w') as f:
        f.write("Interlock Voltage Sweep Classification Report\n")
        f.write(f"Log: {LOG_PATH.name}\n")
        f.write(f"Total frames: {frame_count:,}\n")
        f.write(f"\nEvent Windows:\n")
        for wname, (t0, t1) in WINDOWS.items():
            f.write(f"  {wname}: {t0}-{t1}s\n")

        f.write(f"\n{'='*100}\n")
        f.write("SPECIFIC CANDIDATES\n")
        f.write(f"{'='*100}\n\n")
        f.write(f"{'Label':<22} {'Class':<16} {'N':>6}  "
                f"{'Live1':>9}  {'PostHVAC':>9}  {'Live2':>9}  {'PostHVD':>9}\n")
        f.write("-" * 95 + "\n")

        for label, arb_id, classification, n, means, detail in results:
            def fmt_v(v):
                return f"{v:9.1f}" if v is not None else "     N/A"
            f.write(f"{label:<22} {classification:<16} {n:6}  "
                    f"{fmt_v(means.get('hv_live_1'))}  {fmt_v(means.get('post_hvac_pull'))}  "
                    f"{fmt_v(means.get('hv_live_2'))}  {fmt_v(means.get('post_hvd_pull'))}\n")

        if new_hits:
            f.write(f"\n{'='*100}\n")
            f.write(f"NEW DISCOVERIES (BROAD SWEEP)\n")
            f.write(f"{'='*100}\n\n")
            f.write(f"{'Label':<22} {'Class':<16} {'N':>6}  "
                    f"{'Live1':>9}  {'PostHVAC':>9}  {'Live2':>9}  {'PostHVD':>9}\n")
            f.write("-" * 95 + "\n")
            for label, arb_id, classification, n, means, detail, _ in sorted(
                    new_hits, key=lambda x: x[2]):
                def fmt_v(v):
                    return f"{v:9.1f}" if v is not None else "     N/A"
                f.write(f"{label:<22} {classification:<16} {n:6}  "
                        f"{fmt_v(means.get('hv_live_1'))}  {fmt_v(means.get('post_hvac_pull'))}  "
                        f"{fmt_v(means.get('hv_live_2'))}  {fmt_v(means.get('post_hvd_pull'))}\n")

    print(f"Classification report saved to: {report_path}")


if __name__ == "__main__":
    main()
