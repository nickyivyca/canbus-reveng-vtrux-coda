#!/usr/bin/env python3
"""
Count per-signal InfluxDB point volume for Vtrux logs, applying current exclusions.
Reports top contributors so we can identify good exclusion candidates.

Usage:
  py -3.12 projects/vtrux/notes/artifacts/influx_volume_analysis.py <log> [<log2> ...]
"""
import sys
import io
import re
import contextlib
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from canre.parsers import parse_file

try:
    import cantools
except ImportError:
    print("ERROR: pip install cantools", file=sys.stderr)
    sys.exit(1)

# ---- DBC paths ---------------------------------------------------------------
DBC_PATHS = [
    ROOT / "projects/vtrux/vtrux-powertrain.dbc",
    ROOT / "projects/vtrux/BelInverter.dbc",
    ROOT / "projects/vtrux/GMW8762_PPEI_GMLAN.dbc",
]

# ---- Bus anchors (same as influx_upload.py) ----------------------------------
BUS_ANCHORS = [
    ("powertrain", {0x051}),
    ("vehicle",    {0x1E5, 0x500}),
    ("obd",        {0x040, 0x041, 0x042, 0x043, 0x044}),
]

# ---- Current exclusions (can_id entries from influx_upload.py profile) -------
EXCLUDE_BUS_ID = {
    ("obd",     0x0C1), ("obd",     0x0C5), ("obd",     0x0F9),
    ("obd",     0x1C7), ("obd",     0x1E9), ("obd",     0x1F5),
    ("obd",     0x3E9), ("obd",     0x2F9), ("obd",     0x1CF),
    ("vehicle", 0x0C9), ("vehicle", 0x1C3), ("vehicle", 0x1C5),
    ("vehicle", 0x3C1), ("vehicle", 0x3F9), ("vehicle", 0x3FB),
    ("vehicle", 0x4D1),
}

# ---- Load DBCs ---------------------------------------------------------------
_EXTENDED_BIT = 0x80000000
_BO_RE = re.compile(r'^(BO_ )(\d+)( )', re.MULTILINE)

def fix_extended_ids(text):
    def _fix(m):
        raw_id = int(m.group(2))
        if raw_id > 0x7FF and not (raw_id & _EXTENDED_BIT):
            raw_id |= _EXTENDED_BIT
        return m.group(1) + str(raw_id) + m.group(3)
    return _BO_RE.sub(_fix, text)

databases = []
for path in DBC_PATHS:
    if not path.exists():
        print(f"Warning: DBC not found: {path}", file=sys.stderr)
        continue
    with open(path, encoding='utf-8', errors='replace') as f:
        text = f.read()
    text = fix_extended_ids(text)
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        db = cantools.database.load_string(text, database_format='dbc', strict=False)
    databases.append((path.name, db))

known_ids = set()
for _, db in databases:
    for msg in db.messages:
        known_ids.add(msg.frame_id)

print(f"Loaded {len(databases)} DBCs, {len(known_ids)} unique message IDs\n")

# ---- Identify buses from a quick scan ----------------------------------------
def identify_buses(log_path):
    channel_ids = defaultdict(set)
    for frame in parse_file(log_path):
        channel_ids[frame.bus].add(frame.arbitration_id)
    mapping = {}
    for ch, ids in channel_ids.items():
        for bus_name, anchors in BUS_ANCHORS:
            if ids & anchors:
                mapping[ch] = bus_name
                break
        else:
            mapping[ch] = f"ch{ch}"
    return mapping

# ---- Decode and count --------------------------------------------------------
def decode_frame(frame):
    signals = {}
    for _, db in databases:
        try:
            result = db.decode_message(frame.arbitration_id, frame.data, decode_choices=False)
            signals.update(result)
        except Exception:
            pass
    return signals

def analyze(log_path):
    print(f"Scanning {log_path.name} for bus IDs...")
    bus_map = identify_buses(log_path)
    for ch, name in sorted(bus_map.items()):
        print(f"  ch{ch} -> {name}")

    # counts[(bus, signal_name, can_id_hex)] = n_points
    counts = defaultdict(int)
    # msg_counts[(bus, can_id)] = n_frames (including excluded ones, for context)
    msg_counts = defaultdict(int)
    excluded_frames = defaultdict(int)
    total_frames = 0
    decoded_frames = 0

    print("Counting signal points...")
    for frame in parse_file(log_path):
        if frame.is_tx:
            continue
        total_frames += 1
        bus_name = bus_map.get(frame.bus, f"ch{frame.bus}")
        msg_counts[(bus_name, frame.arbitration_id)] += 1

        if frame.arbitration_id not in known_ids:
            continue
        if (bus_name, frame.arbitration_id) in EXCLUDE_BUS_ID:
            excluded_frames[(bus_name, frame.arbitration_id)] += 1
            continue

        signals = decode_frame(frame)
        if signals:
            decoded_frames += 1
            can_id_hex = f"0x{frame.arbitration_id:03X}"
            for sig_name, val in signals.items():
                if val is None:
                    continue
                counts[(bus_name, sig_name, can_id_hex)] += 1

    total_points = sum(counts.values())
    print(f"\n  {total_frames:,} total frames -> {total_points:,} signal points would be uploaded\n")

    # Sort by point count descending
    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)

    # Group by (bus, can_id) for a message-level summary
    msg_points = defaultdict(int)
    msg_signals = defaultdict(set)
    for (bus, sig, can_id), n in counts.items():
        msg_points[(bus, can_id)] += n
        msg_signals[(bus, can_id)].add(sig)

    msg_ranked = sorted(msg_points.items(), key=lambda x: x[1], reverse=True)

    print(f"{'Rank':<5} {'Points':>10} {'%Total':>7}  {'Bus':<12} {'CAN ID':<8}  Signals")
    print("-" * 90)
    cumulative = 0
    for rank, ((bus, can_id), pts) in enumerate(msg_ranked[:50], 1):
        cumulative += pts
        pct = pts * 100 / total_points if total_points else 0
        cum_pct = cumulative * 100 / total_points if total_points else 0
        n_sigs = len(msg_signals[(bus, can_id)])
        sig_preview = ", ".join(sorted(msg_signals[(bus, can_id)])[:4])
        if n_sigs > 4:
            sig_preview += f", ...+{n_sigs-4}"
        print(f"{rank:<5} {pts:>10,} {pct:>6.1f}%  {bus:<12} {can_id:<8}  {sig_preview}")
        if cum_pct >= 95:
            print(f"  ^ cumulative {cum_pct:.1f}% at rank {rank}")
            break

    print(f"\nTop 30 individual signals:")
    print(f"{'Rank':<5} {'Points':>10} {'%Total':>7}  {'Bus':<12} {'CAN ID':<8}  Signal")
    print("-" * 90)
    for rank, ((bus, sig, can_id), pts) in enumerate(ranked[:30], 1):
        pct = pts * 100 / total_points if total_points else 0
        print(f"{rank:<5} {pts:>10,} {pct:>6.1f}%  {bus:<12} {can_id:<8}  {sig}")

    print(f"\nExcluded messages (already filtered, shown for reference):")
    for (bus, can_id), n in sorted(excluded_frames.items(), key=lambda x: x[1], reverse=True):
        print(f"  {n:>10,}  {bus:<12} 0x{can_id:03X}")

    return total_points, msg_ranked

if __name__ == "__main__":
    log_paths = [Path(a) for a in sys.argv[1:]]
    if not log_paths:
        print("Usage: py -3.12 influx_volume_analysis.py <log> [<log2> ...]")
        sys.exit(1)
    for p in log_paths:
        if not p.exists():
            print(f"Not found: {p}", file=sys.stderr)
            continue
        analyze(p)
        print()
