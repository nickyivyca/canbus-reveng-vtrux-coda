"""
63A_sweep_survey.py

For each log file, extract the 0x63A startup sweep cluster voltages.
The sweep happens at BMS power-on: a brief scan through cluster indices
(B2 lower 7 bits = cluster index), then settles to steady-state broadcasting
of one cluster (usually the highest, V_max).

For each log:
  - Show all cluster voltages seen (B2 bit7=1, B1-B2 LE * 0.1 mV)
  - Show steady-state cluster (most common B2_lower7) and its voltage
  - Include V_avg from 0x440 B3-B4 LE * 0.0156 V / 117 cells
"""
import sys, os, glob, statistics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOGS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')
SWAP_DIR = os.path.join(LOGS_DIR, 'after-battery-swap-charges')
OUT      = os.path.join(os.path.dirname(__file__), '63A_sweep_survey_output.txt')

VPACK_SCALE = 0.0156
CELLS = 117

# Log files to analyze: (label, path)
TARGETS = [
    # Original truk1log charging sessions
    ('truk1log_M1_T0',      os.path.join(LOGS_DIR, 'truk1log_M1_T0.log')),
    # After battery swap charges
    ('charge_M0_T0',        os.path.join(SWAP_DIR, 'charge_M0_T0.log')),
    ('another_M0_T1',       os.path.join(SWAP_DIR, 'another_M0_T1.log')),
    # Main vehicle logs (driving / debug) -- first chunks of each session
    ('generator',           os.path.join(LOGS_DIR, 'generator on then off.log')),
    ('climit',              os.path.join(LOGS_DIR, 'vtruxcurrentlimitingtest.log')),
    ('movingaround',        os.path.join(LOGS_DIR, 'movingaroundindriveway.log')),
    ('oghighwaydrive',      os.path.join(LOGS_DIR, 'oghighwaydrive.log')),
    ('codereading',         os.path.join(LOGS_DIR, 'vtruxcodereading.log')),
    ('evapdrive4',          os.path.join(LOGS_DIR, 'vtruxevapdrivelog4.log')),
    # Inverter fault debug sessions
    ('debuglog_M0_T0',      os.path.join(LOGS_DIR, 'debuglog_M0_T0.log')),
    ('debuglog_M1_T8',      os.path.join(LOGS_DIR, 'debuglog_M1_T8.log')),
    ('debuglog_M2_T11',     os.path.join(LOGS_DIR, 'debuglog_M2_T11.log')),
    ('debuglog_M3_T11',     os.path.join(LOGS_DIR, 'debuglog_M3_T11.log')),
    ('debuglog_M4_T20',     os.path.join(LOGS_DIR, 'debuglog_M4_T20.log')),
    ('debuglog_M5_T20',     os.path.join(LOGS_DIR, 'debuglog_M5_T20.log')),
    ('debuglog_M6_T21',     os.path.join(LOGS_DIR, 'debuglog_M6_T21.log')),
    ('debuglog_M7_T24',     os.path.join(LOGS_DIR, 'debuglog_M7_T24.log')),
    ('debuglog_M8_T24',     os.path.join(LOGS_DIR, 'debuglog_M8_T24.log')),
]


def analyze_log(label, path):
    if not os.path.exists(path):
        return f'  {label}: FILE NOT FOUND'

    cluster_voltages = {}  # B2_lower7 -> list of (B1-B2 LE) values
    cluster_steady   = {}  # B2_lower7 -> count (all frames)
    vavg_samples = []
    n_63A = 0

    try:
        t_off, last_t = 0.0, None
        for frame in parse_file(path):
            t = frame.timestamp
            if last_t is not None and t < last_t - 1.0:
                t_off += last_t
            last_t = t
            ct = t + t_off

            if frame.arbitration_id == 0x440 and len(frame.data) >= 5:
                le = frame.data[3] + frame.data[4] * 256
                vp = le * VPACK_SCALE
                if 200 < vp < 500:
                    vavg_samples.append(vp / CELLS * 1000.0)
                continue

            if frame.arbitration_id != 0x63A or len(frame.data) < 3:
                continue
            n_63A += 1

            b2 = frame.data[2]
            b2_lower = b2 & 0x7F
            is_volt = bool(b2 & 0x80)

            cluster_steady[b2_lower] = cluster_steady.get(b2_lower, 0) + 1

            if is_volt:
                le12 = frame.data[1] + b2 * 256
                mv = le12 * 0.1
                if b2_lower not in cluster_voltages:
                    cluster_voltages[b2_lower] = []
                cluster_voltages[b2_lower].append(mv)

    except Exception as e:
        return f'  {label}: ERROR -- {e}'

    if n_63A == 0:
        return f'  {label}: no 0x63A frames'

    vavg_str = (f'{statistics.median(vavg_samples):.0f}'
                if vavg_samples else 'n/a')

    lines = []
    lines.append(f'  {label}  (V_avg median={vavg_str} mV, {n_63A} 0x63A frames)')

    # Steady-state cluster (most common)
    top = sorted(cluster_steady.items(), key=lambda x: -x[1])
    ss_idx, ss_n = top[0]
    lines.append(f'    Steady-state cluster: idx={ss_idx} ({ss_n} frames)')

    # Startup sweep voltages (sorted by cluster index)
    if cluster_voltages:
        lines.append(f'    Cluster voltages (B1-B2 LE x0.1 mV):')
        for idx in sorted(cluster_voltages.keys()):
            vals = cluster_voltages[idx]
            lo, hi = min(vals), max(vals)
            med = statistics.median(vals)
            n = len(vals)
            rng = f'{lo:.1f}-{hi:.1f}' if lo != hi else f'{lo:.1f}'
            lines.append(f'      idx {idx:2d}: n={n:5d}  range {rng} mV  median={med:.1f} mV')
    else:
        lines.append('    No voltage-type frames (B2 bit7=0 throughout)')

    return '\n'.join(lines)


def main():
    lines = []
    lines.append('=== 0x63A Startup Sweep Survey ===')
    lines.append('Cluster index = B2 & 0x7F; voltage = B1-B2 LE * 0.1 mV (when B2 bit7=1)')
    lines.append('')

    for label, path in TARGETS:
        result = analyze_log(label, path)
        lines.append(result)
        lines.append('')

    output = '\n'.join(lines)
    print(output)
    with open(OUT, 'w') as f:
        f.write(output + '\n')
    print(f'\nOutput written to: {OUT}')


if __name__ == '__main__':
    main()
