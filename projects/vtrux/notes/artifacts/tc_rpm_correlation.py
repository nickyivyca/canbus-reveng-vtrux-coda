"""
Correlation: traction motor RPM vs 0x1F5 LevPos / EstGear transitions.
Also checks same behavior in a regular driving log.

Motor RPM: 0x5A2 B2-B3 LE uint16 centered at 32768 (PT bus=2 in TC log)
OBD motor RPM: 0x044 B0-B1 LE uint16 - 32767 offset (OBD bus)
0x1F5 on Vehicle bus: B0 = EstGear (lower nibble), B3 = LevPos (lower nibble)

Plan:
1. Build RPM timeseries from TC test log
2. For each 0x1F5 state change, find the motor RPM at that moment
3. Table: gear transition vs RPM threshold
4. Also check 0x3E9 (vehicle speed) at those moments
5. Do the same analysis on movingaroundindriveway.log to confirm/deny similar pattern
"""

import sys
sys.path.insert(0, ".")
from canre.parsers import parse_file

TC_LOG   = "projects/vtrux/logs/vtrux_transfer_case_test.log"
DRIVE_LOG = "projects/vtrux/logs/movingaroundindriveway.log"

def identify_buses(frames):
    """Returns (obd_bus, pt_bus, veh_bus) by anchor IDs."""
    from collections import defaultdict
    ids_by_bus = defaultdict(set)
    for f in frames[:5000]:
        ids_by_bus[f.bus].add(f.arbitration_id)
    obd = pt = veh = None
    for bus, ids in ids_by_bus.items():
        if 0x041 in ids or (0x040 in ids and 0x441 in ids):
            obd = bus
        if 0x051 in ids or 0x308 in ids:
            pt = bus
        if 0x1E5 in ids or 0x500 in ids:
            veh = bus
    return obd, pt, veh

def build_timeseries(frames, arb_id, bus, decode_fn):
    """Returns list of (timestamp, value) from decode_fn(frame.data)."""
    result = []
    for f in frames:
        if f.arbitration_id == arb_id and f.bus == bus:
            v = decode_fn(f.data)
            if v is not None:
                result.append((f.timestamp, v))
    return result

def interp(ts_series, t):
    """Linearly interpolate a timeseries at time t."""
    if not ts_series:
        return None
    lo = hi = None
    for i, (ts, v) in enumerate(ts_series):
        if ts <= t:
            lo = (ts, v)
        if ts >= t and hi is None:
            hi = (ts, v)
    if lo is None:
        return ts_series[0][1]
    if hi is None:
        return ts_series[-1][1]
    if lo[0] == hi[0]:
        return lo[1]
    frac = (t - lo[0]) / (hi[0] - lo[0])
    return lo[1] + frac * (hi[1] - lo[1])

def trac_rpm_from_5A2(data):
    if len(data) < 4:
        return None
    raw = data[2] | (data[3] << 8)
    return raw - 32768

def trac_rpm_from_044(data):
    if len(data) < 2:
        return None
    raw = data[0] | (data[1] << 8)
    return raw - 32767

def veh_speed_from_3E9(data):
    if len(data) < 2:
        return None
    raw = (data[0] << 7) | (data[1] >> 1)
    return raw / 64.0

def analyze_log(log_path, label):
    print(f"\n{'='*60}")
    print(f"LOG: {label}")
    print(f"{'='*60}")

    frames = list(parse_file(log_path))
    obd, pt, veh = identify_buses(frames)
    print(f"  Buses: OBD={obd} PT={pt} VEH={veh}")

    rpm_pt  = build_timeseries(frames, 0x5A2, pt,  trac_rpm_from_5A2) if pt else []
    rpm_obd = build_timeseries(frames, 0x044, obd, trac_rpm_from_044) if obd else []
    vspd    = build_timeseries(frames, 0x3E9, veh, veh_speed_from_3E9) if veh else []

    rpm_src = rpm_pt if rpm_pt else rpm_obd
    rpm_label = "0x5A2" if rpm_pt else "0x044"
    print(f"  RPM source: {rpm_label} ({len(rpm_src)} samples)")
    print(f"  VehSpd source: 0x3E9 ({len(vspd)} samples)")

    if not rpm_src:
        print("  No RPM data - skipping")
        return

    f1f5 = [(f.timestamp, f.data) for f in frames
            if f.arbitration_id == 0x1F5 and f.bus == veh]
    if not f1f5:
        print("  No 0x1F5 on VEH bus - skipping")
        return

    print(f"\n  0x1F5 state transitions vs RPM:")
    print(f"  {'Time':>8}  {'EstGear':>8}  {'LevPos raw':>10}  {'LevPos':>18}  {'RPM':>7}  {'Vspd km/h':>10}")
    print(f"  {'-'*8}  {'-'*8}  {'-'*10}  {'-'*18}  {'-'*7}  {'-'*10}")

    LEV_NAMES = {0: 'Between Ranges', 1: 'Park Range', 4: 'Forward Range A',
                 5: 'Fwd Range B', 9: 'Reverse', 15: 'Error/NA'}
    GEAR_NAMES = {0:'Park', 1:'1st', 2:'2nd', 3:'3rd', 4:'4th',
                  5:'5th', 6:'6th', 14:'Reverse', 15:'Park Gear'}

    prev_gear = prev_lev = None
    for t, data in f1f5:
        if len(data) < 4:
            continue
        gear = data[0] & 0x0F
        lev  = data[3] & 0x0F
        if gear == prev_gear and lev == prev_lev:
            continue
        rpm  = interp(rpm_src, t)
        vs   = interp(vspd, t)
        gear_name = GEAR_NAMES.get(gear, str(gear))
        lev_name  = LEV_NAMES.get(lev, f"raw={lev}")
        rpm_str   = f"{rpm:+.0f}" if rpm is not None else "N/A"
        vs_str    = f"{vs:.1f}" if vs is not None else "N/A"
        marker = " <-- BETWEEN RANGES" if lev == 0 else ""
        print(f"  {t:8.3f}  {gear_name:>8}  {lev:>10}  {lev_name:>18}  {rpm_str:>7}  {vs_str:>10}{marker}")
        prev_gear, prev_lev = gear, lev

    print(f"\n  Gear estimate vs RPM threshold table:")
    print(f"  (RPM at which each gear first appears)")
    gear_first_rpm = {}
    prev_gear = None
    for t, data in f1f5:
        if len(data) < 4:
            continue
        gear = data[0] & 0x0F
        if gear != prev_gear:
            rpm = interp(rpm_src, t)
            if gear not in gear_first_rpm:
                gear_first_rpm[gear] = rpm
            prev_gear = gear
    for g in sorted(gear_first_rpm):
        gname = GEAR_NAMES.get(g, str(g))
        print(f"    Gear {gname:>10}: RPM={gear_first_rpm[g]:+.0f}" if gear_first_rpm[g] is not None else f"    Gear {gname}: RPM=N/A")

    print(f"\n  Between-Ranges events and RPM at each:")
    prev_lev = None
    for t, data in f1f5:
        if len(data) < 4:
            continue
        lev = data[3] & 0x0F
        if lev != prev_lev:
            if lev == 0:
                rpm = interp(rpm_src, t)
                vs  = interp(vspd, t)
                print(f"    t={t:.3f}s  Between Ranges  RPM={rpm:+.0f}  Vspd={vs:.1f} km/h")
            prev_lev = lev

CLIMIT_LOG = "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
analyze_log(CLIMIT_LOG, "current limiting test (driving log)")
