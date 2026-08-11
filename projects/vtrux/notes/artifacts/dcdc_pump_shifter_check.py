"""
Cross-check driving timestamps against shifter position (0x055C) and
input shaft speed (0x308) from the pump plug-in log.

0x055C B0: parkLockState=B0[2:0], parkSensor=B0[6], driveSensor=B0[7]
0x308 B1-B2 LE: InputShaftSpeed = (value - 32128) * 0.5 RPM
"""

import sys, os, statistics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers.autodetect import parse_file as parse_log

LOG = "projects/vtrux/logs/vtrux_partstruck_pumpplugin.log"

print("Loading log...")
frames = list(parse_log(LOG))
t_end = max(f.timestamp for f in frames)
print(f"  {len(frames)} frames, span={t_end:.1f}s")

frames_055c = [f for f in frames if f.arbitration_id == 0x055C and len(f.data) >= 1]
frames_0308 = [f for f in frames if f.arbitration_id == 0x308 and len(f.data) >= 3]
print(f"  0x055C: {len(frames_055c)} frames")
print(f"  0x308:  {len(frames_0308)} frames")

print("\n--- 0x055C B0 state transitions (park/drive sensor) ---")
print(f"  {'t(s)':>8}  {'B0 hex':>6}  {'parkState[2:0]':>14}  {'parkSens[6]':>11}  {'driveSens[7]':>12}")
print("  " + "-"*60)
prev_b0 = None
for f in sorted(frames_055c, key=lambda x: x.timestamp):
    b0 = f.data[0]
    if b0 != prev_b0:
        park_state = b0 & 0x07
        park_sens = (b0 >> 6) & 1
        drive_sens = (b0 >> 7) & 1
        print(f"  {f.timestamp:8.2f}  {b0:02X}      {park_state:14}  {park_sens:11}  {drive_sens:12}")
        prev_b0 = b0

print("\n--- 0x308 InputShaftSpeed — transitions in/out of near-zero ---")
print("  (speed = (B1|(B2<<8) - 32128) * 0.5 RPM)")
MOVING_THRESH = 20
prev_moving = None
last_moving_t = None
last_stopped_t = None
transitions = []
for f in sorted(frames_0308, key=lambda x: x.timestamp):
    raw = f.data[1] | (f.data[2] << 8)
    rpm = (raw - 32128) * 0.5
    moving = abs(rpm) > MOVING_THRESH
    if moving != prev_moving:
        transitions.append((f.timestamp, moving, rpm))
        prev_moving = moving

for t, moving, rpm in transitions:
    state = "MOVING" if moving else "STOPPED"
    print(f"  t={t:8.2f}s  {state:8}  rpm={rpm:+.1f}")

print("\n--- 0x308 fine RPM in 40 time bins ---")
span = t_end
N = 40
bin_size = span / N
print(f"  {'Bin':>3} {'t_mid':>7}  {'shaft_rpm':>10}")
for b in range(N):
    t_lo = b * bin_size
    t_hi = (b+1) * bin_size
    t_mid = (t_lo + t_hi) / 2
    bframes = [f for f in frames_0308 if t_lo <= f.timestamp < t_hi]
    if not bframes:
        print(f"  {b:3d} {t_mid:7.1f}  (no data)")
        continue
    rpms = [(f.data[1] | (f.data[2] << 8) - 32128) * 0.5 for f in bframes]
    med = round(statistics.median(rpms), 1)
    print(f"  {b:3d} {t_mid:7.1f}  {med:10.1f}")
