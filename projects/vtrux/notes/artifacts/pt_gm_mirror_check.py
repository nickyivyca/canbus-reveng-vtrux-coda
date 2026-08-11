"""
pt_gm_mirror_check.py -- Test the theory that PT bus IDs in the ~0x470 cluster
are mirrored onto the OBD bus at PT_ID - 0x30 (the "GMLAN mirror cluster").

For every PT ID where (PT_ID - offset) exists on a GM bus, this script:
  1. Reports the candidate pair and frame counts.
  2. Pairs frames by nearest timestamp (within max_gap_s).
  3. Compares data bytes and reports match rate.

A true bridge: high match rate AND byte content is identical (or has a consistent
fixed transform per byte). A coincidence: near-zero match rate or random differences.

Also scans offsets 0x28..0x38 to find which offset (if any) produces the most hits,
as a sanity check that 0x30 is the right value.

Usage:
    py -3.12 pt_gm_mirror_check.py <log_file> [--max-gap-ms 150]
"""

import sys
import os
import bisect
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

OBD_ANCHORS = {0x040, 0x041, 0x042, 0x043, 0x044}
VEH_ANCHORS = {0x1E5, 0x500, 0x17D}
PT_ANCHORS  = {0x051}


def identify_buses(frames):
    bus_ids = defaultdict(set)
    for f in frames:
        bus_ids[f.bus].add(f.arbitration_id)
    roles = {}
    for bus, ids in bus_ids.items():
        if ids & OBD_ANCHORS:
            roles[bus] = 'OBD'
        elif ids & VEH_ANCHORS:
            roles[bus] = 'Vehicle'
        elif ids & PT_ANCHORS:
            roles[bus] = 'PT'
        else:
            roles[bus] = 'Unknown'
    return roles


def pair_and_compare(src_frames, tgt_frames, max_gap_s):
    """Pair src frames to nearest tgt frame; return (matches, total_paired, per_byte_mm)."""
    if not src_frames or not tgt_frames:
        return 0, 0, {}
    tgt_ts   = [t for t, _ in tgt_frames]
    tgt_data = [d for _, d in tgt_frames]
    matches = 0
    total   = 0
    per_byte = defaultdict(list)
    for src_ts, src_d in src_frames:
        idx = bisect.bisect_left(tgt_ts, src_ts)
        best_idx, best_gap = None, float('inf')
        for c in [idx - 1, idx]:
            if 0 <= c < len(tgt_ts):
                g = abs(tgt_ts[c] - src_ts)
                if g < best_gap:
                    best_gap, best_idx = g, c
        if best_gap > max_gap_s:
            continue
        total += 1
        tgt_d = tgt_data[best_idx]
        maxlen = max(len(src_d), len(tgt_d))
        ok = True
        for i in range(maxlen):
            sb = src_d[i] if i < len(src_d) else None
            tb = tgt_d[i] if i < len(tgt_d) else None
            if sb != tb:
                per_byte[i].append((sb, tb))
                ok = False
        if ok:
            matches += 1
    return matches, total, per_byte


def fmt(v):
    return f'0x{v:02X}' if v is not None else 'NA'


def summarise_byte_diffs(per_byte_mm, max_bytes=5):
    if not per_byte_mm:
        return '(identical)'
    parts = []
    for b in sorted(per_byte_mm.keys())[:max_bytes]:
        mms   = per_byte_mm[b]
        uniq  = sorted(set(mms), key=lambda x: (x[0] or 0, x[1] or 0))
        n     = len(mms)
        if len(uniq) == 1:
            s = f'{fmt(uniq[0][0])}->{fmt(uniq[0][1])} (always)'
        elif len(uniq) <= 3:
            s = ', '.join(f'{fmt(a)}->{fmt(b2)}' for a, b2 in uniq)
        else:
            s = f'{len(uniq)} unique pairs'
        parts.append(f'B{b}[{n}x: {s}]')
    extra = len(per_byte_mm) - max_bytes
    if extra > 0:
        parts.append(f'+{extra} more bytes')
    return '; '.join(parts)


def main():
    if len(sys.argv) < 2:
        print("Usage: pt_gm_mirror_check.py <log_file> [--max-gap-ms 150]")
        sys.exit(1)

    log_path = sys.argv[1]
    max_gap_ms = 150
    if '--max-gap-ms' in sys.argv:
        max_gap_ms = int(sys.argv[sys.argv.index('--max-gap-ms') + 1])
    max_gap_s = max_gap_ms / 1000.0

    print(f"Loading {os.path.basename(log_path)} ...")
    frames = list(parse_file(log_path))
    print(f"  {len(frames):,} frames total")

    bus_roles = identify_buses(frames)
    print("\nBus roles:")
    for bus, role in sorted(bus_roles.items()):
        n = len({f.arbitration_id for f in frames if f.bus == bus})
        print(f"  Bus {bus} = {role}  ({n} unique IDs)")

    pt_bus  = next((b for b, r in bus_roles.items() if r == 'PT'), None)
    obd_bus = next((b for b, r in bus_roles.items() if r == 'OBD'), None)
    veh_bus = next((b for b, r in bus_roles.items() if r == 'Vehicle'), None)

    if pt_bus is None or obd_bus is None:
        print("ERROR: Need PT and OBD buses.")
        sys.exit(1)

    print(f"\n  PT={pt_bus}, OBD={obd_bus}, Vehicle={veh_bus}, max_gap={max_gap_ms}ms\n")

    ts_data = defaultdict(list)
    for f in frames:
        ts_data[(f.bus, f.arbitration_id)].append((f.timestamp, bytes(f.data)))

    pt_ids  = sorted({aid for (bus, aid), v in ts_data.items() if bus == pt_bus  and v})
    obd_ids = sorted({aid for (bus, aid), v in ts_data.items() if bus == obd_bus and v})
    veh_ids = sorted({aid for (bus, aid), v in ts_data.items() if bus == veh_bus and v}) if veh_bus else []

    # --- Offset sweep: find which offset gives the most PT->GM ID matches ---
    print("=" * 70)
    print("OFFSET SWEEP (0x20..0x40): how many PT IDs have a GM counterpart?")
    print("=" * 70)
    gm_ids = set(obd_ids) | set(veh_ids)
    for off in range(0x20, 0x41):
        hits = [(pt, pt - off) for pt in pt_ids if (pt - off) in gm_ids and (pt - off) > 0]
        if hits:
            print(f"  offset=0x{off:02X} ({off:3d}): {len(hits):2d} pairs  {[f'0x{p:03X}->0x{g:03X}' for p, g in hits]}")

    # --- Primary analysis at offset 0x30 ---
    PRIMARY_OFFSET = 0x30
    print(f"\n\n{'=' * 90}")
    print(f"PRIMARY ANALYSIS: offset = 0x{PRIMARY_OFFSET:02X}")
    print(f"{'=' * 90}")

    candidates = [(pt, pt - PRIMARY_OFFSET)
                  for pt in pt_ids
                  if (pt - PRIMARY_OFFSET) > 0 and (pt - PRIMARY_OFFSET) in gm_ids]

    if not candidates:
        print("No candidate pairs found at this offset.")
    else:
        print(f"Found {len(candidates)} candidate pairs.\n")
        print(f"{'PT_ID':>7}  {'GM_ID':>7}  {'PT_fr':>7}  {'OBD_fr':>7}  {'Veh_fr':>7}  "
              f"{'Pairs':>6}  {'Match%':>7}  {'Verdict':16}  Byte diffs")
        print("-" * 130)

        for pt_id, gm_id in candidates:
            pt_ts   = ts_data[(pt_bus,  pt_id)]
            obd_ts  = ts_data.get((obd_bus, gm_id), [])
            veh_ts  = ts_data.get((veh_bus, gm_id), []) if veh_bus else []

            # Compare PT against OBD (primary, since 0x441-0x464 are OBD anchors)
            matches, total, per_byte_mm = pair_and_compare(pt_ts, obd_ts, max_gap_s)
            pct = 100.0 * matches / total if total else 0.0

            if   pct >= 95.0: verdict = 'BRIDGE_CONFIRMED'
            elif pct >= 70.0: verdict = 'LIKELY_BRIDGE'
            elif pct >= 30.0: verdict = 'PARTIAL'
            elif total == 0:  verdict = 'NO_PAIRS'
            else:             verdict = 'NO_MATCH'

            diff_str = summarise_byte_diffs(per_byte_mm)

            print(f"0x{pt_id:03X}    0x{gm_id:03X}  {len(pt_ts):>7,}  {len(obd_ts):>7,}  "
                  f"{len(veh_ts):>7,}  {total:>6,}  {pct:>6.1f}%  {verdict:16}  {diff_str}")

            # If OBD failed but Vehicle exists, try PT vs Vehicle too
            if pct < 30.0 and veh_ts:
                m2, t2, mm2 = pair_and_compare(pt_ts, veh_ts, max_gap_s)
                p2 = 100.0 * m2 / t2 if t2 else 0.0
                if p2 > pct:
                    d2 = summarise_byte_diffs(mm2)
                    print(f"         (vs Vehicle: {t2} pairs, {p2:.1f}% match  {d2})")

    print("\nDone.")


if __name__ == '__main__':
    main()
