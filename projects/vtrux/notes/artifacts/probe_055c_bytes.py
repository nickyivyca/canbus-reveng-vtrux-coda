"""
Extract all unique 0x055C frames from Vtrux and Coda logs.
Goal: determine actual DLC and which byte(s) are active.
"""
import sys
sys.path.insert(0, '.')
from canre.parsers.autodetect import parse_file

VTRUX_LOGS = [
    'projects/vtrux/logs/vtrux_shifter_disconnect.log',
    'projects/vtrux/logs/generator on then off.log',
]
CODA_LOGS = [
    'projects/coda/logs/codadriveslowturnonwithdefroster.log',
    'projects/coda/logs/driverinputpart2.log',
    'projects/coda/logs/frombonnydoon.log',
]

TARGET_ID = 0x055C

def analyze(label, log_path):
    print(f'\n=== {label}: {log_path} ===')
    try:
        frames = list(parse_file(log_path))
    except Exception as e:
        print(f'  ERROR: {e}')
        return
    matches = [f for f in frames if f.arbitration_id == TARGET_ID]
    if not matches:
        print('  No 0x055C frames found')
        return
    print(f'  Total frames: {len(matches)}, first t={matches[0].timestamp:.3f}s, last t={matches[-1].timestamp:.3f}s')
    seen = {}
    for f in matches:
        key = bytes(f.data)
        if key not in seen:
            seen[key] = (f.timestamp, 0)
        seen[key] = (seen[key][0], seen[key][1] + 1)
    print(f'  Unique byte patterns ({len(seen)}):')
    for data, (t_first, count) in sorted(seen.items(), key=lambda x: x[1][0]):
        dlc = len(data)
        hex_bytes = ' '.join(f'{b:02X}' for b in data)
        print(f'    [{hex_bytes}]  DLC={dlc}  count={count:5d}  first_t={t_first:.3f}s')
    print()
    transitions = []
    prev_key = None
    for f in matches:
        key = bytes(f.data)
        if key != prev_key:
            hex_bytes = ' '.join(f'{b:02X}' for b in f.data)
            transitions.append((f.timestamp, hex_bytes))
            prev_key = key
    print(f'  Transitions ({len(transitions)}):')
    for t, h in transitions:
        print(f'    t={t:8.3f}s  [{h}]')

for path in VTRUX_LOGS:
    analyze('Vtrux', path)

for path in CODA_LOGS:
    analyze('Coda', path)
