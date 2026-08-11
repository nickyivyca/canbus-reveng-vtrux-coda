"""
bit_scan_climit2.py

Stricter bit scan on vtruxcurrentlimitingtest.log.

Rules (applied independently for CCL and DCL):
  1. Stable in baseline  -- dominant value covers >= STABLE_FRAC of baseline frames
  2. Flips during event  -- dominant value in event window DIFFERS from baseline dominant,
                           and covers >= STABLE_FRAC of event frames
  3. Recovers after event -- dominant value in recovery window MATCHES baseline dominant,
                            and covers >= STABLE_FRAC of recovery frames

CCL and DCL are completely separate candidate lists.
Recovery is REQUIRED for inclusion -- no recovery, no entry.

Windows:
  Baseline:     t=100-340s  (240s local driving, stable reference)
  CCL event:    t=348.6-365.6s  (17s regen limit, auto-detected from 0x050)
  CCL recovery: t=380-560s  (180s after CCL clears, before stop-sign approach)
  DCL event:    t=606-705s  (99s discharge limit)
  DCL recovery: t=800-1200s (400s well after DCL; vehicle hopefully returned to local)

Output groups candidates by message (arb_id), then byte, so clusters across bytes
of the same message (or across messages) are visible together.
"""

import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'logs', 'vtruxcurrentlimitingtest.log')

BASELINE     = (100.0,   340.0)
CCL_EVENT    = (348.6,   365.6)
CCL_RECOVERY = (380.0,   560.0)
DCL_EVENT    = (606.0,   705.0)
DCL_RECOVERY = (800.0,  1200.0)

STABLE_FRAC      = 0.85   # dominant value must cover this fraction for "stable"
MIN_EVENT_FRAMES = 8      # minimum frames in event window to consider

def dominant(vals):
    """Return (dominant_value, fraction). vals is a list of 0/1."""
    if not vals:
        return None, 0.0
    ones = sum(vals)
    zeros = len(vals) - ones
    if ones >= zeros:
        return 1, ones / len(vals)
    return 0, zeros / len(vals)

def main():
    print("Loading log...")
    frames = list(parse_file(LOG_PATH))
    if not frames:
        print("ERROR: no frames loaded")
        return

    t0 = frames[0].timestamp
    records = [(f.timestamp - t0, f.arbitration_id, bytes(f.data)) for f in frames]
    print(f"Loaded {len(records)} frames, t_span={records[-1][0]:.1f}s")

    windows = {
        'baseline':     BASELINE,
        'ccl_event':    CCL_EVENT,
        'ccl_recovery': CCL_RECOVERY,
        'dcl_event':    DCL_EVENT,
        'dcl_recovery': DCL_RECOVERY,
    }

    # Accumulate bit values per window
    # key = (arb_id, byte_idx, bit_idx)
    bit_data = defaultdict(lambda: {w: [] for w in windows})

    for (ts, arb_id, data) in records:
        for w_name, (w_start, w_end) in windows.items():
            if w_start <= ts <= w_end:
                for byte_idx, byte_val in enumerate(data):
                    for bit_idx in range(8):
                        bit_data[(arb_id, byte_idx, bit_idx)][w_name].append(
                            (byte_val >> bit_idx) & 1
                        )
                break

    print(f"Unique (ID, byte, bit) keys: {len(bit_data)}")

    ccl_candidates = []
    dcl_candidates = []

    for key, win_bits in bit_data.items():
        arb_id, byte_idx, bit_idx = key

        base_vals = win_bits['baseline']
        if len(base_vals) < MIN_EVENT_FRAMES:
            continue
        base_dom, base_frac = dominant(base_vals)
        if base_frac < STABLE_FRAC:
            continue

        def check_event(event_key, recovery_key):
            ev_vals  = win_bits[event_key]
            rec_vals = win_bits[recovery_key]
            if len(ev_vals) < MIN_EVENT_FRAMES or len(rec_vals) < MIN_EVENT_FRAMES:
                return None
            ev_dom,  ev_frac  = dominant(ev_vals)
            rec_dom, rec_frac = dominant(rec_vals)
            # must flip during event AND recover after
            if ev_dom != base_dom and ev_frac >= STABLE_FRAC:
                if rec_dom == base_dom and rec_frac >= STABLE_FRAC:
                    return {
                        'arb_id':    arb_id,
                        'byte_idx':  byte_idx,
                        'bit_idx':   bit_idx,
                        'base_dom':  base_dom,
                        'base_frac': base_frac,
                        'base_n':    len(base_vals),
                        'ev_dom':    ev_dom,
                        'ev_frac':   ev_frac,
                        'ev_n':      len(ev_vals),
                        'rec_dom':   rec_dom,
                        'rec_frac':  rec_frac,
                        'rec_n':     len(rec_vals),
                    }
            return None

        r_ccl = check_event('ccl_event', 'ccl_recovery')
        r_dcl = check_event('dcl_event', 'dcl_recovery')

        if r_ccl:
            ccl_candidates.append(r_ccl)
        if r_dcl:
            dcl_candidates.append(r_dcl)

    def fmt_id(arb_id):
        return f"0x{arb_id:08X}" if arb_id > 0x7FF else f"0x{arb_id:03X}"

    def fmt_rec(r, label):
        return (
            f"  {fmt_id(r['arb_id'])} B{r['byte_idx']} bit{r['bit_idx']}: "
            f"base={r['base_dom']} ({r['base_frac']:.0%} n={r['base_n']}) -> "
            f"{label}={r['ev_dom']} ({r['ev_frac']:.0%} n={r['ev_n']}) -> "
            f"recover={r['rec_dom']} ({r['rec_frac']:.0%} n={r['rec_n']})"
        )

    def group_by_id(candidates):
        from collections import OrderedDict
        grouped = defaultdict(list)
        for r in candidates:
            grouped[r['arb_id']].append(r)
        # sort by arb_id
        return sorted(grouped.items())

    out = []
    out.append("=" * 90)
    out.append("BIT SCAN v2 -- vtruxcurrentlimitingtest.log  (RECOVERY REQUIRED)")
    out.append(f"Baseline: t={BASELINE}  |  CCL: t={CCL_EVENT}  |  CCL-recovery: t={CCL_RECOVERY}")
    out.append(f"                        |  DCL: t={DCL_EVENT}  |  DCL-recovery: t={DCL_RECOVERY}")
    out.append(f"Stable frac: {STABLE_FRAC:.0%}  |  Min event frames: {MIN_EVENT_FRAMES}")
    out.append("=" * 90)

    out.append(f"\n--- CCL CANDIDATES ({len(ccl_candidates)} bits) ---")
    out.append(f"(stable baseline -> flips during CCL t={CCL_EVENT} -> recovers by t={CCL_RECOVERY})")
    for arb_id, recs in group_by_id(ccl_candidates):
        out.append(f"\n  [{fmt_id(arb_id)}]  {len(recs)} bit(s)")
        for r in sorted(recs, key=lambda x: (x['byte_idx'], x['bit_idx'])):
            out.append(fmt_rec(r, 'CCL'))

    out.append(f"\n--- DCL CANDIDATES ({len(dcl_candidates)} bits) ---")
    out.append(f"(stable baseline -> flips during DCL t={DCL_EVENT} -> recovers by t={DCL_RECOVERY})")
    for arb_id, recs in group_by_id(dcl_candidates):
        out.append(f"\n  [{fmt_id(arb_id)}]  {len(recs)} bit(s)")
        for r in sorted(recs, key=lambda x: (x['byte_idx'], x['bit_idx'])):
            out.append(fmt_rec(r, 'DCL'))

    out.append(f"\nTotal: {len(ccl_candidates)} CCL bits, {len(dcl_candidates)} DCL bits")

    output = "\n".join(out)
    print(output)

    out_path = os.path.join(os.path.dirname(__file__), 'bit_scan_climit2_output.txt')
    with open(out_path, 'w', encoding='ascii', errors='replace') as f:
        f.write(output)
    print(f"\nOutput written to: {out_path}")

if __name__ == '__main__':
    main()
