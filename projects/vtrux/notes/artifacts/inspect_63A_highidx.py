"""
inspect_63A_highidx.py

Dump raw 0x63A frame bytes at various cluster indices from the climit log.
Purpose: check whether high-index frames really have B2 bit7=1 and what the
other bytes look like -- to determine if 'is_volt' detection is correct and
if the encoding changes at high indices.
"""
import sys, os, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

CLIMIT = os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                      'vtruxcurrentlimitingtest.log')
OUT = os.path.join(os.path.dirname(__file__), 'inspect_63A_highidx_output.txt')

# Show sample frames for these cluster indices
SHOW_INDICES = [12, 13, 14, 15, 16, 20, 25, 30, 40, 45, 50, 51]
SAMPLES_PER_IDX = 5

lines = []
lines.append('=== 0x63A High-Index Frame Inspection (climit log) ===')
lines.append('Cluster index = B2 & 0x7F; is_volt = B2 bit7')
lines.append('')

# Collect frames grouped by cluster index
by_idx = collections.defaultdict(list)
t_off, last_t = 0.0, None

for frame in parse_file(CLIMIT):
    t = frame.timestamp
    if last_t is not None and t < last_t - 1.0:
        t_off += last_t
    last_t = t
    ct = t + t_off

    if frame.arbitration_id != 0x63A or len(frame.data) < 3:
        continue

    b2 = frame.data[2]
    b2_lower = b2 & 0x7F
    is_volt = bool(b2 & 0x80)
    by_idx[b2_lower].append((ct, is_volt, bytes(frame.data)))

# Per-index summary
lines.append('Per-index summary (voltage frames only, B2 bit7=1):')
lines.append(f'  {"idx":>4}  {"n_volt":>8}  {"n_nonvolt":>10}  {"B1_min":>6}  {"B1_max":>6}  {"B1_median":>9}  {"V_min_mV":>8}  {"V_max_mV":>8}')
lines.append('  ' + '-'*75)

import statistics
for idx in sorted(by_idx.keys()):
    frames = by_idx[idx]
    volt = [(ct, data) for ct, is_v, data in frames if is_v]
    nonvolt = [(ct, data) for ct, is_v, data in frames if not is_v]
    if not volt:
        continue
    b1s = [data[1] for ct, data in volt]
    raws = [data[1] + data[2]*256 for ct, data in volt]
    vmvs = [r * 0.1 for r in raws]
    lines.append(f'  {idx:>4}  {len(volt):>8}  {len(nonvolt):>10}  '
                 f'{min(b1s):>6}  {max(b1s):>6}  {statistics.median(b1s):>9.0f}  '
                 f'{min(vmvs):>8.1f}  {max(vmvs):>8.1f}')

lines.append('')

# Sample raw frame bytes at target indices
for idx in SHOW_INDICES:
    if idx not in by_idx:
        lines.append(f'idx={idx}: no frames')
        continue
    volt = [(ct, data) for ct, is_v, data in by_idx[idx] if is_v]
    nonvolt = [(ct, data) for ct, is_v, data in by_idx[idx] if not is_v]

    lines.append(f'idx={idx}: {len(volt)} volt frames, {len(nonvolt)} non-volt frames')

    if volt:
        lines.append(f'  Volt frames (B2 bit7=1) -- sample of up to {SAMPLES_PER_IDX}:')
        step = max(1, len(volt) // SAMPLES_PER_IDX)
        for i in range(0, min(len(volt), SAMPLES_PER_IDX * step), step):
            ct, data = volt[i]
            raw = data[1] + data[2]*256
            vmv = raw * 0.1
            hex_str = ' '.join(f'{b:02X}' for b in data)
            lines.append(f'    t={ct:8.2f}s  [{hex_str}]  '
                         f'B0={data[0]:3d}=0x{data[0]:02X}  B1={data[1]:3d}  B2={data[2]:3d}=0x{data[2]:02X}  '
                         f'raw={raw}  V={vmv:.1f} mV')

    if nonvolt:
        lines.append(f'  Non-volt frames (B2 bit7=0) -- sample of up to {SAMPLES_PER_IDX}:')
        step = max(1, len(nonvolt) // SAMPLES_PER_IDX)
        for i in range(0, min(len(nonvolt), SAMPLES_PER_IDX * step), step):
            ct, data = nonvolt[i]
            hex_str = ' '.join(f'{b:02X}' for b in data)
            lines.append(f'    t={ct:8.2f}s  [{hex_str}]  '
                         f'B0={data[0]:3d}=0x{data[0]:02X}  B1={data[1]:3d}  B2={data[2]:3d}=0x{data[2]:02X}')
    lines.append('')

# Also: for idx=12 volt frames, what does B3-B7 look like?
# Compare idx=12 vs idx=51 to see if there are structural differences
lines.append('--- B3-B7 comparison: idx=12 vs idx=51 volt frames ---')
for idx in [12, 51]:
    if idx not in by_idx:
        continue
    volt = [(ct, data) for ct, is_v, data in by_idx[idx] if is_v]
    if not volt:
        continue
    lines.append(f'idx={idx} ({len(volt)} volt frames):')
    for bpos in range(3, 8):
        bvals = [data[bpos] for ct, data in volt if len(data) > bpos]
        if not bvals:
            continue
        uniq = len(set(bvals))
        med = statistics.median(bvals)
        lines.append(f'  B{bpos}: min={min(bvals)} max={max(bvals)} median={med:.0f} unique={uniq}')

output = '\n'.join(lines)
print(output)
with open(OUT, 'w') as f:
    f.write(output + '\n')
print(f'\nOutput written to: {OUT}')
