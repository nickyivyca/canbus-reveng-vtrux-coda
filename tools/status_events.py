"""Status event finder for CAN bus captures.

Extracts time-ordered state transitions for discrete status signals,
groups them into event clusters, and reports them.

Two modes:
  --auto (default)          Auto-discover candidate signals via bus survey
  --watch-profile NAME      Use a named vehicle-specific signal set

Usage:
    python tools/status_events.py <log> [options]
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from canre.parsers.autodetect import parse_file
from canre.utils.merge import merge_files
from canre.analysis.survey import run_survey
from collections import Counter, defaultdict
from pathlib import Path


def _load_frames(log_paths: list[str]) -> list:
    """Load frames from one or more log files.

    If multiple paths are given they are merged in order using merge_files,
    which handles _T{chunk} and _M{bus}_T{chunk} naming automatically.
    """
    paths = [Path(p) for p in log_paths]
    if len(paths) == 1:
        return list(parse_file(paths[0]))
    return list(merge_files(paths))


# ===================================================================
# VEHICLE-SPECIFIC CONFIGURATION
#
# Everything below this banner is vehicle/session specific.
# Add new profiles here when investigating a new vehicle or session.
# The rest of the file is the generic analysis engine.
# ===================================================================

# Watch profiles: manually curated signal sets per vehicle/session.
# Format: { (bus, id_hex): [byte_indices, ...] }
WATCH_PROFILES = {
    "coda-charging": {
        # B CAN (bus 3) - Charger system status
        (3, 0x617): [0, 4, 6],
        (3, 0x274): [0, 1, 2, 3, 4, 5],
        (3, 0x615): [0, 2, 6],
        # B CAN (bus 3) - Binary flag bytes
        (3, 0x410): [2, 6],
        (3, 0x439): [0],
        (3, 0x275): [6, 7],
        (3, 0x382): [0, 1, 4],
        (3, 0x390): [0, 1, 2, 3],
        (3, 0x620): [4],
        (3, 0x61B): [4],
        (3, 0x61A): [3],
        (3, 0x276): [0],
        # C CAN (bus 1) - vehicle/BMS state
        (1, 0x200): [1],
        (1, 0x680): [2],
    },
    # Add future profiles here, e.g.:
    # "vtrux-startup": { ... },
    # "coda-startup": { ... },
}

# Signal annotations: human-readable labels for known signals.
# Keyed by (bus, id, byte) for specific bytes, or (bus, id) for all bytes of an ID.
# Only used in --watch-profile mode.
SIGNAL_NOTES = {
    # --- Coda ---
    (3, 0x617, 0): "ChrgrSysSts B0 state code",
    (3, 0x617, 4): "ChrgrSysSts B4 flags",
    (3, 0x617, 6): "ChrgrSysSts B6 transient",
    (3, 0x274): "Fault",
    (3, 0x615): "SysLimits",
    (3, 0x410): "binary flag?",
    (3, 0x439): "binary",
    (3, 0x382): "BMS/charge",
    (3, 0x620, 4): "State counter B4",
    (3, 0x390): "BMS/thermal?",
    (3, 0x61B): "0x61B",
    (3, 0x276): "status",
    (3, 0x275): "0x275",
    (1, 0x200): "C CAN 0x200",
    (1, 0x680): "C CAN 0x680",
    # --- Vtrux ---
    # (add annotations here as signals are identified)
}


# ===================================================================
# GENERIC ANALYSIS ENGINE
#
# Everything below is vehicle-agnostic. No hard-coded IDs, buses,
# or signal assumptions.
# ===================================================================

def _get_note(bus, aid, bi):
    """Look up annotation for a signal (profile mode only)."""
    key3 = (bus, aid, bi)
    if key3 in SIGNAL_NOTES:
        return SIGNAL_NOTES[key3]
    key2 = (bus, aid)
    if key2 in SIGNAL_NOTES:
        return f"{SIGNAL_NOTES[key2]} B{bi}"
    return ""


def auto_discover(frames, bus_filter, include_bits):
    """Discover candidate signals from survey data.

    Returns (watch_dict, bit_only_dict) where:
      watch_dict:  {(bus, id): [byte_indices]} for byte-level tracking (unique_count 2-16)
      bit_only_dict: {(bus, id): [byte_indices]} for bit-only tracking (unique_count 17-256)
    """
    survey = run_survey(iter(frames), bus_filter=bus_filter)
    watch = {}
    bit_only = {}

    for label, info in survey["ids"].items():
        if info["is_extended"]:
            continue
        bus = info["bus"]
        aid = info["arbitration_id"]
        byte_info = info.get("bytes", {})

        byte_candidates = []
        bit_candidates = []

        for pos_str, bs in byte_info.items():
            if bs["min"] == bs["max"]:
                continue  # constant
            uc = bs["unique_count"]
            if uc <= 16:
                byte_candidates.append(int(pos_str))
            elif include_bits and uc <= 256:
                bit_candidates.append(int(pos_str))

        if byte_candidates:
            watch[(bus, aid)] = sorted(byte_candidates)
        if bit_candidates:
            bit_only[(bus, aid)] = sorted(bit_candidates)

    id_count = len(watch) + len(bit_only)
    byte_count = sum(len(v) for v in watch.values())
    print(f"  Auto-discovery: {id_count} IDs, {byte_count} byte-level candidates")
    if include_bits:
        bit_count = sum(len(v) for v in bit_only.values())
        print(f"  Bit-only candidates: {bit_count} bytes across {len(bit_only)} IDs")

    return watch, bit_only


def scan_transitions(frames, watch, bit_only, bus_filter, max_trans, include_bits):
    """Single-pass transition scan across all candidate signals.

    Returns:
      byte_trans:    [(rel_ts, bus, id, byte_idx, old, new), ...]
      bit_trans:     [(rel_ts, bus, id, byte_idx, bit_pos, old_bit, new_bit), ...]
      byte_counts:   Counter of (bus, id, byte_idx) -> total transitions
      bit_counts:    Counter of (bus, id, byte_idx, bit_pos) -> total transitions
      counter_bytes: set of (bus, id, byte_idx) identified as rolling counters
      byte_unique:   {(bus, id, byte_idx): set of observed values}
    """
    t0 = frames[0].timestamp

    last_val = {}
    byte_trans = []
    bit_trans = []
    byte_counts = Counter()
    bit_counts = Counter()

    # Counter detection accumulators
    inc_up = Counter()
    inc_down = Counter()

    byte_unique = defaultdict(set)

    # Build lookup: which frames/bytes to process
    all_watch = {}       # (bus, id) -> set of all byte indices to track
    byte_level = {}      # (bus, id) -> set of byte-level indices only
    for key, indices in watch.items():
        all_watch[key] = set(indices)
        byte_level[key] = set(indices)
    if include_bits:
        for key, indices in bit_only.items():
            existing = all_watch.get(key, set())
            all_watch[key] = existing | set(indices)

    for f in frames:
        bus = f.bus
        aid = f.arbitration_id
        prefix = (bus, aid)

        if prefix not in all_watch:
            continue
        if bus_filter is not None and bus != bus_filter:
            continue

        track_bytes = all_watch[prefix]
        is_byte = byte_level.get(prefix, set())
        data = f.data

        for bi in track_bytes:
            if bi >= len(data):
                continue
            val = data[bi]
            sk = (bus, aid, bi)
            byte_unique[sk].add(val)

            if sk not in last_val:
                last_val[sk] = val
                continue

            old = last_val[sk]
            if val == old:
                continue
            last_val[sk] = val

            # Counter detection
            if (val - old) & 0xFF == 1:
                inc_up[sk] += 1
            if (old - val) & 0xFF == 1:
                inc_down[sk] += 1

            # Byte-level transition
            if bi in is_byte:
                byte_counts[sk] += 1
                if byte_counts[sk] <= max_trans:
                    byte_trans.append((f.timestamp - t0, bus, aid, bi, old, val))

            # Bit-level transitions
            if include_bits:
                flipped = old ^ val
                for bit in range(8):
                    if flipped & (1 << (7 - bit)):
                        old_bit = (old >> (7 - bit)) & 1
                        new_bit = (val >> (7 - bit)) & 1
                        bk = (bus, aid, bi, bit)
                        bit_counts[bk] += 1
                        if bit_counts[bk] <= max_trans:
                            bit_trans.append((
                                f.timestamp - t0, bus, aid, bi, bit,
                                old_bit, new_bit,
                            ))

    # Identify counters: >80% sequential increments AND >4 unique values.
    # Binary/few-state signals (e.g. 0<->1) always look sequential but aren't counters.
    counter_bytes = set()
    for sk, count in byte_counts.items():
        if count > 0 and len(byte_unique[sk]) > 4:
            seq = inc_up[sk] + inc_down[sk]
            if seq / count > 0.80:
                counter_bytes.add(sk)

    return (byte_trans, bit_trans, byte_counts, bit_counts,
            counter_bytes, byte_unique)


def classify_signals(byte_counts, bit_counts, counter_bytes, max_trans,
                     byte_unique, include_bits):
    """Classify each signal as QUIET, NOISY, or COUNTER.

    Returns (quiet_bytes, quiet_bits, inventory_lines)
    """
    quiet_bytes = set()
    quiet_bits = set()
    inventory = []  # (count, label, tag)

    for key, count in sorted(byte_counts.items(), key=lambda x: x[1]):
        bus, aid, bi = key
        label = f"Bus{bus} 0x{aid:03X} B{bi}"
        if key in counter_bytes:
            tag = "COUNTER"
        elif count > max_trans:
            tag = "NOISY"
        else:
            tag = "QUIET"
            quiet_bytes.add(key)
        inventory.append((count, label, tag))

    if include_bits:
        # Suppress bit entries redundant with 2-value byte entries
        two_val_bytes = {k for k in quiet_bytes if len(byte_unique.get(k, set())) == 2}

        for bk, count in sorted(bit_counts.items(), key=lambda x: x[1]):
            bus, aid, bi, bit = bk
            byte_key = (bus, aid, bi)
            if byte_key in two_val_bytes:
                continue  # redundant with byte-level
            label = f"Bus{bus} 0x{aid:03X} B{bi}.bit{bit}"
            if byte_key in counter_bytes:
                tag = "COUNTER"
            elif count > max_trans:
                tag = "NOISY"
            else:
                tag = "QUIET"
                quiet_bits.add(bk)
            inventory.append((count, label, tag))

    inventory.sort(key=lambda x: x[0])
    return quiet_bytes, quiet_bits, inventory


def format_byte_line(ts, bus, aid, bi, old, new, show_notes):
    """Format one byte-level transition line."""
    sig = f"Bus{bus} 0x{aid:03X} B{bi}"
    note = _get_note(bus, aid, bi) if show_notes else ""
    note_str = f"  {note}" if note else ""
    return (f"{ts:8.2f}  {sig:<22s}  0x{old:02X} -> 0x{new:02X}"
            f"  [byte]{note_str}")


def format_bit_line(ts, bus, aid, bi, bit, old_bit, new_bit):
    """Format one bit-level transition line."""
    sig = f"Bus{bus} 0x{aid:03X} B{bi}.bit{bit}"
    return f"{ts:8.2f}  {sig:<22s}      {old_bit} -> {new_bit}      [bit]"


def build_report(byte_trans, bit_trans, quiet_bytes, quiet_bits,
                 inventory, args):
    """Build the full text report."""
    lines = []
    show_notes = args.watch_profile is not None

    # --- Section 1: Signal Inventory ---
    lines.append("=== SIGNAL INVENTORY ===")
    lines.append(f"{'Count':>6}  {'Signal':<24s}  Status")
    lines.append("-" * 45)
    for count, label, tag in inventory:
        lines.append(f"{count:>6}  {label:<24s}  {tag}")
    lines.append("")
    quiet_n = sum(1 for _, _, t in inventory if t == "QUIET")
    noisy_n = sum(1 for _, _, t in inventory if t == "NOISY")
    ctr_n = sum(1 for _, _, t in inventory if t == "COUNTER")
    lines.append(f"  {quiet_n} quiet, {noisy_n} noisy, {ctr_n} counters"
                 f"  (threshold: {args.max_transitions})")
    lines.append("")

    # Build merged list of quiet transitions
    merged = []
    for entry in byte_trans:
        ts, bus, aid, bi, old, new = entry
        if (bus, aid, bi) in quiet_bytes:
            merged.append(("byte", entry))
    for entry in bit_trans:
        ts, bus, aid, bi, bit, ob, nb = entry
        if (bus, aid, bi, bit) in quiet_bits:
            merged.append(("bit", entry))
    merged.sort(key=lambda x: x[1][0])

    if not merged:
        lines.append("No quiet-signal transitions found.")
        return "\n".join(lines)

    # --- Section 2: Event Clusters ---
    if args.gap > 0:
        clusters = []
        cur = [merged[0]]
        for i in range(1, len(merged)):
            if merged[i][1][0] - cur[-1][1][0] > args.gap:
                clusters.append(cur)
                cur = [merged[i]]
            else:
                cur.append(merged[i])
        clusters.append(cur)

        lines.append(f"=== EVENT CLUSTERS (gap={args.gap}s) ===")
        lines.append("")

        for ci, cluster in enumerate(clusters, 1):
            t_start = cluster[0][1][0]
            t_end = cluster[-1][1][0]
            n = len(cluster)
            sigs = set()
            for typ, entry in cluster:
                if typ == "byte":
                    sigs.add((entry[1], entry[2], entry[3]))
                else:
                    sigs.add((entry[1], entry[2], entry[3], entry[4]))
            iso = " (isolated)" if n == 1 else ""
            dur = f"{t_end - t_start:.2f}s" if t_end > t_start else "instant"
            lines.append(
                f"--- Cluster #{ci} at t={t_start:.2f}s - {t_end:.2f}s "
                f"({dur}, {n} transitions, {len(sigs)} signals){iso} ---"
            )
            for typ, entry in cluster:
                if typ == "byte":
                    ts, bus, aid, bi, old, new = entry
                    lines.append(format_byte_line(
                        ts, bus, aid, bi, old, new, show_notes))
                else:
                    ts, bus, aid, bi, bit, ob, nb = entry
                    lines.append(format_bit_line(
                        ts, bus, aid, bi, bit, ob, nb))
            lines.append("")

    # --- Section 3: Full Timeline ---
    lines.append(f"=== FULL TIMELINE ({len(merged)} transitions) ===")
    lines.append(f"{'Time(s)':>8}  {'Signal':<22s}  {'Old':>5}    {'New':<5}  Type")
    lines.append("-" * 60)
    for typ, entry in merged:
        if typ == "byte":
            ts, bus, aid, bi, old, new = entry
            lines.append(format_byte_line(
                ts, bus, aid, bi, old, new, show_notes))
        else:
            ts, bus, aid, bi, bit, ob, nb = entry
            lines.append(format_bit_line(ts, bus, aid, bi, bit, ob, nb))

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Status event finder for CAN bus captures"
    )
    parser.add_argument("log", nargs="+",
                        help="Log file(s). Pass multiple T-chunk files to merge "
                             "them into a single session at runtime.")
    parser.add_argument("--bus", type=int, default=None,
                        help="Filter to single bus number")
    parser.add_argument("--watch-profile", default=None,
                        choices=list(WATCH_PROFILES.keys()),
                        help="Use a named vehicle-specific signal set")
    parser.add_argument("--auto", action="store_true", default=False,
                        help="Auto-discover candidates (default when no profile)")
    parser.add_argument("--max-transitions", type=int, default=50,
                        help="Quiet-signal threshold (default: 50)")
    parser.add_argument("--gap", type=float, default=2.0,
                        help="Cluster gap in seconds (default: 2.0, 0=disable)")
    parser.add_argument("--bits", action="store_true", default=False,
                        help="Include bit-level transitions")
    parser.add_argument("--output", default=None,
                        help="Write report to file instead of stdout")
    args = parser.parse_args()

    # Default to auto-discovery if no profile specified
    use_auto = args.watch_profile is None or args.auto

    label = args.log[0] if len(args.log) == 1 else f"{len(args.log)} files"
    print(f"Parsing {label} ...")
    frames = _load_frames(args.log)
    print(f"  {len(frames):,} frames loaded")

    if not frames:
        print("No frames parsed.")
        return

    total_dur = frames[-1].timestamp - frames[0].timestamp
    print(f"  Duration: {total_dur:.1f}s")

    # --- Build candidate signal set ---
    if use_auto:
        print("  Mode: auto-discovery")
        watch, bit_only = auto_discover(frames, args.bus, args.bits)
    else:
        print(f"  Mode: watch profile '{args.watch_profile}'")
        watch = WATCH_PROFILES[args.watch_profile]
        bit_only = {}

    if not watch and not bit_only:
        print("No candidate signals found.")
        return

    # --- Scan transitions ---
    print("Scanning transitions ...")
    (byte_trans, bit_trans, byte_counts, bit_counts,
     counter_bytes, byte_unique) = scan_transitions(
        frames, watch, bit_only, args.bus,
        args.max_transitions, args.bits,
    )

    # --- Classify ---
    quiet_bytes, quiet_bits, inventory = classify_signals(
        byte_counts, bit_counts, counter_bytes,
        args.max_transitions, byte_unique, args.bits,
    )

    # --- Report ---
    report = build_report(
        byte_trans, bit_trans, quiet_bytes, quiet_bits,
        inventory, args,
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
        print(f"\nReport written to {args.output}")
    else:
        print()
        print(report)


if __name__ == "__main__":
    main()
