"""
Scratchpad: full-charge-then-fail.log
Two questions:
1. What does 0x420 B3 (insulation resistance, normal=190-200) look like over the full log?
2. Is there any restart attempt at the end, or does the log just end after the fault?

Key signals for restart detection:
- 0x410 B1: 0x3F = pre-HV startup, 0xBF = normal running, 0xCF = fault latched
- 0x410 B0: bit4 = contactor-closed candidate, bit3 = interlock loop
- 0x412 B0: 0x2D = normal, 0x00 = fault/off
"""

import sys
sys.path.insert(0, ".")
from canre.parsers import parse_file

import os
LOG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs", "full-charge-then-fail.log"))

print("Loading log...")
frames = list(parse_file(LOG))
print(f"Loaded {len(frames)} frames")

# --- Q1: 0x420 B3 timeseries ---
print("\n=== 0x420 B3 (Insulation Resistance) Timeseries ===")
print(f"(only prints when value changes)")
frames_420 = [f for f in frames if f.arbitration_id == 0x420]
print(f"0x420 frames: {len(frames_420)}")
print(f"Time span: {frames_420[0].timestamp:.1f}s - {frames_420[-1].timestamp:.1f}s")

prev_b3 = None
b3_events = []
for f in frames_420:
    b3 = f.data[3]
    if b3 != prev_b3:
        b3_events.append((f.timestamp, b3))
        prev_b3 = b3

print(f"\nAll B3 transitions ({len(b3_events)} total):")
for t, val in b3_events:
    minutes = t / 60.0
    print(f"  t={t:8.2f}s ({minutes:5.1f}min)  B3={val:3d} (0x{val:02X})")

# --- Q2: Last 300s of log - look for restart activity ---
print("\n\n=== Last 300s of log - restart activity search ===")
log_end = frames[-1].timestamp
window_start = log_end - 300.0

print(f"Log ends at t={log_end:.1f}s. Examining last 300s (from t={window_start:.1f}s).")

tail_frames = [f for f in frames if f.timestamp >= window_start]
print(f"Frames in last 300s: {len(tail_frames)}")

# Focus on key status signals: 0x410 B1, 0x410 B0, 0x412 B0, 0x596 B0 (SoC)
watch_ids = {0x410, 0x412, 0x596, 0x410}

print("\n--- 0x410 B0/B1 transitions in last 300s ---")
frames_410 = [f for f in tail_frames if f.arbitration_id == 0x410]
prev_b0 = prev_b1 = None
for f in frames_410:
    b0, b1 = f.data[0], f.data[1]
    if b0 != prev_b0 or b1 != prev_b1:
        print(f"  t={f.timestamp:8.2f}s  B0=0x{b0:02X} B1=0x{b1:02X}")
        prev_b0, prev_b1 = b0, b1

print("\n--- 0x412 B0 transitions in last 300s ---")
frames_412 = [f for f in tail_frames if f.arbitration_id == 0x412]
prev = None
for f in frames_412:
    v = f.data[0]
    if v != prev:
        print(f"  t={f.timestamp:8.2f}s  B0=0x{v:02X} ({v})")
        prev = v

print("\n--- 0x596 B0 (SoC integer) in last 300s (changes only) ---")
frames_596 = [f for f in tail_frames if f.arbitration_id == 0x596]
prev = None
for f in frames_596:
    v = f.data[0]
    if v != prev:
        print(f"  t={f.timestamp:8.2f}s  B0={v} (%)")
        prev = v

print("\n--- Any IDs that appear AFTER the last fault event (last 60s of log) ---")
fault_window = log_end - 60.0
post_fault = [f for f in frames if f.timestamp >= fault_window]
ids_after = sorted(set(f.arbitration_id for f in post_fault))
print(f"IDs active in last 60s (t > {fault_window:.1f}s): {[hex(i) for i in ids_after]}")

# Check if 0x410 B1 ever recovers from 0xCF back toward 0x3F (restart)
print("\n--- 0x410 B1 unique values in last 300s ---")
b1_vals_tail = sorted(set(f.data[1] for f in frames_410))
print(f"  Unique B1 values: {[hex(v) for v in b1_vals_tail]}")

# Show last 10 frames of key IDs to see how log ends
print("\n--- Very last frames of 0x410 ---")
for f in frames_410[-5:]:
    print(f"  t={f.timestamp:.3f}s  {' '.join(f'{b:02X}' for b in f.data)}")

print("\n--- Very last frame overall ---")
print(f"  t={frames[-1].timestamp:.3f}s  id=0x{frames[-1].arb_id:03X}  {' '.join(f'{b:02X}' for b in frames[-1].data)}")
print(f"  id=0x{frames[-2].arb_id:03X} at t={frames[-2].timestamp:.3f}s")
print(f"  id=0x{frames[-3].arb_id:03X} at t={frames[-3].timestamp:.3f}s")
