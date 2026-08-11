import glob, struct, sys

# Parse BUSMASTER timestamp to seconds
def ts_to_s(ts):
    h, m, s, t = ts.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001

def parse_log(path):
    odometer = []   # (t, raw_24bit)
    speed_pts = []  # (t, km_h)
    with open(path, 'r', errors='replace') as f:
        for line in f:
            parts = line.split()
            if len(parts) < 7 or parts[1] not in ('Rx', 'Tx'):
                continue
            ts = ts_to_s(parts[0])
            id_ = parts[3]
            data = parts[6:6+8]

            if id_ == '0x625' and len(data) >= 3:
                raw = (int(data[0],16) << 16) | (int(data[1],16) << 8) | int(data[2],16)
                odometer.append((ts, raw))

            # 0x06000001 Veh_Speed: 15-bit Motorola B10:B11 (startbit 95, len 15)
            # From EPRI: Veh_Speed 15-bit Motorola, 1/64 km/h
            # Startbit=95 in 12-byte GoPoint packet -- raw CAN frame layout differs
            # Use PT bus 0x3E9 ECM_VehSpdAvgDrvn instead: 15-bit Motorola, 1/64 km/h
            if id_ == '0x3E9' and len(data) >= 4:
                # ECM_VehSpdAvgDrvn: 15-bit Motorola startbit=7, so B0[6:0] MSB + B1 LSB
                raw_spd = ((int(data[0],16) & 0x7F) << 8) | int(data[1],16)
                kmh = raw_spd / 64.0
                speed_pts.append((ts, kmh))

    return odometer, speed_pts

def analyze(path, label):
    print(label)
    odo, spd = parse_log(path)
    if not odo:
        print('  No odometer frames found')
        return
    odo_start = odo[0]
    odo_end   = odo[-1]
    delta_counts = odo_end[1] - odo_start[1]
    duration_s   = odo_end[0] - odo_start[0]
    print(f'  Odo start: {odo_start[1]} (0x{odo_start[1]:06X}) at t={odo_start[0]:.1f}s')
    print(f'  Odo end:   {odo_end[1]} (0x{odo_end[1]:06X}) at t={odo_end[0]:.1f}s')
    print(f'  Delta counts: {delta_counts}  over {duration_s:.0f}s')

    if spd:
        dist_km = 0.0
        prev_t, prev_kmh = spd[0]
        for t, kmh in spd[1:]:
            dt = t - prev_t
            dist_km += prev_kmh * dt / 3600.0
            prev_t, prev_kmh = t, kmh
        print(f'  Integrated speed distance: {dist_km:.3f} km  ({dist_km*0.621371:.3f} miles)')
        if delta_counts > 0:
            km_per_count = dist_km / delta_counts
            print(f'  Implied scale: {km_per_count:.6f} km/count  ({km_per_count*1000:.4f} m/count)')
            print(f'  Cross-check: 0x015625 km/count = 0.015625  (GMLAN 0x0120 scale)')
    print()

analyze('projects/vtrux/logs/debuglog_M0.log',            'debuglog_M0 (Aug 2025 drive, 245 MB)')
analyze('projects/vtrux/logs/vtruxscottsvalleydrive.log', 'vtruxscottsvalleydrive (Mar 2026, 69 min)')
analyze('projects/vtrux/logs/vtruxanotherevaplogpart2.log','vtruxanotherevaplogpart2 (Mar 2026, 33 min drive)')
