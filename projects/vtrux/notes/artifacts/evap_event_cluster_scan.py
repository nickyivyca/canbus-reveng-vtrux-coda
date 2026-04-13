"""
Event cluster scan for evap signal identification.

Scans vtruxanotherevaplogpart2.log once, recording every byte-level transition.
Then compares which (bus, msg_id, byte_pos) signals change in each reference window.

Reference windows (from confirmed RPM event timestamps):
  evap_done : t=1388-1395s  -- evap cycle complete / engine auto-off
  stall     : t=806-818s    -- involuntary engine stall (control)
  m_on      : t=1453-1458s  -- user M mode engage (control)
  m_off     : t=1667-1672s  -- user M mode disengage (control)

Candidates = changed in evap_done window, NOT in any control window.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from canre.parsers import parse_file

LOG = "projects/vtrux/logs/vtruxanotherevaplogpart2.log"
OUT = "projects/vtrux/notes/artifacts/evap_cluster_scan_results.txt"

# Reference windows: (label, t_lo, t_hi)
WINDOWS = {
    "evap_done": (1388.0, 1395.0),
    "stall":     ( 806.0,  818.0),
    "m_on":      (1453.0, 1458.0),
    "m_off":     (1667.0, 1672.0),
}
CONTROLS = ["stall", "m_on", "m_off"]

# Padding around windows to capture pre/post state
PAD = 5.0
t_all_lo = min(lo - PAD for lo, hi in WINDOWS.values())
t_all_hi = max(hi + PAD for lo, hi in WINDOWS.values())

print("Scanning", LOG)
print("Collecting transitions in windows:", list(WINDOWS.keys()))

# transitions[label] = set of (bus, msg_id, byte_pos)
transitions = {k: set() for k in WINDOWS}
# details[label][(bus, msg_id, byte_pos)] = list of (t, old, new)
details = {k: {} for k in WINDOWS}

# last_val[(bus, msg_id, byte_pos)] = last seen byte value
last_val = {}

frame_count = 0
in_range_count = 0

for frame in parse_file(LOG):
    t = frame.timestamp
    frame_count += 1

    # Only track state changes within a broad window covering all reference windows
    # But we need last_val to be up to date, so we must track from the start.
    # Track last_val always; only record transitions inside windows.
    key_base = (frame.bus, frame.arbitration_id)
    for i, b in enumerate(frame.data):
        key = (frame.bus, frame.arbitration_id, i)
        prev = last_val.get(key)
        if prev is not None and prev != b:
            # Record transition in any matching window
            for label, (lo, hi) in WINDOWS.items():
                if lo <= t <= hi:
                    transitions[label].add(key)
                    det = details[label].setdefault(key, [])
                    det.append((t, prev, b))
        last_val[key] = b

    if frame_count % 2_000_000 == 0:
        print(f"  {frame_count:,} frames, t={t:.1f}s ...")

print(f"Done. {frame_count:,} total frames parsed.")

# --- Analysis ---
evap_set = transitions["evap_done"]
control_set = set()
for c in CONTROLS:
    control_set |= transitions[c]

candidates = evap_set - control_set
in_all = evap_set & control_set  # changed everywhere (likely engine-state signals)
control_only = control_set - evap_set

lines = []
lines.append("=" * 70)
lines.append("EVAP EVENT CLUSTER SCAN -- vtruxanotherevaplogpart2.log")
lines.append("=" * 70)
lines.append("")
lines.append("Reference windows:")
for label, (lo, hi) in WINDOWS.items():
    lines.append(f"  {label:12s}: t={lo:.1f} - {hi:.1f}s  ({len(transitions[label])} signals changed)")
lines.append("")

lines.append(f"Signals changed in evap_done:          {len(evap_set)}")
lines.append(f"Signals changed in any control window: {len(control_set)}")
lines.append(f"CANDIDATES (evap only, not controls):  {len(candidates)}")
lines.append(f"Changed in all windows (engine-state): {len(in_all)}")
lines.append("")

def fmt_key(key):
    bus, mid, byte = key
    return f"Bus{bus} 0x{mid:03X} B{byte}"

lines.append("=" * 70)
lines.append("CANDIDATES -- changed at evap_done, NOT at stall/m_on/m_off")
lines.append("=" * 70)
for key in sorted(candidates):
    lines.append(f"\n  {fmt_key(key)}")
    for t, old, new in details["evap_done"].get(key, []):
        lines.append(f"    t={t:.3f}s  0x{old:02X} -> 0x{new:02X}  ({old} -> {new})")

lines.append("")
lines.append("=" * 70)
lines.append("CHANGED IN ALL WINDOWS (engine-state signals, expected)")
lines.append("=" * 70)
for key in sorted(in_all):
    lines.append(f"\n  {fmt_key(key)}")
    lines.append(f"    evap_done: " + ", ".join(
        f"t={t:.2f} 0x{o:02X}->0x{n:02X}" for t, o, n in details["evap_done"].get(key, [])))
    for c in CONTROLS:
        if key in details[c]:
            lines.append(f"    {c:12s}: " + ", ".join(
                f"t={t:.2f} 0x{o:02X}->0x{n:02X}" for t, o, n in details[c].get(key, [])))

lines.append("")
lines.append("=" * 70)
lines.append("CONTROL-ONLY (changed at engine state changes, not evap_done)")
lines.append("=" * 70)
for key in sorted(control_only):
    windows_hit = [c for c in CONTROLS if key in transitions[c]]
    lines.append(f"  {fmt_key(key)}  [{', '.join(windows_hit)}]")

out_text = "\n".join(lines)
print(out_text)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(out_text)
print("\nResults saved to", OUT)
