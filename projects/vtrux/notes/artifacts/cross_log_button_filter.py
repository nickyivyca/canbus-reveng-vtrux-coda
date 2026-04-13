"""
cross_log_button_filter.py

Find ID/byte combinations that vary in the trailer poking log
but are completely static in a set of reference Vtrux logs.

These are strong candidates for button-press signals because
trailer brake buttons are not pressed in any other log.

Usage:
    py -3.12 projects/vtrux/notes/artifacts/cross_log_button_filter.py

Output:
    projects/vtrux/notes/artifacts/button_candidates.txt
"""

import sys
import os
from collections import defaultdict

# Add project root to path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, ROOT)

from canre.parsers import parse_file

LOGS_DIR = os.path.join(ROOT, 'projects', 'vtrux', 'logs')
OUT_FILE  = os.path.join(ROOT, 'projects', 'vtrux', 'notes', 'artifacts', 'button_candidates.txt')

POKING_LOG = os.path.join(LOGS_DIR, 'vtruxtrailerpokinglog.log')

# Diverse reference logs -- driving and stationary, no button presses
REFERENCE_LOGS = [
    ('oghighwaydrive',        os.path.join(LOGS_DIR, 'oghighwaydrive.log')),
    ('movingaroundindriveway', os.path.join(LOGS_DIR, 'movingaroundindriveway.log')),
    ('vtruxevapdrivelog4',     os.path.join(LOGS_DIR, 'vtruxevapdrivelog4.log')),
    ('debuglog_M0_T0',         os.path.join(LOGS_DIR, 'debuglog_M0_T0.log')),
    ('vtruxinterlocktest',     os.path.join(LOGS_DIR, 'vtruxinterlocktest.log')),
]

# Anchor IDs for Vehicle bus (HS-GMLAN Unfiltered)
GM_VEHICLE_ANCHORS = {0x1E5, 0x500}

def find_gm_bus(frames_by_bus):
    """Return bus number that contains Vehicle anchor IDs, or None."""
    for bus, ids in frames_by_bus.items():
        if ids & GM_VEHICLE_ANCHORS:
            return bus
    return None

def collect_byte_values(log_path, label):
    """
    Parse log, identify Vehicle bus by anchor IDs, then collect
    unique byte values for each (arb_id, byte_index) on that bus.

    Returns:
        dict: {(arb_id, byte_idx): set(values)}
        or None on error
    """
    print(f'  Parsing {label} ...', flush=True)
    # First pass: find which bus is Vehicle
    frames_by_bus = defaultdict(set)
    try:
        for frame in parse_file(log_path):
            frames_by_bus[frame.bus].add(frame.arbitration_id)
    except Exception as e:
        print(f'    ERROR reading {label}: {e}')
        return None

    gm_bus = find_gm_bus(frames_by_bus)
    if gm_bus is None:
        print(f'    WARNING: no Vehicle bus found in {label} (no anchor IDs 0x1E5/0x500)')
        return None
    print(f'    Vehicle bus = {gm_bus}')

    # Second pass: collect byte-level unique values on the GM bus
    byte_values = defaultdict(set)
    for frame in parse_file(log_path):
        if frame.bus != gm_bus:
            continue
        for i, b in enumerate(frame.data):
            byte_values[(frame.arbitration_id, i)].add(b)

    print(f'    {len(byte_values)} (arb_id, byte) combinations on GM bus')
    return byte_values


def main():
    lines = []

    print('=== Collecting poking log byte values ===', flush=True)
    poking_vals = collect_byte_values(POKING_LOG, 'vtruxtrailerpokinglog')
    if poking_vals is None:
        print('Failed to parse poking log -- aborting')
        return

    # Only care about bytes with 2+ unique values in the poking log
    active_in_poking = {k: v for k, v in poking_vals.items() if len(v) >= 2}
    print(f'\n{len(active_in_poking)} (arb_id, byte) combinations vary in poking log\n')

    print('=== Collecting reference log byte values ===', flush=True)
    ref_data = {}
    for label, path in REFERENCE_LOGS:
        vals = collect_byte_values(path, label)
        if vals is not None:
            ref_data[label] = vals
    print()

    # Categorize each active candidate
    # Category A: static (1 unique value) in every reference log where the ID appears
    # Category B: not present in any reference log at all (trailer-specific or poking-session-only)
    # Category C: varies in at least one reference log too (not button-specific)

    cat_a = []  # static in refs -- strong button candidates
    cat_b = []  # absent from refs -- possibly trailer-specific
    cat_c = []  # varies in refs -- skip

    for (arb_id, bidx), pvalues in sorted(active_in_poking.items()):
        ref_unique_counts = {}
        for ref_label, rvals in ref_data.items():
            key = (arb_id, bidx)
            if key in rvals:
                ref_unique_counts[ref_label] = len(rvals[key])

        if not ref_unique_counts:
            # Not seen in any reference log
            cat_b.append((arb_id, bidx, pvalues, ref_unique_counts))
        elif all(c == 1 for c in ref_unique_counts.values()):
            # Present in refs but always 1 unique value
            cat_a.append((arb_id, bidx, pvalues, ref_unique_counts))
        else:
            # Varies in at least one ref -- not button-specific
            cat_c.append((arb_id, bidx, pvalues, ref_unique_counts))

    # Build output
    lines.append('BUTTON CANDIDATE FILTER -- CROSS-LOG ANALYSIS')
    lines.append('=' * 60)
    lines.append(f'Poking log: vtruxtrailerpokinglog.log')
    lines.append(f'Reference logs: {", ".join(ref_data.keys())}')
    lines.append('')
    lines.append(f'Active in poking log (>=2 unique byte values on GM bus): {len(active_in_poking)}')
    lines.append(f'  Category A -- static in all refs (button candidates): {len(cat_a)}')
    lines.append(f'  Category B -- absent from all refs (trailer-specific?): {len(cat_b)}')
    lines.append(f'  Category C -- varies in refs (not button-specific): {len(cat_c)}')
    lines.append('')

    lines.append('=' * 60)
    lines.append('CATEGORY A -- STATIC IN ALL REFS (strongest candidates)')
    lines.append('Sorted by number of unique values in poking log (desc)')
    lines.append('-' * 60)
    cat_a_sorted = sorted(cat_a, key=lambda x: len(x[2]), reverse=True)
    for arb_id, bidx, pvalues, ref_counts in cat_a_sorted:
        pvals_hex = sorted(pvalues)
        pvals_str = ' '.join(f'{v:02X}' for v in pvals_hex)
        ref_str = ', '.join(f'{k}:{v}uniq' for k, v in sorted(ref_counts.items()))
        lines.append(f'  0x{arb_id:03X}  B{bidx}  poke={len(pvalues)}uniq [{pvals_str}]  refs=[{ref_str}]')
    lines.append('')

    lines.append('=' * 60)
    lines.append('CATEGORY B -- ABSENT FROM ALL REFS (possibly trailer-specific IDs)')
    lines.append('-' * 60)
    cat_b_sorted = sorted(cat_b, key=lambda x: (x[0], x[1]))
    for arb_id, bidx, pvalues, _ in cat_b_sorted:
        pvals_hex = sorted(pvalues)
        pvals_str = ' '.join(f'{v:02X}' for v in pvals_hex)
        lines.append(f'  0x{arb_id:03X}  B{bidx}  poke={len(pvalues)}uniq [{pvals_str}]  refs=[absent]')
    lines.append('')

    lines.append('=' * 60)
    lines.append('CATEGORY C -- VARIES IN REFS (filtered out, not button-specific)')
    lines.append('-' * 60)
    cat_c_sorted = sorted(cat_c, key=lambda x: (x[0], x[1]))
    for arb_id, bidx, pvalues, ref_counts in cat_c_sorted:
        pvals_hex = sorted(pvalues)
        pvals_str = ' '.join(f'{v:02X}' for v in pvals_hex)
        ref_str = ', '.join(f'{k}:{v}uniq' for k, v in sorted(ref_counts.items()))
        lines.append(f'  0x{arb_id:03X}  B{bidx}  poke={len(pvalues)}uniq [{pvals_str}]  refs=[{ref_str}]')

    output = '\n'.join(lines)
    print(output)

    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        f.write(output)
    print(f'\nWritten to {OUT_FILE}')


if __name__ == '__main__':
    main()
