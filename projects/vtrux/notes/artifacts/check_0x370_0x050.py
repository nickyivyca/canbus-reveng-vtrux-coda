"""
check_0x370_0x050.py -- Quick extraction to answer two questions:
  1. Are 0x370-0x375 cell group voltages or temperatures?
     Test: do values change rapidly during the t~600s discharge event (V_pack 381->341V)?
  2. Does 0x050 B2 track pack voltage (via B1-B2 LE as cell voltage)?
"""
import sys, bisect
sys.path.insert(0, '.')
from canre.parsers import parse_file

LOG = 'projects/vtrux/logs/vtruxcurrentlimitingtest.log'
OUT = 'projects/vtrux/notes/artifacts/check_0x370_0x050.txt'

print('Loading...', flush=True)
frames = list(parse_file(LOG))
pt_bus = next(b for b, ids in {f.bus: set() for f in frames}.items()
              if any(f.bus == b and f.arbitration_id == 0x051 for f in frames))
# Re-detect properly
bus_ids = {}
for f in frames:
    bus_ids.setdefault(f.bus, set()).add(f.arbitration_id)
pt_bus = next(b for b, ids in bus_ids.items() if 0x051 in ids)
print(f'PT bus = Bus {pt_bus}')

# 0x482 V_avg_ref
f482 = [(f.timestamp, f.data) for f in frames
        if f.bus == pt_bus and f.arbitration_id == 0x482 and len(f.data) >= 3]
t_482 = [t for t, _ in f482]
v_pack_arr = [d[1] + d[2]*256 for _, d in f482]
v_avg_arr = [v / 117.0 * 1000 for v in v_pack_arr]

def nearest_vpk(ts):
    idx = bisect.bisect_left(t_482, ts)
    if idx == 0: return v_pack_arr[0], v_avg_arr[0]
    if idx >= len(t_482): return v_pack_arr[-1], v_avg_arr[-1]
    if abs(t_482[idx-1]-ts) < abs(t_482[idx]-ts):
        return v_pack_arr[idx-1], v_avg_arr[idx-1]
    return v_pack_arr[idx], v_avg_arr[idx]

lines = []
lines.append('=== 0x370-0x375 vs 0x482 Pack Voltage ===')
lines.append('')

# ====== 0x370-0x375: check during discharge event (t=500-700s) and regen (t=700-900s) ======
for aid in [0x370, 0x371, 0x372, 0x373, 0x374, 0x375]:
    flist = [(f.timestamp, f.data) for f in frames
             if f.bus == pt_bus and f.arbitration_id == aid and len(f.data) >= 8]
    if not flist:
        lines.append(f'  0x{aid:03X}: no frames found')
        continue
    lines.append(f'--- 0x{aid:03X}: {len(flist)} frames at {len(flist)/1810:.2f} Hz ---')
    lines.append(f'  Time     V_pack  V_avg_mV  B0  B1  B2  B3  B4  B5  B6  B7')
    # Print frames in the discharge window (500-800s) where voltage drops significantly
    discharge_frames = [(ts, d) for ts, d in flist if 500 <= ts <= 800]
    rest_frames = [(ts, d) for ts, d in flist if 0 <= ts <= 100]
    regen_frames = [(ts, d) for ts, d in flist if 600 <= ts <= 700]
    all_windows = [('rest(0-100s)', rest_frames[:10]),
                   ('discharge(500-800s)', discharge_frames[::3]),
                   ('regen(700-900s)', [(ts, d) for ts, d in flist if 700 <= ts <= 900][::3])]
    for label, wframes in all_windows:
        if not wframes:
            lines.append(f'    [{label}]: no data')
            continue
        lines.append(f'    [{label}]:')
        for ts, d in wframes[:15]:
            vp, va = nearest_vpk(ts)
            b = list(d)
            while len(b) < 8: b.append(0)
            lines.append(f'    {ts:8.1f}  {vp:7d}  {va:8.1f}  {b[0]:3d} {b[1]:3d} {b[2]:3d} {b[3]:3d} {b[4]:3d} {b[5]:3d} {b[6]:3d} {b[7]:3d}')
    lines.append('')

lines.append('')
lines.append('=== 0x050 B1/B2 vs V_pack ===')
lines.append('')
f050 = [(f.timestamp, f.data) for f in frames
        if f.bus == pt_bus and f.arbitration_id == 0x050 and len(f.data) >= 8]
print(f'  0x050 frames: {len(f050)}')

lines.append(f'0x050: {len(f050)} frames. B7=4-bit counter, B4-B6 constant.')
lines.append(f'  Checking B0, B1, B2 vs V_pack...')
lines.append(f'  {"Time":>8}  {"V_pack":>7}  {"V_avg_mV":>9}  {"B0":>4}  {"B1":>4}  {"B2":>4}  {"B1-B2-LE":>10}  {"B1B2LE*0.052":>13}')

# Sample at varied pack voltages: grab frames at different V_pack levels
step = max(1, len(f050) // 100)
seen_vpk = set()
for ts, data in f050[::step]:
    vp, va = nearest_vpk(ts)
    vp_bucket = (vp // 5) * 5  # bucket to 5V
    if vp_bucket in seen_vpk:
        continue
    seen_vpk.add(vp_bucket)
    b = list(data)
    while len(b) < 8: b.append(0)
    le16 = b[1] + b[2]*256
    lines.append(f'  {ts:8.1f}  {vp:7d}  {va:9.1f}  {b[0]:4d}  {b[1]:4d}  {b[2]:4d}  {le16:10d}  {le16*0.052:13.1f}')

lines.append('')
lines.append('--- B1 value distribution vs V_pack bucket ---')
# Group B1 values by V_pack bucket
from collections import defaultdict
b2_by_vpk = defaultdict(list)
b1_by_vpk = defaultdict(list)
le16_by_vpk = defaultdict(list)
for ts, data in f050:
    vp, va = nearest_vpk(ts)
    vp_b = (vp // 10) * 10
    if 330 <= vp <= 430:
        b = list(data)
        while len(b) < 8: b.append(0)
        b1_by_vpk[vp_b].append(b[1])
        b2_by_vpk[vp_b].append(b[2])
        le16_by_vpk[vp_b].append(b[1] + b[2]*256)

lines.append(f'  {"V_pack":>8}  {"B1_mean":>8}  {"B2_mean":>8}  {"LE16_mean":>10}  {"LE16*0.052":>11}  {"count":>6}')
for vp_b in sorted(b2_by_vpk.keys()):
    n = len(b2_by_vpk[vp_b])
    b1m = sum(b1_by_vpk[vp_b])/n
    b2m = sum(b2_by_vpk[vp_b])/n
    lem = sum(le16_by_vpk[vp_b])/n
    lines.append(f'  {vp_b:8d}  {b1m:8.2f}  {b2m:8.2f}  {lem:10.1f}  {lem*0.052:11.1f}  {n:6d}')

out = '\n'.join(lines)
print(out)
with open(OUT, 'w') as fh:
    fh.write(out)
print(f'\nSaved to {OUT}')
