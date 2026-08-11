"""
check_0x430_nibbles.py -- Check upper nibbles of 0x430 B0 and B2 across logs.

For each log, reports:
  - unique values of (B0 >> 4) and (B2 >> 4)
  - min/max of the two 12-bit masked fields: (B0&0x0F)<<8|B1 and (B2&0x0F)<<8|B3
  - spread (max(B01) - min(B23) and vice versa) to gauge imbalance visibility
  - first and last 10 frames for beginning/end checks
"""
import sys
sys.path.insert(0, '.')
from canre.parsers import parse_file

LOGS = [
    # Same physical battery as current truck (truk1log = new battery)
    ('truk1log_start',  'projects/vtrux/logs/truk1log_M0_T0.log'),
    ('truk1log_end',    'projects/vtrux/logs/truk1log_M1_T18.log'),
    # Original battery (Bel Inverter folder truklog sessions)
    ('og_battery_start', 'projects/vtrux/Bel-Inverter/other-logs/truklog_M0_T0.log'),
    ('og_battery_end',   'projects/vtrux/Bel-Inverter/other-logs/truklog_M3_T22.log'),
]

OUT = 'projects/vtrux/notes/artifacts/check_0x430_nibbles.txt'

lines = []

def banner(s):
    lines.append('')
    lines.append('=' * 60)
    lines.append(s)
    lines.append('=' * 60)

for label, path in LOGS:
    banner(label)
    lines.append(f'  Log: {path}')
    try:
        frames = list(parse_file(path))
    except Exception as e:
        lines.append(f'  ERROR loading: {e}')
        continue

    # Identify PT bus
    bus_ids = {}
    for f in frames:
        bus_ids.setdefault(f.bus, set()).add(f.arbitration_id)
    pt_buses = [b for b, ids in bus_ids.items() if 0x051 in ids]
    if not pt_buses:
        lines.append('  WARNING: no PT bus found (no 0x051)')
        pt_bus = None
    else:
        pt_bus = pt_buses[0]
        lines.append(f'  PT bus = {pt_bus}')

    frames_430 = [f for f in frames
                  if f.bus == pt_bus and f.arbitration_id == 0x430 and len(f.data) >= 4]
    lines.append(f'  0x430 frames: {len(frames_430)}')

    if not frames_430:
        lines.append('  (no 0x430 data)')
        continue

    b0_nibbles  = sorted(set(f.data[0] >> 4 for f in frames_430))
    b2_nibbles  = sorted(set(f.data[2] >> 4 for f in frames_430))
    b0_vals     = sorted(set(f.data[0] for f in frames_430))
    b2_vals     = sorted(set(f.data[2] for f in frames_430))

    lines.append(f'  B0 unique raw values: {b0_vals}')
    lines.append(f'  B0 upper nibbles:     {b0_nibbles}')
    lines.append(f'  B2 unique raw values: {b2_vals}')
    lines.append(f'  B2 upper nibbles:     {b2_nibbles}')

    # 12-bit fields (mask upper nibble)
    v01 = [(f.data[0] & 0x0F) * 256 + f.data[1] for f in frames_430]
    v23 = [(f.data[2] & 0x0F) * 256 + f.data[3] for f in frames_430]
    spread = [a - b for a, b in zip(v01, v23)]

    lines.append(f'  12-bit B0-B1 masked: min={min(v01)}  max={max(v01)}  (mV at 1mV/cnt)')
    lines.append(f'  12-bit B2-B3 masked: min={min(v23)}  max={max(v23)}  (mV at 1mV/cnt)')
    lines.append(f'  Spread (B01-B23):    min={min(spread)}  max={max(spread)}  mean={sum(spread)/len(spread):.1f}')

    # Show first 10 and last 10 raw frames
    lines.append('  First 10 raw 0x430 frames:')
    for f in frames_430[:10]:
        d = f.data
        v01f = (d[0] & 0x0F) * 256 + d[1]
        v23f = (d[2] & 0x0F) * 256 + d[3]
        lines.append(f'    t={f.timestamp:8.2f}  '
                     f'raw={" ".join(f"{x:02X}" for x in d[:8])}  '
                     f'B0hi={d[0]>>4:X} B2hi={d[2]>>4:X}  '
                     f'v01={v01f} v23={v23f} spread={v01f-v23f}')
    lines.append('  Last 10 raw 0x430 frames:')
    for f in frames_430[-10:]:
        d = f.data
        v01f = (d[0] & 0x0F) * 256 + d[1]
        v23f = (d[2] & 0x0F) * 256 + d[3]
        lines.append(f'    t={f.timestamp:8.2f}  '
                     f'raw={" ".join(f"{x:02X}" for x in d[:8])}  '
                     f'B0hi={d[0]>>4:X} B2hi={d[2]>>4:X}  '
                     f'v01={v01f} v23={v23f} spread={v01f-v23f}')

txt = '\n'.join(lines)
print(txt)
with open(OUT, 'w', encoding='ascii', errors='replace') as fh:
    fh.write(txt)
print(f'\nSaved: {OUT}')
