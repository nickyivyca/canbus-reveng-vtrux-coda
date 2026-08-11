"""
bcm_fgd investigation -- determine the meaning of the bcm_fgd signal (0x0440 B1).
Run from project root: py -3.12 projects/vtrux/notes/artifacts/bcm_fgd_investigation.py <phase>
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')


def phase_b1_survey():
    """
    Survey bcm_fgd (0x440 B1) across multiple logs to understand when it has valid
    (non-sentinel) values, what those values are, and whether they vary.

    Sentinel: raw >= 0xFE  (i.e., 0xFE and 0xFF are invalid)
    Scale: raw * 0.5 %
    """
    logs = [
        ('vtruxisolationtest',       'projects/vtrux/logs/vtruxisolationtest.log'),
        ('rainychargedebug',         'projects/vtrux/logs/rainychargedebug.log'),
        ('truk1log_M1_T14',          'projects/vtrux/logs/truk1log_M1_T14.log'),
        ('vtruxevapdrivelog',        'projects/vtrux/logs/vtruxevapdrivelog.log'),
        ('oghighwaydrive',           'projects/vtrux/logs/oghighwaydrive.log'),
        ('vtruxcurrentlimitingtest', 'projects/vtrux/logs/vtruxcurrentlimitingtest.log'),
        ('vtruxpartstruck',          'projects/vtrux/logs/vtruxpartstruck.log'),
        ('movingaroundindriveway',   'projects/vtrux/logs/movingaroundindriveway.log'),
        ('vtruxinterlocktest',       'projects/vtrux/logs/vtruxinterlocktest.log'),
    ]

    for name, rel_path in logs:
        path = os.path.join(ROOT, rel_path)
        if not os.path.exists(path):
            print(f'{name}: FILE NOT FOUND')
            continue
        try:
            frames_440 = [f for f in parse_file(path) if f.arbitration_id == 0x440]
            if not frames_440:
                print(f'{name}: no 0x440 frames')
                continue
            b1_vals = [f.data[1] for f in frames_440 if len(f.data) > 1]
            all_unique = sorted(set(b1_vals))
            non_sentinel = [v for v in b1_vals if v < 0xFE]
            print(f'{name}: {len(frames_440)} frames, B1 unique={all_unique[:15]}, '
                  f'non-sentinel count={len(non_sentinel)}, '
                  f'non-sentinel values={sorted(set(non_sentinel))}')
        except Exception as e:
            print(f'{name}: ERROR {e}')


def phase_b1_timeseries(log_name='rainychargedebug'):
    """
    Print the bcm_fgd timeseries (timestamp, raw, value_pct) for a specific log.
    Only prints rows where the value changes or is non-sentinel.
    """
    log_map = {
        'rainychargedebug':   'projects/vtrux/logs/rainychargedebug.log',
        'truk1log_M1_T14':    'projects/vtrux/logs/truk1log_M1_T14.log',
        'vtruxisolationtest': 'projects/vtrux/logs/vtruxisolationtest.log',
    }
    path = os.path.join(ROOT, log_map.get(log_name, log_name))
    frames_440 = [f for f in parse_file(path) if f.arbitration_id == 0x440 and len(f.data) > 1]
    prev_b1 = None
    for f in frames_440:
        b1 = f.data[1]
        if b1 != prev_b1:
            sentinel = '*SENTINEL*' if b1 >= 0xFE else f'{b1 * 0.5:.1f}%'
            print(f't={f.timestamp:.3f}s  raw={b1:#04x} ({b1})  fgd={sentinel}')
            prev_b1 = b1


def phase_b1_vs_soc(log_name='rainychargedebug'):
    """
    Compare bcm_fgd (0x440 B1) with bcm_soc (0x410 B?) to check if fgd tracks SOC.
    Also compare with bcm_balancing_cnt (0x440 B7).
    """
    import cantools
    dbc_path = os.path.join(ROOT, 'projects/vtrux/epri-pt-bus.dbc')
    db = cantools.db.load_file(dbc_path)

    log_map = {
        'rainychargedebug':   'projects/vtrux/logs/rainychargedebug.log',
        'truk1log_M1_T14':    'projects/vtrux/logs/truk1log_M1_T14.log',
        'vtruxisolationtest': 'projects/vtrux/logs/vtruxisolationtest.log',
    }
    path = os.path.join(ROOT, log_map.get(log_name, log_name))

    soc_vals = {}
    fgd_vals = {}
    balcnt_vals = {}

    for f in parse_file(path):
        if f.arbitration_id == 0x410:
            try:
                decoded = db.decode_message(0x410, bytes(f.data))
                if 'bcm_soc' in decoded:
                    soc_vals[f.timestamp] = decoded['bcm_soc']
            except Exception:
                pass
        elif f.arbitration_id == 0x440:
            if len(f.data) > 1:
                b1 = f.data[1]
                if b1 < 0xFE:
                    fgd_vals[f.timestamp] = b1 * 0.5
            if len(f.data) > 7:
                b7 = f.data[7]
                if b7 < 0xFE:
                    balcnt_vals[f.timestamp] = b7

    if not fgd_vals:
        print(f'No valid bcm_fgd values in {log_name}')
    else:
        fgd_list = sorted(fgd_vals.items())
        print(f'bcm_fgd: {len(fgd_list)} valid frames, '
              f'range={min(v for _, v in fgd_list):.1f}% to {max(v for _, v in fgd_list):.1f}%')
        for t, v in fgd_list[:20]:
            print(f'  t={t:.3f}  fgd={v:.1f}%')

    if soc_vals:
        soc_list = sorted(soc_vals.items())
        print(f'bcm_soc: range={min(v for _, v in soc_list):.1f} to {max(v for _, v in soc_list):.1f}')

    if balcnt_vals:
        balcnt_list = sorted(balcnt_vals.items())
        print(f'bcm_balancing_cnt: unique={sorted(set(v for _, v in balcnt_list))}')


if __name__ == '__main__':
    phase = sys.argv[1] if len(sys.argv) > 1 else 'b1_survey'
    if phase == 'b1_survey':
        phase_b1_survey()
    elif phase == 'b1_timeseries':
        log = sys.argv[2] if len(sys.argv) > 2 else 'rainychargedebug'
        phase_b1_timeseries(log)
    elif phase == 'b1_vs_soc':
        log = sys.argv[2] if len(sys.argv) > 2 else 'rainychargedebug'
        phase_b1_vs_soc(log)
    else:
        print(f'Unknown phase: {phase}')
        print('Available: b1_survey, b1_timeseries [log], b1_vs_soc [log]')
