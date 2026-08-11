"""
discharge_event_zoom.py

Zoom into t=590-630s in climit log. For every 0x410, 0x420, 0x440 frame,
show raw bytes alongside V_avg. Also show 0x63A B1-B2 LE.

Goal: understand whether 0x410 B4 and 0x63A respond to current like a
measurement or a limit/model value.
"""
import sys, os, bisect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

CLIMIT = os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                      'vtruxcurrentlimitingtest.log')
OUT = os.path.join(os.path.dirname(__file__), 'discharge_event_zoom_output.txt')

ZOOM_S, ZOOM_E = 590.0, 630.0
VPACK_SCALE = 0.0156
CELLS = 117

# --- pass 1: build V_avg reference ---
vavg_ts, vavg_mv = [], []
t_off, last_t = 0.0, None
for frame in parse_file(CLIMIT):
    t = frame.timestamp
    if last_t is not None and t < last_t - 1.0:
        t_off += last_t
    last_t = t
    ct = t + t_off
    if frame.arbitration_id == 0x440 and len(frame.data) >= 5:
        le = frame.data[3] + frame.data[4] * 256
        vp = le * VPACK_SCALE
        if 200 < vp < 500:
            vavg_ts.append(ct)
            vavg_mv.append(vp / CELLS * 1000.0)

def get_vavg(t):
    pos = bisect.bisect_left(vavg_ts, t)
    best_j, best_dt = None, float('inf')
    for j in [pos-1, pos]:
        if 0 <= j < len(vavg_ts):
            dt = abs(vavg_ts[j] - t)
            if dt < best_dt:
                best_dt, best_j = dt, j
    return vavg_mv[best_j] if best_j is not None else None

# --- pass 2: collect zoom frames ---
frames_zoom = []
t_off, last_t = 0.0, None
for frame in parse_file(CLIMIT):
    t = frame.timestamp
    if last_t is not None and t < last_t - 1.0:
        t_off += last_t
    last_t = t
    ct = t + t_off
    if ZOOM_S <= ct <= ZOOM_E and frame.arbitration_id in (0x410, 0x420, 0x440, 0x63A):
        frames_zoom.append((ct, frame.arbitration_id, bytes(frame.data)))

lines = []
lines.append('=== Discharge Event Zoom t=590-630s ===')
lines.append('All BMS frames; V_avg from 0x440 B3-B4 LE')
lines.append('')
lines.append(f'  {"t":>8}  {"ID":>6}  {"B0":>3} {"B1":>3} {"B2":>3} {"B3":>3} {"B4":>3} {"B5":>3}  '
             f'{"V_avg":>8}  {"Notes"}')
lines.append('  ' + '-'*80)

prev_sec = -1
for ct, aid, data in frames_zoom:
    va = get_vavg(ct)
    va_s = f'{va:8.1f}' if va else '     n/a'

    if int(ct) > prev_sec:
        lines.append('')
        prev_sec = int(ct)

    b = list(data[:8]) + [0] * (8 - len(data))

    if aid == 0x410:
        b4_mv = 6.370 * b[4] + 2248.0
        notes = f'B4={b[4]} -> Vmin_est={b4_mv:.0f} mV  (B4-Vavg={b4_mv-va:.0f} mV)' if va else f'B4={b[4]}'
    elif aid == 0x63A and len(data) >= 3:
        raw = b[1] + b[2]*256
        idx = b[2] & 0x7F
        is_v = bool(b[2] & 0x80)
        vmv = raw * 0.1
        notes = f'B1-B2_LE={raw} -> {vmv:.1f} mV  idx={idx}  is_volt={is_v}'
    elif aid == 0x440 and len(data) >= 5:
        le = b[3] + b[4]*256
        vp = le * VPACK_SCALE
        notes = f'Vpack={vp:.2f}V -> Vavg={vp/CELLS*1000:.1f} mV'
    else:
        notes = ''

    lines.append(f'  {ct:>8.2f}  0x{aid:04X}  '
                 f'{b[0]:>3} {b[1]:>3} {b[2]:>3} {b[3]:>3} {b[4]:>3} {b[5]:>3}  '
                 f'{va_s}  {notes}')

output = '\n'.join(lines)
print(output)
with open(OUT, 'w') as f:
    f.write(output + '\n')
print(f'\nOutput written to: {OUT}')
