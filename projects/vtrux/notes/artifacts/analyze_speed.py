"""
Correlate vehicle speed (0x3E9) and transmission output shaft speed (0x0F9)
with direction from 0x0C7, all from bus 2 of movingaroundindriveway.log.

Signal definitions (GMW8762):
  0x0C7 (12.5ms): Transmission Output Rotational Status
    B0 bits 7-6: Rotation Direction (0=Unknown, 1=Forward, 2=Reverse, 3=Undef)
    B0 bits 5-4: Last Transition Type
    B0 bit    3: Reset Occurred
    B0 bit    2: Validity (0=Valid)
    B0 bits 1-0: Pulse Counter MSBs (top 2 of 10-bit)
    B1 bits 7-0: Pulse Counter LSBs (lower 8 of 10-bit)  -> 0-1023 counts
    B2-B3:       Timestamp (16-bit, 0-65535 counts)

  0x0F9 (12.5ms): Transmission General Status 1
    B0-B1: Transmission Overall Estimated Torque Ratio (15-bit signed, /256)
    B2:    Status flags
    B3-B4: Transmission Output Shaft Angular Velocity (16-bit unsigned, *0.25 rpm)

  0x3E9 (100ms): Vehicle Speed and Distance
    B0 bit  7:   Vehicle Speed Average Driven Validity (0=Valid)
    B0 bits 6-0: Vehicle Speed Average Driven MSBs (top 7 of 15-bit)
    B1 bits 7-0: Vehicle Speed Average Driven LSBs (lower 8 of 15-bit)
                 -> physical = N * 0.015625 km/h
    B4 bit  7:   Vehicle Speed Average Non Driven Validity
    B4 bits 6-0: Vehicle Speed Average Non Driven MSBs
    B5 bits 7-0: Vehicle Speed Average Non Driven LSBs
                 -> physical = N * 0.015625 km/h
"""

import re
from collections import defaultdict

LOG_PATH = r"<home>\<drive-root>\<library>\My Libraries\Projects\reverse-it\projects\vtrux\threebus-investigation\movingaroundindriveway.log"

TARGET_IDS = {0x0C7, 0x0F9, 0x1F5, 0x3E9}

BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)+)'
)

DIR_NAMES = {0: "Unk", 1: "Fwd", 2: "Rev", 3: "???"}
GEAR_NAMES = {0: "BetweenRng", 1: "Park", 2: "Reverse", 3: "Neutral",
              4: "Drive", 0xF: "Unknown"}


def parse_ts(ts_str):
    h, m, s, t = ts_str.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001


# ---- Pass 1: collect all frames of interest from bus 2 ----
frames = defaultdict(list)   # msg_id -> [(rel_t, data)]
t0 = None

with open(LOG_PATH, 'r', errors='replace') as f:
    for line in f:
        m = BUSMASTER_RE.match(line.strip())
        if not m:
            continue
        ts_str, bus_str, id_str, dlc_str, data_str = m.groups()
        if int(bus_str) != 2:
            continue
        msg_id = int(id_str, 16)
        if msg_id not in TARGET_IDS:
            continue
        ts = parse_ts(ts_str)
        if t0 is None:
            t0 = ts
        rel = ts - t0
        data = [int(b, 16) for b in data_str.strip().split()]
        frames[msg_id].append((rel, data))

print("Message presence on bus 2:")
for mid in sorted(TARGET_IDS):
    n = len(frames[mid])
    if n:
        ts_first = frames[mid][0][0]
        ts_last  = frames[mid][-1][0]
        print(f"  0x{mid:03X}: {n:5d} frames, t={ts_first:.2f}s to {ts_last:.2f}s")
    else:
        print(f"  0x{mid:03X}: NOT FOUND on bus 2")
print()

if not frames[0x0F9] and not frames[0x3E9] and not frames[0x0C7]:
    print("No speed data found. Exiting.")
    exit()


# ---- Decoders ----

def decode_0c7(d):
    """0x0C7 Transmission Output Rotational Status."""
    direction = (d[0] >> 6) & 0x3
    valid     = (d[0] >> 2) & 0x1
    pulse     = ((d[0] & 0x3) << 8) | d[1]
    ts        = (d[2] << 8) | d[3] if len(d) >= 4 else 0
    return direction, valid, pulse, ts


def decode_0f9(d):
    """0x0F9 Transmission General Status 1."""
    if len(d) < 5:
        return None, None, None
    # Torque ratio: B0 bit6, length 15, signed
    raw_torque = ((d[0] & 0x7F) << 8) | d[1]
    # sign-extend 15-bit
    if raw_torque & 0x4000:
        raw_torque -= 0x8000
    torque_ratio = raw_torque / 256.0
    torque_valid = (d[0] >> 7) & 0x1  # 0=valid

    # Output shaft speed: B3, bit7, length 16, unsigned
    shaft_rpm_raw = (d[3] << 8) | d[4]
    shaft_rpm = shaft_rpm_raw * 0.25
    shaft_valid = (d[2] >> 7) & 0x1  # 0=valid

    return torque_ratio, torque_valid, shaft_rpm, shaft_valid


def decode_3e9(d):
    """0x3E9 Vehicle Speed and Distance."""
    if len(d) < 6:
        return None, None, None, None
    vspd_valid = (d[0] >> 7) & 0x1
    vspd_raw   = ((d[0] & 0x7F) << 8) | d[1]
    vspd_kmh   = vspd_raw * 0.015625

    nd_valid  = (d[4] >> 7) & 0x1
    nd_raw    = ((d[4] & 0x7F) << 8) | d[5]
    nd_kmh    = nd_raw * 0.015625

    return vspd_kmh, vspd_valid, nd_kmh, nd_valid


def decode_1f5_lever(d):
    """Get shift lever position from 0x1F5 byte 3."""
    return d[3] & 0xF if len(d) >= 4 else 0


# ---- Build lookup tables: for any time t, find latest reading ----

def make_lookup(msg_id, decoder):
    """Return a list of (t, decoded...) sorted by t."""
    result = []
    for t, d in frames[msg_id]:
        dec = decoder(d)
        if dec is not None and (not isinstance(dec, tuple) or dec[0] is not None):
            result.append((t,) + (dec if isinstance(dec, tuple) else (dec,)))
    return result


def nearest_before(table, t):
    """Binary search: find last entry at or before t."""
    lo, hi = 0, len(table) - 1
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if table[mid][0] <= t:
            best = table[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


# ---- Build signal tables ----
tbl_0c7 = make_lookup(0x0C7, decode_0c7)
tbl_0f9 = [(t,) + decode_0f9(d) for t, d in frames[0x0F9]]
tbl_1f5 = [(t, decode_1f5_lever(d)) for t, d in frames[0x1F5]]

if frames[0x3E9]:
    tbl_3e9 = [(t,) + decode_3e9(d) for t, d in frames[0x3E9]]
else:
    tbl_3e9 = []


# ---- Section 1: Show all distinct vehicle speed readings ----
print("="*70)
print("0x3E9 VEHICLE SPEED (driven + non-driven), all changes")
print("="*70)
if tbl_3e9:
    prev_vspd = None
    for row in tbl_3e9:
        t, vspd, vv, nd, ndv = row
        if abs((vspd or 0) - (prev_vspd or 0)) > 0.05:
            gear = nearest_before(tbl_1f5, t)
            gname = GEAR_NAMES.get(gear[1], "?") if gear else "?"
            print(f"  t={t:7.3f}s  Driven={vspd:6.3f} km/h {'(INV)' if vv else '     '}  "
                  f"NonDriven={nd:6.3f} km/h {'(INV)' if ndv else '     '}  [{gname}]")
            prev_vspd = vspd
else:
    print("  0x3E9 not present on bus 2")

print()
print("="*70)
print("0x0C7 TRANSMISSION OUTPUT DIRECTION changes (all transitions)")
print("="*70)
if tbl_0c7:
    prev_dir = None
    for row in tbl_0c7:
        t, direction, valid, pulse, ts = row
        if direction != prev_dir:
            gear = nearest_before(tbl_1f5, t)
            gname = GEAR_NAMES.get(gear[1], "?") if gear else "?"
            print(f"  t={t:7.3f}s  Direction={DIR_NAMES.get(direction,'?')}  "
                  f"Valid={'Y' if not valid else 'N'}  Pulse={pulse:4d}  [{gname}]")
            prev_dir = direction
else:
    print("  0x0C7 not present on bus 2")

print()
print("="*70)
print("0x0F9 TRANSMISSION OUTPUT SHAFT SPEED (changes > 10 rpm)")
print("="*70)
if tbl_0f9:
    prev_rpm = None
    for row in tbl_0f9:
        t, torque_ratio, tv, shaft_rpm, sv = row
        if shaft_rpm is None:
            continue
        if prev_rpm is None or abs(shaft_rpm - prev_rpm) > 10:
            gear = nearest_before(tbl_1f5, t)
            gname = GEAR_NAMES.get(gear[1], "?") if gear else "?"
            print(f"  t={t:7.3f}s  ShaftRPM={shaft_rpm:8.2f}  "
                  f"TorqueRatio={torque_ratio:+6.3f}  [{gname}]")
            prev_rpm = shaft_rpm
else:
    print("  0x0F9 not present on bus 2")


# ---- Section 2: Merged timeline — correlate all signals ----
print()
print("="*70)
print("MERGED TIMELINE: vehicle speed vs transmission shaft speed")
print("(sampled at each 0x3E9 frame, with nearest 0x0F9 + direction)")
print("="*70)

if tbl_3e9 and tbl_0f9:
    header = (f"{'Time':>8}  {'Gear':<11}  {'Dir':>5}  "
              f"{'VSpd km/h':>10}  {'ShaftRPM':>10}  {'Ratio':>8}  Note")
    print(header)
    print("-" * 75)

    prev_vspd = None
    for row in tbl_3e9:
        t, vspd, vv, nd, ndv = row
        if abs((vspd or 0) - (prev_vspd or 0)) < 0.01:
            continue   # skip unchanged rows to keep output manageable
        prev_vspd = vspd

        gear_row = nearest_before(tbl_1f5, t)
        gname = GEAR_NAMES.get(gear_row[1], "?") if gear_row else "?"

        dir_row = nearest_before(tbl_0c7, t) if tbl_0c7 else None
        dir_name = DIR_NAMES.get(dir_row[1], "?") if dir_row else " N/A"

        # Find nearest 0x0F9 reading
        f9_row = nearest_before(tbl_0f9, t)
        shaft_rpm = f9_row[3] if f9_row else None

        # Compute ratio: shaft_rpm / vspd_kmh (should be constant if correlated)
        if shaft_rpm and vspd and vspd > 0.1:
            ratio = shaft_rpm / vspd
            ratio_str = f"{ratio:8.1f}"
        else:
            ratio_str = "       -"

        note = ""
        if vv:
            note += " [spd invalid]"
        if dir_row and dir_row[2]:
            note += " [dir invalid]"

        print(f"{t:8.3f}  {gname:<11}  {dir_name:>5}  "
              f"{(vspd or 0):10.3f}  {(shaft_rpm or 0):10.2f}  {ratio_str}  {note}")

elif tbl_0f9 and not tbl_3e9:
    # Fall back to showing 0x0F9 alone with direction
    print("(0x3E9 not available; showing 0x0F9 shaft RPM alone)")
    print(f"{'Time':>8}  {'Gear':<11}  {'Dir':>5}  {'ShaftRPM':>10}")
    print("-" * 45)
    prev_rpm = None
    for row in tbl_0f9:
        t, torque_ratio, tv, shaft_rpm, sv = row
        if shaft_rpm is None:
            continue
        if prev_rpm is not None and abs(shaft_rpm - prev_rpm) < 5:
            continue
        prev_rpm = shaft_rpm
        gear_row = nearest_before(tbl_1f5, t)
        gname = GEAR_NAMES.get(gear_row[1], "?") if gear_row else "?"
        dir_row = nearest_before(tbl_0c7, t) if tbl_0c7 else None
        dir_name = DIR_NAMES.get(dir_row[1], "?") if dir_row else " N/A"
        print(f"{t:8.3f}  {gname:<11}  {dir_name:>5}  {shaft_rpm:10.2f}")

print()
print("="*70)
print("SPEED RANGE SUMMARY BY GEAR PHASE")
print("="*70)

# Known gear phases from 1F5 analysis
phases = [
    (0.0,    24.54, "Park (start)"),
    (24.63,  46.03, "Drive #1"),
    (46.63,  53.32, "Reverse #1"),
    (53.38,  74.87, "Drive #2"),
    (75.07,  80.12, "Reverse #2"),
    (80.21,  86.12, "Drive #3"),
    (86.96,  94.52, "Reverse #3"),
    (94.58,  97.61, "Drive #4"),
    (97.79, 115.0,  "Park (end)"),
]

def frames_in(table, t0, t1):
    return [row for row in table if t0 <= row[0] <= t1]

print(f"\n{'Phase':<20}  {'Duration':>8}  {'MaxSpd km/h':>12}  "
      f"{'MaxRPM':>9}  {'Dir':>6}  {'Ratio':>8}")
print("-" * 80)

for (ta, tb, label) in phases:
    dur = tb - ta

    # Vehicle speed
    spd_rows = frames_in(tbl_3e9, ta, tb)
    speeds   = [r[1] for r in spd_rows if r[1] is not None and r[2] == 0]
    max_spd  = max(speeds) if speeds else None

    # Shaft rpm
    rpm_rows = frames_in(tbl_0f9, ta, tb)
    rpms     = [r[3] for r in rpm_rows if r[3] is not None and r[4] == 0]
    max_rpm  = max(rpms) if rpms else None

    # Direction
    dir_rows = frames_in(tbl_0c7, ta, tb)
    dirs     = [DIR_NAMES.get(r[1], "?") for r in dir_rows if r[2] == 0]
    dir_str  = max(set(dirs), key=dirs.count) if dirs else "N/A"

    # Typical ratio at peak speed
    if max_spd and max_rpm and max_spd > 0.1:
        ratio = max_rpm / max_spd
        ratio_str = f"{ratio:8.1f}"
    else:
        ratio_str = "       -"

    spd_str = f"{max_spd:12.3f}" if max_spd is not None else "           -"
    rpm_str = f"{max_rpm:9.2f}" if max_rpm is not None else "        -"
    print(f"{label:<20}  {dur:8.1f}  {spd_str}  {rpm_str}  {dir_str:>6}  {ratio_str}")
