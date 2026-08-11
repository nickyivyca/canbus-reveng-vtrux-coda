"""Quick check of 0x600 B3 and generator state across multiple logs."""
import sys
sys.path.insert(0, '.')
from canre.parsers import parse_file

LOGS = [
    'projects/vtrux/logs/movingaroundindriveway.log',
    'projects/vtrux/logs/generator on then off.log',
    'projects/vtrux/logs/vtruxcurrentlimitingtest.log',
    'projects/vtrux/logs/debuglog_M0_T2_short.log',
    'projects/vtrux/logs/debuglog_M0_T2.log',
    'projects/vtrux/logs/debuglog_M0_T7.log',
    'projects/vtrux/logs/vtruxinterlocktest.log',
    'projects/vtrux/logs/vtruxcodereading.log',
]

PT_ANCHORS = {0x051}

def check_log(path):
    try:
        pt_bus = None
        b3_vals = []
        b0_vals = []
        gen_rpm_max = 0
        frame_count = 0
        for frame in parse_file(path):
            cid = frame.arbitration_id
            bus = frame.bus
            frame_count += 1
            if frame_count > 3_000_000:
                break
            if cid == 0x051 and pt_bus is None:
                pt_bus = bus
            if pt_bus is not None and bus == pt_bus and cid == 0x600 and frame.dlc >= 4:
                b3 = frame.data[3]
                b0 = frame.data[0]
                b3_vals.append((frame.timestamp, b3, b0))
            if pt_bus is not None and bus == pt_bus and cid == 0x63C and frame.dlc >= 7:
                b6 = frame.data[6]
                rpm = 16 * b6 - 96
                if rpm > gen_rpm_max:
                    gen_rpm_max = rpm

        if not b3_vals:
            return f'  PT bus: {pt_bus}  No 0x600 frames found'

        # Sample: first, at 25%, 50%, 75%, last
        n = len(b3_vals)
        samples = [b3_vals[0], b3_vals[n//4], b3_vals[n//2], b3_vals[3*n//4], b3_vals[-1]]
        unique_b3 = sorted(set(v[1] for v in b3_vals))
        unique_b0 = sorted(set(v[2] for v in b3_vals))
        lines = [f'  PT bus: {pt_bus}  |  0x600 frames: {n:,}  |  gen RPM max: {gen_rpm_max}']
        lines.append(f'  B3 unique values: {unique_b3}')
        lines.append(f'  B0 unique values: {[hex(b) for b in unique_b0]}')
        lines.append(f'  Samples (t, B3, B0):')
        for t, b3, b0 in samples:
            lines.append(f'    t={t:7.1f}s  B3={b3:3d}  B0={hex(b0)}')
        return '\n'.join(lines)
    except Exception as e:
        return f'  ERROR: {e}'

for log in LOGS:
    name = log.split('/')[-1]
    print(f'\n=== {name} ===')
    print(check_log(log))
