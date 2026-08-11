"""
Bit scan on vtruxcurrentlimitingtest.log

For every bit of every CAN ID, check:
  1. Stable (single dominant value) in baseline window (t=100-340s)
  2. Flips (changes dominant value) during CCL window (t=348-366s)
  3. Flips (changes dominant value) during DCL window (t=606-705s)
  4. Recovers (returns to baseline dominant value) after each event window

Reports candidates that are stable-outside and active-inside for CCL, DCL, or both.
"""

import sys
import os

# Add project root so canre can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file
from collections import defaultdict

LOG_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'logs', 'vtruxcurrentlimitingtest.log')

# Windows (t=s relative to log start)
BASELINE   = (100.0, 340.0)   # unrestricted, stable drive
CCL_EVENT  = (348.6, 365.6)   # regen limit active (auto-detected from 0x050)
CCL_AFTER  = (365.6, 450.0)   # after CCL event, before stop sign
DCL_EVENT  = (606.0, 705.0)   # discharge limit active
DCL_AFTER  = (705.0, 800.0)   # after DCL event (if log extends this far)

# Threshold: dominant value must cover >= this fraction of frames for "stable"
STABLE_FRAC = 0.85
# Threshold: event window dominant value must be DIFFERENT from baseline dominant value
# (if event window has <MIN_EVENT_FRAMES frames, skip)
MIN_EVENT_FRAMES = 10
# Recovery: after-window dominant value must match baseline dominant
# (if recovery window has fewer than this many frames, skip recovery check)
MIN_RECOVERY_FRAMES = 10

def get_timestamps_start(frames):
    """Return t0 (first frame timestamp in seconds)."""
    if not frames:
        return 0.0
    return frames[0].timestamp

def classify_frames(frames):
    """Return dict: arb_id -> {byte_idx -> {bit_idx -> list_of_values (0 or 1)}}
    indexed by timestamp.
    Returns also: list of (timestamp, arb_id, data_bytes)."""
    records = []
    for f in frames:
        records.append((f.timestamp, f.arbitration_id, f.data))
    return records

def window_slice(records, t_start, t_end):
    return [(ts, arb_id, data) for (ts, arb_id, data) in records if t_start <= ts <= t_end]

def dominant_bit_value(frames_for_bit):
    """frames_for_bit: list of (0 or 1). Return (dominant_val, fraction)."""
    if not frames_for_bit:
        return None, 0.0
    ones = sum(frames_for_bit)
    zeros = len(frames_for_bit) - ones
    if ones >= zeros:
        return 1, ones / len(frames_for_bit)
    else:
        return 0, zeros / len(frames_for_bit)

def main():
    print("Loading log...")
    frames = list(parse_file(LOG_PATH))
    if not frames:
        print("ERROR: no frames loaded")
        return

    t0 = frames[0].timestamp
    # Convert timestamps relative to log start
    records = [(f.timestamp - t0, f.arbitration_id, bytes(f.data)) for f in frames]

    print(f"Loaded {len(records)} frames, t_span={records[-1][0]:.1f}s")

    # Build per-(arb_id, byte_idx, bit_idx) timeseries in each window
    # Use a dict: key=(arb_id, byte_idx, bit_idx) -> {window_name: [bit_values]}
    windows = {
        'baseline':    BASELINE,
        'ccl_event':   CCL_EVENT,
        'ccl_after':   CCL_AFTER,
        'dcl_event':   DCL_EVENT,
        'dcl_after':   DCL_AFTER,
    }

    # Accumulate bit values per window
    bit_data = defaultdict(lambda: {w: [] for w in windows})

    for (ts, arb_id, data) in records:
        for w_name, (w_start, w_end) in windows.items():
            if w_start <= ts <= w_end:
                for byte_idx, byte_val in enumerate(data):
                    for bit_idx in range(8):
                        bit_val = (byte_val >> bit_idx) & 1
                        bit_data[(arb_id, byte_idx, bit_idx)][w_name].append(bit_val)
                break  # each frame only falls in one window (non-overlapping)

    print(f"Unique (ID, byte, bit) keys: {len(bit_data)}")

    candidates_ccl = []
    candidates_dcl = []
    candidates_both = []

    for key, win_bits in bit_data.items():
        arb_id, byte_idx, bit_idx = key

        # Baseline must be stable
        base_vals = win_bits['baseline']
        if len(base_vals) < MIN_EVENT_FRAMES:
            continue
        base_dom, base_frac = dominant_bit_value(base_vals)
        if base_frac < STABLE_FRAC:
            continue  # baseline not stable

        # --- CCL event check ---
        ccl_vals = win_bits['ccl_event']
        ccl_after_vals = win_bits['ccl_after']

        ccl_flips = False
        ccl_recovers = False
        ccl_event_dom = None
        ccl_event_frac = 0.0

        if len(ccl_vals) >= MIN_EVENT_FRAMES:
            ccl_event_dom, ccl_event_frac = dominant_bit_value(ccl_vals)
            if ccl_event_dom != base_dom and ccl_event_frac >= STABLE_FRAC:
                ccl_flips = True
                # Check recovery
                if len(ccl_after_vals) >= MIN_RECOVERY_FRAMES:
                    ccl_after_dom, ccl_after_frac = dominant_bit_value(ccl_after_vals)
                    if ccl_after_dom == base_dom and ccl_after_frac >= STABLE_FRAC:
                        ccl_recovers = True

        # --- DCL event check ---
        dcl_vals = win_bits['dcl_event']
        dcl_after_vals = win_bits['dcl_after']

        dcl_flips = False
        dcl_recovers = False
        dcl_event_dom = None
        dcl_event_frac = 0.0

        if len(dcl_vals) >= MIN_EVENT_FRAMES:
            dcl_event_dom, dcl_event_frac = dominant_bit_value(dcl_vals)
            if dcl_event_dom != base_dom and dcl_event_frac >= STABLE_FRAC:
                dcl_flips = True
                # Check recovery
                if len(dcl_after_vals) >= MIN_RECOVERY_FRAMES:
                    dcl_after_dom, dcl_after_frac = dominant_bit_value(dcl_after_vals)
                    if dcl_after_dom == base_dom and dcl_after_frac >= STABLE_FRAC:
                        dcl_recovers = True

        if ccl_flips or dcl_flips:
            rec = {
                'arb_id': arb_id,
                'byte_idx': byte_idx,
                'bit_idx': bit_idx,
                'base_dom': base_dom,
                'base_frac': base_frac,
                'base_n': len(base_vals),
                'ccl_flips': ccl_flips,
                'ccl_recovers': ccl_recovers,
                'ccl_event_dom': ccl_event_dom,
                'ccl_event_frac': ccl_event_frac,
                'ccl_n': len(ccl_vals),
                'dcl_flips': dcl_flips,
                'dcl_recovers': dcl_recovers,
                'dcl_event_dom': dcl_event_dom,
                'dcl_event_frac': dcl_event_frac,
                'dcl_n': len(dcl_vals),
            }
            if ccl_flips and dcl_flips:
                candidates_both.append(rec)
            elif ccl_flips:
                candidates_ccl.append(rec)
            elif dcl_flips:
                candidates_dcl.append(rec)

    def sort_key(r):
        # prefer recovered over not, then by arb_id
        return (-(r['ccl_recovers'] + r['dcl_recovers']), r['arb_id'], r['byte_idx'], r['bit_idx'])

    candidates_both.sort(key=sort_key)
    candidates_ccl.sort(key=sort_key)
    candidates_dcl.sort(key=sort_key)

    def fmt_rec(r):
        arb_id = r['arb_id']
        if arb_id > 0x7FF:
            id_str = f"0x{arb_id:08X}"
        else:
            id_str = f"0x{arb_id:03X}"
        return (
            f"  {id_str} B{r['byte_idx']} bit{r['bit_idx']}: "
            f"base={r['base_dom']} ({r['base_frac']:.0%}, n={r['base_n']}) | "
            f"CCL: flips={r['ccl_flips']}, dom={r['ccl_event_dom']} ({r['ccl_event_frac']:.0%}, n={r['ccl_n']}), "
            f"recovers={r['ccl_recovers']} | "
            f"DCL: flips={r['dcl_flips']}, dom={r['dcl_event_dom']} ({r['dcl_event_frac']:.0%}, n={r['dcl_n']}), "
            f"recovers={r['dcl_recovers']}"
        )

    out_lines = []
    out_lines.append("=" * 90)
    out_lines.append("BIT SCAN -- vtruxcurrentlimitingtest.log")
    out_lines.append(f"Baseline: t={BASELINE[0]}-{BASELINE[1]}s | CCL event: t={CCL_EVENT[0]}-{CCL_EVENT[1]}s | DCL event: t={DCL_EVENT[0]}-{DCL_EVENT[1]}s")
    out_lines.append(f"Stable frac threshold: {STABLE_FRAC:.0%} | Min event frames: {MIN_EVENT_FRAMES}")
    out_lines.append("=" * 90)

    out_lines.append(f"\n--- BOTH CCL and DCL ({len(candidates_both)} candidates) ---")
    for r in candidates_both:
        out_lines.append(fmt_rec(r))

    out_lines.append(f"\n--- CCL ONLY ({len(candidates_ccl)} candidates) ---")
    for r in candidates_ccl:
        out_lines.append(fmt_rec(r))

    out_lines.append(f"\n--- DCL ONLY ({len(candidates_dcl)} candidates) ---")
    for r in candidates_dcl:
        out_lines.append(fmt_rec(r))

    total = len(candidates_both) + len(candidates_ccl) + len(candidates_dcl)
    out_lines.append(f"\nTotal candidates: {total} ({len(candidates_both)} both, {len(candidates_ccl)} CCL-only, {len(candidates_dcl)} DCL-only)")

    output = "\n".join(out_lines)
    print(output)

    out_path = os.path.join(os.path.dirname(__file__), 'bit_scan_climit_output.txt')
    with open(out_path, 'w', encoding='ascii', errors='replace') as f:
        f.write(output)
    print(f"\nOutput written to: {out_path}")

if __name__ == '__main__':
    main()
