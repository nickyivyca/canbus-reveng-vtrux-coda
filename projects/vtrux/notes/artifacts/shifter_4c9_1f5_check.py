"""
Check 0x4C9 and 0x1F5 frame activity during the shifter disconnect window
to determine if messages were actively broadcast or just stale last-known values.

Disconnect window: t=20.3-29.5s (from investigation notes)
"""
import sys
sys.path.insert(0, ".")
from canre.parsers import parse_file
from collections import defaultdict

LOG = "projects/vtrux/logs/vtrux_shifter_disconnect.log"

DISC_START = 20.3
DISC_END   = 29.5

frames = list(parse_file(LOG))
t0 = frames[0].timestamp

# Identify buses
ids_by_bus = defaultdict(set)
for f in frames[:5000]:
    ids_by_bus[f.bus].add(f.arbitration_id)

veh = obd = None
for bus, ids in ids_by_bus.items():
    if 0x1E5 in ids or 0x500 in ids:
        veh = bus
    if 0x041 in ids or (0x040 in ids and 0x441 in ids):
        obd = bus

print(f"Bus IDs: VEH={veh}  OBD={obd}")
print(f"Disconnect window: t={DISC_START}-{DISC_END}s")
print(f"Log duration: {frames[-1].timestamp - t0:.1f}s  total frames: {len(frames)}")
print()

windows = [
    ("before",  0,           DISC_START),
    ("DISCONNECT", DISC_START, DISC_END),
    ("after",   DISC_END,    9999),
]

for arb_id, bus_id, label in [(0x4C9, veh, "0x4C9 (VEH)"), (0x1F5, veh, "0x1F5 (VEH)")]:
    print(f"--- {label} ---")
    for win_label, t_start, t_end in windows:
        wframes = [f for f in frames
                   if f.arbitration_id == arb_id and f.bus == bus_id
                   and t_start <= (f.timestamp - t0) < t_end]
        dur = min(t_end, frames[-1].timestamp - t0) - t_start
        rate = len(wframes) / dur if dur > 0 else 0
        print(f"  {win_label:12s}: {len(wframes):5d} frames  ({rate:.1f} Hz)")
        if arb_id == 0x4C9 and wframes:
            unique_data = set(bytes(f.data).hex() for f in wframes)
            print(f"               unique payloads: {unique_data}")
    print()
