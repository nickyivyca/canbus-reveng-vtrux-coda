"""
63A_temporal_spread.py

For each cluster index, show the time distribution of voltage-type frames
in the climit log. Also show B1 values at each index to understand what
quantity is encoded.

Key question: do high-index frames appear throughout the log (tracking
an ongoing signal) or only during specific high-current events?
"""
import sys, os, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

CLIMIT = os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                      'vtruxcurrentlimitingtest.log')
OUT = os.path.join(os.path.dirname(__file__), '63A_temporal_spread_output.txt')

lines = []
lines.append('=== 0x63A Cluster Index Temporal Spread (climit log) ===')
lines.append('For each cluster index: first/last timestamp and B1 range')
lines.append('')

by_idx = collections.defaultdict(list)  # idx -> [(ct, b1)]
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
    if not (b2 & 0x80):   # only voltage-type frames
        continue
    b2_lower = b2 & 0x7F
    by_idx[b2_lower].append((ct, frame.data[1]))

lines.append(f'  {"idx":>4}  {"n":>7}  {"t_first":>9}  {"t_last":>9}  {"B1_min":>6}  {"B1_max":>6}  {"V_mV_min":>9}  {"V_mV_max":>9}')
lines.append('  ' + '-'*70)

for idx in sorted(by_idx.keys()):
    samples = by_idx[idx]
    cts = [ct for ct, b1 in samples]
    b1s = [b1 for ct, b1 in samples]
    b2val = 0x80 | idx
    v_min = (min(b1s) + b2val * 256) * 0.1
    v_max = (max(b1s) + b2val * 256) * 0.1
    lines.append(f'  {idx:>4}  {len(samples):>7}  {min(cts):>9.1f}  {max(cts):>9.1f}  '
                 f'{min(b1s):>6}  {max(b1s):>6}  {v_min:>9.1f}  {v_max:>9.1f}')

# Also: zoom in on the t=590-625s window -- show all volt frames in that range
lines.append('')
lines.append('=== Zoom: t=590-630s, all voltage frames ===')
lines.append('(This is the heavy discharge event window)')
lines.append('')
lines.append(f'  {"t":>9}  {"idx":>4}  {"B1":>4}  {"V_mV":>8}')
lines.append('  ' + '-'*30)

all_volt = []
t_off2, last_t2 = 0.0, None
for frame in parse_file(CLIMIT):
    t = frame.timestamp
    if last_t2 is not None and t < last_t2 - 1.0:
        t_off2 += last_t2
    last_t2 = t
    ct = t + t_off2
    if 590.0 <= ct <= 630.0 and frame.arbitration_id == 0x63A and len(frame.data) >= 3:
        b2 = frame.data[2]
        if b2 & 0x80:
            all_volt.append((ct, b2 & 0x7F, frame.data[1], (frame.data[1] + b2*256)*0.1))

# Show every 10th to reduce clutter
prev_idx = -1
for ct, idx, b1, vmv in all_volt[::5]:
    marker = ' <<< V drops here' if (prev_idx > idx and idx < 20) else ''
    lines.append(f'  {ct:>9.2f}  {idx:>4}  {b1:>4}  {vmv:>8.1f}{marker}')
    prev_idx = idx

output = '\n'.join(lines)
print(output)
with open(OUT, 'w') as f:
    f.write(output + '\n')
print(f'\nOutput written to: {OUT}')
