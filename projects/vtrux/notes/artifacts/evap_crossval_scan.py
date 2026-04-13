"""
Cross-validation of Phase 2C cluster scan candidates against first evap drive.

Checks each remaining candidate signal in vtruxevapdrivelog4part2.log.
Evap completion in that log: t~12.07s (B3 rises 4->11), engine off t~16.7s.

For each candidate: print all transitions in the full log, highlighting the
evap window (t=8-20s). A true evap signal should show a clean, SUSTAINED
transition at evap completion that does NOT appear at the M mode events
(engine on at ~90s, off at ~145.5s).
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from canre.parsers import parse_file

LOG = "projects/vtrux/logs/vtruxevapdrivelog4part2.log"
OUT = "projects/vtrux/notes/artifacts/evap_crossval_results.txt"

# Candidates: (msg_id, byte_pos, label)
# Bus ignored -- cross-validate by ID+byte only
CANDIDATES = [
    (0x589,       7, "0x589 B7"),
    (0x0BE,       4, "0x0BE B4"),
    (0x370,       7, "0x370 B7"),
    (0x410,       3, "0x410 B3"),
    (0x596,       6, "0x596 B6 (SoC)"),
    (0xC0CA040,   3, "0xC0CA040 B3"),
    (0x18FFD6B3,  0, "0x18FFD6B3 B0 (DCDC)"),
]

# Reference windows in this log
EVAP_LO,  EVAP_HI  =  8.0,  20.0   # evap completion + engine stop
M_ON_LO,  M_ON_HI  = 87.0,  95.0   # M mode engine on
M_OFF_LO, M_OFF_HI = 143.0, 150.0  # M mode engine off

CANDIDATE_IDS = {mid for mid, _, _ in CANDIDATES}

print("Scanning", LOG)
last_val = {}  # (msg_id, byte_pos) -> last value (ignoring bus for cross-val)
transitions = {(mid, bp): [] for mid, bp, _ in CANDIDATES}

frame_count = 0
for frame in parse_file(LOG):
    t = frame.timestamp
    frame_count += 1
    if frame.arbitration_id not in CANDIDATE_IDS:
        continue
    mid = frame.arbitration_id
    for i, b in enumerate(frame.data):
        key = (mid, i)
        if key not in transitions:
            continue
        prev = last_val.get(key)
        if prev is not None and prev != b:
            transitions[key].append((t, prev, b))
        last_val[key] = b

    if frame_count % 1_000_000 == 0:
        print(f"  {frame_count:,} frames ...")

print(f"Done. {frame_count:,} frames parsed.")

lines = []
lines.append("=" * 70)
lines.append("CROSS-VALIDATION: evap drive 4 part 2")
lines.append("Evap completion: t~12.07s  Engine off: t~16.7s")
lines.append("M mode on: t~90s  M mode off: t~145.5s")
lines.append("=" * 70)
lines.append("")

for mid, bp, label in CANDIDATES:
    key = (mid, bp)
    txns = transitions[key]
    lines.append(f"--- {label} ---")
    if not txns:
        lines.append("  (no transitions found in log)")
    else:
        for t, old, new in txns:
            tag = ""
            if EVAP_LO <= t <= EVAP_HI:
                tag = " <-- EVAP WINDOW"
            elif M_ON_LO <= t <= M_ON_HI:
                tag = " <-- M-ON WINDOW"
            elif M_OFF_LO <= t <= M_OFF_HI:
                tag = " <-- M-OFF WINDOW"
            lines.append(f"  t={t:.3f}s  0x{old:02X} -> 0x{new:02X}  ({old} -> {new}){tag}")
    lines.append("")

out_text = "\n".join(lines)
print(out_text)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(out_text)
print("Results saved to", OUT)
