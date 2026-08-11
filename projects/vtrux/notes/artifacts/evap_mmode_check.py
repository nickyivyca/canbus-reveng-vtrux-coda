import sys
sys.path.insert(0, r'<repo>')
from canre.parsers import parse_file

LOG_PATH = r'<repo>\projects\vtrux\logs\vtruxgeneratoroverheattest.log'

PT_ANCHOR = 0x051
VEH_ANCHOR = 0x1E5
TARGET_IDS = {0x1F5, 0x649, 0x600}

pt_bus = None
veh_bus = None
frames_by_id_bus = {}  # (arb_id, bus) -> list of (timestamp, data)
total = 0
sampled = {}  # bus -> set of arb_ids seen in first 5000 frames

print("Streaming log (single pass, collecting only target IDs)...")

for f in parse_file(LOG_PATH):
    total += 1

    if total <= 5000:
        sampled.setdefault(f.bus, set()).add(f.arbitration_id)
    elif total == 5001:
        for bus, ids in sampled.items():
            if PT_ANCHOR in ids:
                pt_bus = bus
            if VEH_ANCHOR in ids:
                veh_bus = bus
        if pt_bus is not None and veh_bus is not None:
            print(f"  PT bus={pt_bus}, Vehicle bus={veh_bus}")

    if f.arbitration_id in TARGET_IDS:
        key = (f.arbitration_id, f.bus)
        if key not in frames_by_id_bus:
            frames_by_id_bus[key] = []
        frames_by_id_bus[key].append((f.timestamp, bytes(f.data)))

    if total % 2000000 == 0:
        print(f"  {total//1000000}M frames processed...")

print(f"Done. Total frames: {total:,}")

if pt_bus is None or veh_bus is None:
    print("ERROR: buses not identified from sample - trying full scan")
    for bus, ids in sampled.items():
        print(f"  Bus {bus}: anchor IDs present: 0x051={PT_ANCHOR in ids}, 0x1E5={VEH_ANCHOR in ids}")
    sys.exit(1)

key_1f5 = (0x1F5, veh_bus)
key_649 = (0x649, pt_bus)
key_600 = (0x600, pt_bus)

frames_1f5 = frames_by_id_bus.get(key_1f5, [])
frames_649 = frames_by_id_bus.get(key_649, [])
frames_600 = frames_by_id_bus.get(key_600, [])

print(f"\n0x1F5 (Vehicle bus {veh_bus}): {len(frames_1f5)} frames")
print(f"0x649 (PT bus {pt_bus}):     {len(frames_649)} frames")
print(f"0x600 (PT bus {pt_bus}):     {len(frames_600)} frames")

# Find M-mode windows: LevPos = B3 & 0x0F == 9
print("\nFinding M-mode windows (0x1F5 LevPos=9)...")
mmode_windows = []
in_mmode = False
mmode_start = None
for (t, data) in frames_1f5:
    lever = data[3] & 0x0F if len(data) > 3 else 0
    if lever == 9 and not in_mmode:
        in_mmode = True
        mmode_start = t
    elif lever != 9 and in_mmode:
        mmode_windows.append((mmode_start, t))
        in_mmode = False
if in_mmode:
    mmode_windows.append((mmode_start, frames_1f5[-1][0]))

print(f"Found {len(mmode_windows)} M-mode window(s):")
for i, (t0, t1) in enumerate(mmode_windows):
    print(f"  [{i}] t={t0:.2f}s - {t1:.2f}s  (duration={t1-t0:.1f}s)")

if not mmode_windows:
    print("No M-mode windows found. Exiting.")
    sys.exit(0)

# For each window, check evap signals
print("\nPer M-mode window analysis:")
for i, (t0, t1) in enumerate(mmode_windows):
    w649 = [(t, d) for (t, d) in frames_649 if t0 <= t <= t1]
    w600 = [(t, d) for (t, d) in frames_600 if t0 <= t <= t1]

    if not w649 and not w600:
        print(f"  [{i}] t={t0:.1f}-{t1:.1f}s: no PT frames in window")
        continue

    b0_vals = set(d[0] for (t, d) in w649 if d)
    bit7_set = any((v >> 7) & 1 for v in b0_vals)
    b3_vals = set(d[3] for (t, d) in w600 if len(d) > 3)
    b3_min = min(b3_vals) if b3_vals else None

    flag = "  *** EVAP ACTIVE ***" if bit7_set else ""
    print(f"  [{i}] t={t0:.1f}-{t1:.1f}s ({t1-t0:.1f}s):{flag}")
    print(f"    0x649 B0 unique: {sorted(hex(v) for v in b0_vals)}")
    print(f"    0x649 bit7 (evap_active) set: {bit7_set}")
    print(f"    0x600 B3 (evap stage): {sorted(b3_vals)}  (12=normal, <12=evap)")

# Full transition timeline for bit7 of 0x649
print("\nFull 0x649 B0 bit7 transition timeline (with M-mode flag):")
prev_bit7 = None
for (t, data) in frames_649:
    bit7 = (data[0] >> 7) & 1 if data else 0
    if bit7 != prev_bit7:
        in_mmode_now = any(t0 <= t <= t1 for (t0, t1) in mmode_windows)
        b3_at_t = None
        for (t2, d2) in frames_600:
            if abs(t2 - t) < 1.0 and len(d2) > 3:
                b3_at_t = d2[3]
                break
        print(f"  t={t:.2f}s  B0=0x{data[0]:02X}  evap_bit7={bit7}  M-mode={in_mmode_now}  0x600-B3={b3_at_t}")
        prev_bit7 = bit7
