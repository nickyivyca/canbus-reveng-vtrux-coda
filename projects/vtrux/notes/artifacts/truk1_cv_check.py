"""
truk1_cv_check.py -- Verify the CV charging voltage hypothesis in truk1log_M1.

Hypothesis: The parts truck battery was out of balance at the start of this
charging session. During CV charging, unbalanced cells cause the pack-level
voltage to be lower than ideal (117 * 3.6V = 421.2V) because some cells hit
the OV limit before others are fully charged. As balance improves over the
session, the CV setpoint should rise toward the ideal.

Proxy for pack voltage: 0x18FFD6B3 B4-B5 LE (DCDC HV input voltage).
  Scale from climit log: ~0.427 mV/count (per cell).
  Pack voltage: raw * 0.427 * 117 / 1000  (V)
  Ideal full charge: 3600 mV/cell * 117 = 421.2V -> raw ~= 8431 counts.

Reads all M1 chunks (T0-T18), reports per-chunk statistics, and identifies
the CV phase (window where voltage is stable at its peak value).
"""
import sys, glob, os, bisect
sys.path.insert(0, '.')
from canre.parsers import parse_file

LOG_PATTERN = 'projects/vtrux/logs/truk1log_M1_T{}.log'
N_CHUNKS    = 19  # T0 through T18
OUT         = 'projects/vtrux/notes/artifacts/truk1_cv_check.txt'

DCDC_ID  = 0x18FFD6B3
SCALE_MV = 0.427  # mV per count per cell (from climit log calibration)
N_CELLS  = 117
IDEAL_FULL_V  = 3.6 * N_CELLS          # 421.2 V
IDEAL_FULL_RAW = 3600 / SCALE_MV       # ~8431 counts

def raw_to_volts(raw):
    return raw * SCALE_MV * N_CELLS / 1000.0  # pack voltage in V

lines = []
lines.append('=== truk1log M1: DCDC HV Voltage Trajectory (CV Hypothesis Check) ===')
lines.append(f'Signal: 0x18FFD6B3 B4-B5 LE  Scale: {SCALE_MV} mV/count/cell')
lines.append(f'Ideal full charge: {IDEAL_FULL_V:.1f} V ({IDEAL_FULL_RAW:.0f} counts)')
lines.append('')
lines.append(f'  {"Chunk":<7} {"t_start":>8} {"t_end":>8} {"V_min":>7} {"V_max":>7} {"V_last":>7}  {"frames":>7}  note')
lines.append('-' * 80)

print('Processing chunks...', flush=True)

all_times  = []   # (abs_t, raw) across all chunks for CV-phase analysis
chunk_t0   = 0.0  # running absolute time offset

CV_THRESH_V   = 415.0   # anything above this = plausibly in CV phase
CV_STABLE_MV  = 2.0     # V stability window to call it "CV"

for chunk_idx in range(N_CHUNKS):
    path = LOG_PATTERN.format(chunk_idx)
    if not os.path.exists(path):
        lines.append(f'  T{chunk_idx:<6}  (file not found)')
        continue

    frames = [(f.timestamp, f.data) for f in parse_file(path)
              if f.arbitration_id == DCDC_ID and len(f.data) >= 6]

    if not frames:
        lines.append(f'  T{chunk_idx:<6}  -- no DCDC frames --')
        continue

    raws   = [d[4] + d[5]*256 for _, d in frames]
    times  = [t for t, _ in frames]
    t_span = times[-1] - times[0]

    v_min  = raw_to_volts(min(raws))
    v_max  = raw_to_volts(max(raws))
    v_last = raw_to_volts(raws[-1])

    # Accumulate for full-session view (use relative time within chunk + offset)
    for t, r in zip(times, raws):
        all_times.append((chunk_t0 + t, r))
    chunk_t0 += t_span   # advance absolute time by chunk duration

    note = ''
    if v_max >= CV_THRESH_V and (v_max - v_min) < CV_STABLE_MV:
        note = '<-- CV phase (stable high voltage)'
    elif v_max >= CV_THRESH_V:
        note = '<-- CV region (high, but varying)'

    lines.append(f'  T{chunk_idx:<6} {times[0]:8.1f} {times[-1]:8.1f} '
                 f'{v_min:7.2f} {v_max:7.2f} {v_last:7.2f}  {len(frames):7}  {note}')

# ---- Find peak CV voltage and when it occurs ----
lines.append('')
if all_times:
    abs_times, all_raws = zip(*all_times)
    peak_raw = max(all_raws)
    peak_v   = raw_to_volts(peak_raw)
    peak_t   = abs_times[all_raws.index(peak_raw)]

    # First and last time voltage is within 1V of peak
    near_peak = [(t, r) for t, r in zip(abs_times, all_raws)
                 if raw_to_volts(r) >= peak_v - 1.0]
    cv_start_t = near_peak[0][0]  if near_peak else float('nan')
    cv_end_t   = near_peak[-1][0] if near_peak else float('nan')

    lines.append(f'Peak pack voltage:  {peak_v:.2f} V  (raw={peak_raw}, at t={peak_t:.0f}s abs)')
    lines.append(f'Ideal full charge:  {IDEAL_FULL_V:.1f} V')
    lines.append(f'Gap from ideal:     {IDEAL_FULL_V - peak_v:.2f} V  ({(IDEAL_FULL_V-peak_v)/IDEAL_FULL_V*100:.1f}%)')
    lines.append(f'CV region (within 1V of peak): t={cv_start_t:.0f}s to t={cv_end_t:.0f}s '
                 f'({(cv_end_t-cv_start_t)/3600:.2f} hr)')

    # Sample voltages at start/end of CV region to see trajectory within CV
    if near_peak:
        v_at_cv_start = raw_to_volts(near_peak[0][1])
        v_at_cv_end   = raw_to_volts(near_peak[-1][1])
        lines.append(f'Voltage at CV start: {v_at_cv_start:.2f} V')
        lines.append(f'Voltage at CV end:   {v_at_cv_end:.2f} V')
        lines.append(f'CV voltage drift:    {v_at_cv_end - v_at_cv_start:+.2f} V')

out = '\n'.join(lines)
print(out)
with open(OUT, 'w') as fh:
    fh.write(out)
print(f'\nSaved to {OUT}')
