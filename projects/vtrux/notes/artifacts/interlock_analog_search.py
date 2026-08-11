"""
Interlock Analog Search -- find gradual voltage decline signals on CAN bus.

Searches for an analog interlock circuit voltage signal that starts declining
BEFORE the fault bit fires. The interlock is a low-voltage loop (5V or 12V)
that drops gradually when a connector is pulled.

Known event timing:
  HVAC pull: first fault bit at t=63.23s (0x410 B0 bit4 drops)
  HVD pull:  first fault bit at t=240.75s (0x410 B0 bit4 drops)

Strategy:
  1. Single pass through the log, collecting every byte value and byte-pair
     value on Bus 2 standard frames in three time windows:
       - Baseline:  [45.0, 55.0]  (stable, well before any event)
       - Window 1:  [58.0, 68.0]  (around HVAC pull)
       - Window 2:  [236.0, 246.0] (around HVD pull)
  2. For each (ID, byte/pair), score based on:
       - Gradualness (many intermediate values)
       - Early onset (change precedes fault bit)
       - Response to BOTH events
  3. Output ranked candidates and timeseries of top hits.

Output files:
  interlock-analog-candidates.txt  -- Ranked table of top 30 candidates
  interlock-analog-top5.csv        -- Full-resolution timeseries of top 5
"""

import sys
import csv
import math
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]  # artifacts -> notes -> vtrux -> projects -> reverse-it
sys.path.insert(0, str(PROJECT_ROOT))

from canre.parsers.autodetect import parse_file

# -- Configuration ----------------------------------------------------------

LOG_PATH = PROJECT_ROOT / "projects" / "vtrux" / "logs" / "vtruxinterlocktest.log"
ARTIFACTS_DIR = SCRIPT_DIR

POWERTRAIN_BUS = 2

# Event timing (first fault bit fires)
FAULT_T1 = 63.23   # HVAC pull
FAULT_T2 = 240.75  # HVD pull

# Time windows for data collection
BASELINE_WINDOW = (45.0, 55.0)    # stable baseline
EVENT1_WINDOW   = (58.0, 68.0)    # around HVAC pull
EVENT2_WINDOW   = (236.0, 246.0)  # around HVD pull

# Known HV voltage signals to EXCLUDE from ranking (still collected for reference)
EXCLUDE_KEYS = {
    (0x482, "pair", 1, "LE"),   # POST_CONTACTOR HV voltage B1-B2
    (0x470, "pair", 1, "LE"),   # POST_CONTACTOR HV voltage B1-B2
    (0x440, "pair", 3, "LE"),   # POST_CONTACTOR HV voltage B3-B4
    (0x420, "pair", 0, "LE"),   # battery voltage (goes to zeros) B0-B1
    (0x420, "pair", 0, "BE"),   # battery voltage BE variant
    (0x412, "single", 0, None), # current (goes to zeros) B0
    (0x482, "pair", 0, "LE"),   # known HV mirror
    (0x470, "pair", 0, "LE"),   # known HV mirror
    (0x412, "pair", 0, "BE"),   # current pair
    (0x412, "pair", 4, "LE"),   # current pair
}

# Known counter IDs to exclude
COUNTER_IDS = {0x0AA}

# BMS cluster IDs to highlight
BMS_IDS = set(range(0x596, 0x64C))  # 0x596 through 0x64B
PRIORITY_IDS = {0x64A, 0x647, 0x648, 0x63D}


# -- Helpers ----------------------------------------------------------------

def in_window(t, window):
    return window[0] <= t <= window[1]


def compute_stats(values):
    """Return (mean, stdev, min_val, max_val, n_distinct) for a list of values."""
    if not values:
        return None, None, None, None, 0
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0, values[0], values[0], 1
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    stdev = math.sqrt(var)
    return mean, stdev, min(values), max(values), len(set(values))


def find_first_sustained_change(timeseries, direction_threshold=0, min_consecutive=3):
    """
    Find the first time of sustained change in a timeseries.

    timeseries: list of (t, value) sorted by time.
    Returns (first_change_time, direction) or (None, None).

    A sustained change = min_consecutive frames where each delta from
    the previous frame is non-zero and in the same direction.
    """
    if len(timeseries) < min_consecutive + 1:
        return None, None

    streak = 0
    streak_dir = 0
    streak_start_t = None

    for i in range(1, len(timeseries)):
        delta = timeseries[i][1] - timeseries[i - 1][1]
        if delta > direction_threshold:
            d = 1
        elif delta < -direction_threshold:
            d = -1
        else:
            streak = 0
            streak_dir = 0
            continue

        if d == streak_dir:
            streak += 1
        else:
            streak = 1
            streak_dir = d
            streak_start_t = timeseries[i - 1][0]

        if streak >= min_consecutive:
            return streak_start_t, streak_dir

    return None, None


def count_intermediate_values(timeseries, window):
    """
    Count distinct intermediate values in a window between the initial
    and final settled values.

    Returns (n_intermediate, start_val, end_val).
    """
    pts = [(t, v) for t, v in timeseries if in_window(t, window)]
    if len(pts) < 4:
        return 0, 0, 0

    # Start value: mean of first 10% of samples
    n_edge = max(3, len(pts) // 10)
    start_vals = [v for _, v in pts[:n_edge]]
    end_vals = [v for _, v in pts[-n_edge:]]
    start_val = sum(start_vals) / len(start_vals)
    end_val = sum(end_vals) / len(end_vals)

    if abs(end_val - start_val) < 1:
        return 0, start_val, end_val

    lo = min(start_val, end_val)
    hi = max(start_val, end_val)

    # Count distinct values strictly between start and end
    intermediate = set()
    for _, v in pts:
        if lo < v < hi:
            intermediate.add(v)

    return len(intermediate), start_val, end_val


def format_signal_label(arb_id, sig_type, byte_idx, endian):
    """Format a human-readable signal label."""
    if sig_type == "single":
        return f"0x{arb_id:03X} B{byte_idx}"
    else:
        return f"0x{arb_id:03X} B{byte_idx}-B{byte_idx + 1} {endian}"


def format_csv_label(arb_id, sig_type, byte_idx, endian):
    """Format a CSV-safe signal label (no spaces)."""
    if sig_type == "single":
        return f"0x{arb_id:03X}_B{byte_idx}"
    else:
        return f"0x{arb_id:03X}_B{byte_idx}B{byte_idx + 1}_{endian}"


# -- Main -------------------------------------------------------------------

def main():
    print("=" * 90)
    print("INTERLOCK ANALOG SEARCH")
    print("=" * 90)
    print(f"Log:             {LOG_PATH}")
    print(f"Powertrain bus:  {POWERTRAIN_BUS}")
    print(f"Fault time 1:    {FAULT_T1}s (HVAC pull)")
    print(f"Fault time 2:    {FAULT_T2}s (HVD pull)")
    print(f"Baseline window: {BASELINE_WINDOW}")
    print(f"Event 1 window:  {EVENT1_WINDOW}")
    print(f"Event 2 window:  {EVENT2_WINDOW}")
    print()

    # Storage: key = (arb_id, signal_type, byte_idx, endian_or_none)
    #   signal_type = "single" for single byte, "pair" for adjacent byte pair
    #   For single bytes: endian_or_none = None, value = byte value (0-255)
    #   For pairs: endian_or_none = "LE" or "BE", value = 16-bit unsigned
    #
    # Per key, collect:
    #   { "baseline": [(t, v), ...], "event1": [...], "event2": [...] }
    signals = defaultdict(lambda: {"baseline": [], "event1": [], "event2": []})

    # -- Single pass through the log ----------------------------------------

    print("Parsing log (single pass)...")
    frame_count = 0
    ids_seen = set()

    for frame in parse_file(str(LOG_PATH)):
        frame_count += 1
        if frame_count % 500000 == 0:
            print(f"  ... {frame_count:>10,} frames  (t={frame.timestamp:.1f}s)")

        # Only powertrain bus standard frames
        if frame.bus != POWERTRAIN_BUS or frame.is_extended:
            continue

        t = frame.timestamp
        arb_id = frame.arbitration_id
        data = frame.data
        ids_seen.add(arb_id)

        # Skip counters
        if arb_id in COUNTER_IDS:
            continue

        # Determine which window(s) this frame falls in
        windows_hit = []
        if in_window(t, BASELINE_WINDOW):
            windows_hit.append("baseline")
        if in_window(t, EVENT1_WINDOW):
            windows_hit.append("event1")
        if in_window(t, EVENT2_WINDOW):
            windows_hit.append("event2")

        if not windows_hit:
            continue

        # Collect single bytes
        for bi in range(len(data)):
            key = (arb_id, "single", bi, None)
            val = data[bi]
            for w in windows_hit:
                signals[key][w].append((t, val))

        # Collect adjacent byte pairs (LE and BE)
        for bi in range(len(data) - 1):
            b_lo = data[bi]
            b_hi = data[bi + 1]
            val_le = b_lo | (b_hi << 8)
            val_be = (b_lo << 8) | b_hi

            key_le = (arb_id, "pair", bi, "LE")
            key_be = (arb_id, "pair", bi, "BE")
            for w in windows_hit:
                signals[key_le][w].append((t, val_le))
                signals[key_be][w].append((t, val_be))

    print(f"Done. {frame_count:,} total frames parsed.")
    print(f"Unique standard-frame IDs on Bus {POWERTRAIN_BUS}: {len(ids_seen)}")
    print(f"Signal candidates collected: {len(signals)}")
    print()

    # -- Analyze each signal ------------------------------------------------

    print("Analyzing candidates...")
    candidates = []

    for key, windows in signals.items():
        arb_id, sig_type, byte_idx, endian = key

        bl = windows["baseline"]
        ev1 = windows["event1"]
        ev2 = windows["event2"]

        # Need data in all windows
        if len(bl) < 5 or len(ev1) < 5 or len(ev2) < 5:
            continue

        # Baseline stats
        bl_vals = [v for _, v in bl]
        bl_mean, bl_std, bl_min, bl_max, bl_distinct = compute_stats(bl_vals)

        # Skip if baseline is not stable (stdev >= 2)
        if bl_std is None or bl_std >= 2.0:
            continue

        # Skip if baseline is 0 or 255 for single byte (likely unused)
        if sig_type == "single" and bl_mean is not None:
            if bl_mean < 0.5 or bl_mean > 254.5:
                continue

        # Skip if baseline is 0 for pairs
        if sig_type == "pair" and bl_mean is not None and bl_mean < 0.5:
            continue

        # Event 1 analysis
        ev1_sorted = sorted(ev1, key=lambda x: x[0])
        n_inter_1, start1, end1 = count_intermediate_values(ev1_sorted, EVENT1_WINDOW)
        change_t1, change_dir1 = find_first_sustained_change(ev1_sorted)

        # Event 2 analysis
        ev2_sorted = sorted(ev2, key=lambda x: x[0])
        n_inter_2, start2, end2 = count_intermediate_values(ev2_sorted, EVENT2_WINDOW)
        change_t2, change_dir2 = find_first_sustained_change(ev2_sorted)

        # Must have SOME change in at least one event window
        ev1_range = abs(end1 - start1) if n_inter_1 > 0 else 0
        ev2_range = abs(end2 - start2) if n_inter_2 > 0 else 0

        if ev1_range < 1 and ev2_range < 1:
            continue

        # -- Scoring --------------------------------------------------------

        score = 0.0
        notes = []

        # Gradualness bonus: more intermediate values = more analog-looking
        grad1 = min(n_inter_1, 50)  # cap contribution
        grad2 = min(n_inter_2, 50)
        score += grad1 * 2.0 + grad2 * 2.0
        if n_inter_1 >= 10:
            notes.append(f"grad1={n_inter_1}")
        if n_inter_2 >= 10:
            notes.append(f"grad2={n_inter_2}")

        # Early onset bonus: change precedes fault bit
        precedes_1 = False
        if change_t1 is not None and change_t1 < FAULT_T1:
            precedes_1 = True
            lead_time = FAULT_T1 - change_t1
            score += 50.0 + lead_time * 5.0  # big bonus
            notes.append(f"EARLY1 by {lead_time:.2f}s")

        precedes_2 = False
        if change_t2 is not None and change_t2 < FAULT_T2:
            precedes_2 = True
            lead_time = FAULT_T2 - change_t2
            score += 50.0 + lead_time * 5.0
            notes.append(f"EARLY2 by {lead_time:.2f}s")

        # Responds to BOTH events
        responds_both = ev1_range >= 1 and ev2_range >= 1
        if responds_both:
            score += 30.0
            notes.append("BOTH_EVENTS")

        # Same direction in both events
        if change_dir1 is not None and change_dir2 is not None:
            if change_dir1 == change_dir2:
                score += 10.0
                notes.append("SAME_DIR")

        # Step function penalty: < 3 intermediate values
        if n_inter_1 < 3 and ev1_range >= 1:
            score -= 30.0
            notes.append("STEP1")
        if n_inter_2 < 3 and ev2_range >= 1:
            score -= 30.0
            notes.append("STEP2")

        # Baseline voltage plausibility: interlock is 5V or 12V
        # High HV range is implausible for interlock circuit
        if sig_type == "pair" and bl_mean is not None and bl_mean > 5000:
            score -= 20.0
            notes.append("HIGH_BASELINE")
        if sig_type == "single" and bl_mean is not None and bl_mean > 200:
            score -= 10.0
            notes.append("HIGH_BYTE")

        # BMS cluster bonus (we suspect interlock may be reported by BMS)
        if arb_id in BMS_IDS:
            score += 15.0
            notes.append("BMS")
        if arb_id in PRIORITY_IDS:
            score += 10.0
            notes.append("PRIORITY")

        # Check exclusion list
        is_excluded = key in EXCLUDE_KEYS
        if is_excluded:
            notes.append("EXCLUDED_HV")

        candidates.append({
            "key": key,
            "arb_id": arb_id,
            "sig_type": sig_type,
            "byte_idx": byte_idx,
            "endian": endian,
            "score": score,
            "bl_mean": bl_mean,
            "bl_std": bl_std,
            "bl_distinct": bl_distinct,
            "n_inter_1": n_inter_1,
            "n_inter_2": n_inter_2,
            "start1": start1,
            "end1": end1,
            "start2": start2,
            "end2": end2,
            "ev1_range": ev1_range,
            "ev2_range": ev2_range,
            "change_t1": change_t1,
            "change_dir1": change_dir1,
            "change_t2": change_t2,
            "change_dir2": change_dir2,
            "precedes_1": precedes_1,
            "precedes_2": precedes_2,
            "responds_both": responds_both,
            "is_excluded": is_excluded,
            "notes": notes,
            "ev1_ts": ev1_sorted,
            "ev2_ts": ev2_sorted,
            "bl_ts": sorted(bl, key=lambda x: x[0]),
        })

    print(f"Candidates with stable baseline and measurable change: {len(candidates)}")

    # Sort by score descending
    candidates.sort(key=lambda c: c["score"], reverse=True)

    # -- Output: Ranked table -----------------------------------------------

    out_path = ARTIFACTS_DIR / "interlock-analog-candidates.txt"
    with open(out_path, "w") as f:
        def p(line=""):
            print(line)
            f.write(line + "\n")

        p("=" * 120)
        p("INTERLOCK ANALOG SIGNAL SEARCH -- CANDIDATE RANKING")
        p("=" * 120)
        p(f"Log:             {LOG_PATH.name}")
        p(f"Powertrain bus:  {POWERTRAIN_BUS}")
        p(f"Fault T1:        {FAULT_T1}s (HVAC pull)")
        p(f"Fault T2:        {FAULT_T2}s (HVD pull)")
        p(f"Baseline window: {BASELINE_WINDOW}")
        p(f"Event 1 window:  {EVENT1_WINDOW}")
        p(f"Event 2 window:  {EVENT2_WINDOW}")
        p(f"Total candidates analyzed: {len(candidates)}")
        p()

        # -- Top 30 (excluding known HV signals) --
        p("=" * 120)
        p("TOP 30 CANDIDATES (excluding known HV voltage signals)")
        p("=" * 120)
        p()

        header = (
            f"{'Rank':>4}  {'Signal':<24} {'Score':>7}  "
            f"{'BL Mean':>8} {'BL Std':>7}  "
            f"{'E1 Range':>8} {'E1 Inter':>8} {'E1 Lead':>8}  "
            f"{'E2 Range':>8} {'E2 Inter':>8} {'E2 Lead':>8}  "
            f"Notes"
        )
        p(header)
        p("-" * 140)

        rank = 0
        for c in candidates:
            if c["is_excluded"]:
                continue
            rank += 1
            if rank > 30:
                break

            label = format_signal_label(c["arb_id"], c["sig_type"],
                                        c["byte_idx"], c["endian"])

            lead1 = ""
            if c["change_t1"] is not None:
                dt = FAULT_T1 - c["change_t1"]
                lead1 = f"{dt:+.2f}s"

            lead2 = ""
            if c["change_t2"] is not None:
                dt = FAULT_T2 - c["change_t2"]
                lead2 = f"{dt:+.2f}s"

            notes_str = ", ".join(c["notes"])

            line = (
                f"{rank:4d}  {label:<24} {c['score']:7.1f}  "
                f"{c['bl_mean']:8.1f} {c['bl_std']:7.2f}  "
                f"{c['ev1_range']:8.1f} {c['n_inter_1']:8d} {lead1:>8s}  "
                f"{c['ev2_range']:8.1f} {c['n_inter_2']:8d} {lead2:>8s}  "
                f"{notes_str}"
            )
            p(line)

        # -- Also show excluded signals for reference --
        p()
        p("=" * 120)
        p("EXCLUDED SIGNALS (known HV / current -- shown for reference)")
        p("=" * 120)
        p()
        p(header)
        p("-" * 140)

        for c in candidates:
            if not c["is_excluded"]:
                continue

            label = format_signal_label(c["arb_id"], c["sig_type"],
                                        c["byte_idx"], c["endian"])

            lead1 = ""
            if c["change_t1"] is not None:
                dt = FAULT_T1 - c["change_t1"]
                lead1 = f"{dt:+.2f}s"

            lead2 = ""
            if c["change_t2"] is not None:
                dt = FAULT_T2 - c["change_t2"]
                lead2 = f"{dt:+.2f}s"

            notes_str = ", ".join(c["notes"])

            line = (
                f" REF  {label:<24} {c['score']:7.1f}  "
                f"{c['bl_mean']:8.1f} {c['bl_std']:7.2f}  "
                f"{c['ev1_range']:8.1f} {c['n_inter_1']:8d} {lead1:>8s}  "
                f"{c['ev2_range']:8.1f} {c['n_inter_2']:8d} {lead2:>8s}  "
                f"{notes_str}"
            )
            p(line)

        # -- Detail section for top 10 --
        p()
        p("=" * 120)
        p("DETAILED PROFILES -- TOP 10 CANDIDATES")
        p("=" * 120)

        rank = 0
        for c in candidates:
            if c["is_excluded"]:
                continue
            rank += 1
            if rank > 10:
                break

            label = format_signal_label(c["arb_id"], c["sig_type"],
                                        c["byte_idx"], c["endian"])

            p()
            p(f"--- #{rank}: {label} (score={c['score']:.1f}) ---")
            p(f"  Baseline:    mean={c['bl_mean']:.2f}  std={c['bl_std']:.3f}  "
              f"distinct_values={c['bl_distinct']}")
            p(f"  Event 1:     range={c['ev1_range']:.1f}  "
              f"start={c['start1']:.1f} -> end={c['end1']:.1f}  "
              f"intermediate_values={c['n_inter_1']}")
            if c["change_t1"] is not None:
                dir_str = "DOWN" if c["change_dir1"] == -1 else "UP"
                pre_str = "  ** PRECEDES FAULT **" if c["precedes_1"] else ""
                p(f"               first_change_at={c['change_t1']:.3f}s  "
                  f"dir={dir_str}{pre_str}")
            else:
                p("               no sustained change detected")
            p(f"  Event 2:     range={c['ev2_range']:.1f}  "
              f"start={c['start2']:.1f} -> end={c['end2']:.1f}  "
              f"intermediate_values={c['n_inter_2']}")
            if c["change_t2"] is not None:
                dir_str = "DOWN" if c["change_dir2"] == -1 else "UP"
                pre_str = "  ** PRECEDES FAULT **" if c["precedes_2"] else ""
                p(f"               first_change_at={c['change_t2']:.3f}s  "
                  f"dir={dir_str}{pre_str}")
            else:
                p("               no sustained change detected")

            # Show first/last few samples of event 1 timeseries
            ev1 = c["ev1_ts"]
            if len(ev1) > 0:
                p("  Event 1 samples (first 8):")
                for t, v in ev1[:8]:
                    p(f"    t={t:.3f}  val={v}")
                if len(ev1) > 16:
                    p(f"    ... ({len(ev1)} total samples)")
                    p("  Event 1 samples (last 8):")
                    for t, v in ev1[-8:]:
                        p(f"    t={t:.3f}  val={v}")

            ev2 = c["ev2_ts"]
            if len(ev2) > 0:
                p("  Event 2 samples (first 8):")
                for t, v in ev2[:8]:
                    p(f"    t={t:.3f}  val={v}")
                if len(ev2) > 16:
                    p(f"    ... ({len(ev2)} total samples)")
                    p("  Event 2 samples (last 8):")
                    for t, v in ev2[-8:]:
                        p(f"    t={t:.3f}  val={v}")

            p(f"  Notes: {', '.join(c['notes'])}")

    print(f"\nRanked candidates saved to: {out_path}")

    # -- Output: Top 5 timeseries CSV ---------------------------------------

    csv_path = ARTIFACTS_DIR / "interlock-analog-top5.csv"

    # Collect top 5 non-excluded candidates
    top5 = []
    for c in candidates:
        if c["is_excluded"]:
            continue
        top5.append(c)
        if len(top5) >= 5:
            break

    if not top5:
        print("No qualifying candidates for CSV output.")
        return

    # Build labels
    top5_labels = []
    for c in top5:
        top5_labels.append(format_csv_label(c["arb_id"], c["sig_type"],
                                            c["byte_idx"], c["endian"]))

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Header: window, timestamp, then one column per signal
        writer.writerow(["window", "timestamp"] + top5_labels)

        # For each candidate, merge baseline + event1 + event2 timeseries.
        # Collect all (window, t, signal_idx, value) tuples, then for each
        # unique (window, t) emit a row.
        rows = defaultdict(lambda: {})  # (window_name, t_rounded) -> {sig_idx: val}

        window_names = ["baseline", "event1", "event2"]
        ts_keys = ["bl_ts", "ev1_ts", "ev2_ts"]

        for sig_idx, c in enumerate(top5):
            for wname, tsk in zip(window_names, ts_keys):
                for t, v in c[tsk]:
                    # Round to 1ms for alignment
                    t_key = round(t, 3)
                    rows[(wname, t_key)][sig_idx] = v

        # Sort and write
        sorted_keys = sorted(rows.keys(), key=lambda x: (
            window_names.index(x[0]), x[1]
        ))

        for wname, t_key in sorted_keys:
            row = [wname, f"{t_key:.3f}"]
            vals = rows[(wname, t_key)]
            for sig_idx in range(len(top5)):
                if sig_idx in vals:
                    row.append(f"{vals[sig_idx]}")
                else:
                    row.append("")
            writer.writerow(row)

    print(f"Top 5 timeseries CSV saved to: {csv_path}")
    print()
    print("Done.")


if __name__ == "__main__":
    main()
