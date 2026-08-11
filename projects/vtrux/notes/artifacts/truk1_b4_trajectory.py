"""
truk1_b4_trajectory.py

Scan all truk1log M1 chunks (T0-T18), extract per-chunk stats for:
  - 0x410 B4  : V_min candidate (regression: V = 6.370*B4 + 2248 mV)
  - 0x410 B3  : temperature / slow-drift candidate
  - 0x440 B3+B4*256 LE * 0.0156 : V_pack (HV voltage)
  - 0x420 B3  : secondary cell voltage candidate

Outputs a summary table and a CSV for plotting.
"""
import sys, os, glob, statistics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file

LOG_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')
OUT_CSV  = os.path.join(os.path.dirname(__file__), 'truk1_b4_trajectory.csv')

# Regression from climit log bisect correlation
B4_SLOPE     = 6.370   # mV per count
B4_INTERCEPT = 2248.0  # mV

# 0x440 B3-B4 LE scale factor (confirmed from interlock test)
VPACK_SCALE  = 0.0156   # V per count
CELLS        = 117

def v_min_est(b4):
    return B4_SLOPE * b4 + B4_INTERCEPT

def chunk_num(path):
    base = os.path.basename(path)
    # truk1log_M1_T{n}.log
    try:
        return int(base.split('_T')[1].replace('.log', ''))
    except Exception:
        return 99

def analyze_chunk(path):
    b4_vals, b3_vals, b3_420, vpack_vals = [], [], [], []
    for frame in parse_file(path):
        if frame.arbitration_id == 0x410 and len(frame.data) >= 5:
            b4_vals.append(frame.data[4])
            b3_vals.append(frame.data[3])
        elif frame.arbitration_id == 0x440 and len(frame.data) >= 5:
            le = frame.data[3] + frame.data[4] * 256
            vpack_vals.append(le * VPACK_SCALE)
        elif frame.arbitration_id == 0x420 and len(frame.data) >= 4:
            b3_420.append(frame.data[3])

    def med(lst): return statistics.median(lst) if lst else float('nan')
    def avg(lst): return statistics.mean(lst) if lst else float('nan')
    def mn(lst):  return min(lst) if lst else float('nan')
    def mx(lst):  return max(lst) if lst else float('nan')
    def uniq(lst): return len(set(lst)) if lst else 0

    b4_med  = med(b4_vals)
    b3_med  = med(b3_vals)
    vp_med  = med(vpack_vals)
    b3420_med = med(b3_420)

    return {
        'b4_med':    b4_med,
        'b4_min':    mn(b4_vals),
        'b4_max':    mx(b4_vals),
        'b4_uniq':   uniq(b4_vals),
        'vmin_est':  v_min_est(b4_med),
        'b3_med':    b3_med,
        'vpack_med': vp_med,
        'vavg_med':  vp_med / CELLS * 1000 if vp_med == vp_med else float('nan'),
        'b3420_med': b3420_med,
        'n_410':     len(b4_vals),
        'n_440':     len(vpack_vals),
    }

def main():
    pattern = os.path.join(LOG_DIR, 'truk1log_M1_T*.log')
    paths = sorted(glob.glob(pattern), key=chunk_num)

    if not paths:
        print(f'No files found matching {pattern}')
        return

    print(f'Found {len(paths)} chunks')
    print()

    header = ('Chunk | n_410 | B4_med | B4_min | B4_max | B4_uniq | '
              'Vmin_est(mV) | Vpack(V) | Vavg(mV) | B3_med | B3420_med')
    print(header)
    print('-' * len(header))

    rows = []
    for path in paths:
        c = chunk_num(path)
        r = analyze_chunk(path)
        line = (f'  T{c:02d}  | {r["n_410"]:5d} | {r["b4_med"]:6.1f} | '
                f'{r["b4_min"]:6.0f} | {r["b4_max"]:6.0f} | {r["b4_uniq"]:7d} | '
                f'{r["vmin_est"]:11.1f} | {r["vpack_med"]:8.2f} | '
                f'{r["vavg_med"]:8.1f} | {r["b3_med"]:6.1f} | {r["b3420_med"]:9.1f}')
        print(line)
        rows.append((c, r))

    # Write CSV
    with open(OUT_CSV, 'w') as f:
        f.write('chunk,b4_med,b4_min,b4_max,b4_uniq,vmin_est_mV,vpack_V,vavg_mV,b3_med,b3420_med,n_410\n')
        for c, r in rows:
            f.write(f'{c},{r["b4_med"]:.2f},{r["b4_min"]},{r["b4_max"]},{r["b4_uniq"]},'
                    f'{r["vmin_est"]:.1f},{r["vpack_med"]:.3f},{r["vavg_med"]:.1f},'
                    f'{r["b3_med"]:.2f},{r["b3420_med"]:.2f},{r["n_410"]}\n')

    print()
    print(f'CSV written to: {OUT_CSV}')

    # Delta summary
    if rows:
        first_b4 = rows[0][1]['b4_med']
        last_b4  = rows[-1][1]['b4_med']
        first_vp = rows[0][1]['vpack_med']
        last_vp  = rows[-1][1]['vpack_med']
        print()
        print(f'B4 trajectory:   T0={first_b4:.1f} -> T18={last_b4:.1f}  '
              f'(delta={last_b4-first_b4:+.1f} counts = '
              f'{(last_b4-first_b4)*B4_SLOPE:+.0f} mV)')
        print(f'Vpack trajectory: T0={first_vp:.2f}V -> T18={last_vp:.2f}V  '
              f'(delta={last_vp-first_vp:+.2f}V)')
        if first_vp and last_vp:
            print(f'Vavg trajectory:  T0={first_vp/CELLS*1000:.1f} -> '
                  f'T18={last_vp/CELLS*1000:.1f} mV/cell '
                  f'(delta={( last_vp-first_vp)/CELLS*1000:+.1f} mV/cell)')

if __name__ == '__main__':
    main()
