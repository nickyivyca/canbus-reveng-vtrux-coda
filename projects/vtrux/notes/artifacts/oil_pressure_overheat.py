"""
Oil pressure vs thermal signals -- generator and drivetrain overheat logs
=========================================================================
Phases:
  derate_check  -- find exact ThermInd_pct value when generator torque derate begins
  plot          -- side-by-side oil pressure plot for both overheat logs
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

import cantools
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

from canre.parsers import parse_file

DBC_PT  = r'projects/vtrux/epri-pt-bus.dbc'
LOG_GEN = r'projects/vtrux/logs/vtruxgeneratoroverheattest.log'
LOG_DRV = r'projects/vtrux/logs/vtruxdrivetrainoverheattest.log'

PHASE = sys.argv[1] if len(sys.argv) > 1 else 'derate_check'

db = cantools.database.load_file(DBC_PT, strict=False)
msg_0599 = db.get_message_by_name('EPRI_HCU_VIRTSENS_5_Pressures_0599')
msg_0479 = db.get_message_by_name('EPRI_MCU_Thermal1_0479')


# ---------------------------------------------------------------------------
def collect_gen(log_path):
    """Collect signals from generator overheat log."""
    out = {
        'press_t': [], 'gene_press': [], 'trac_press': [],
        'therm_t': [], 'therm_pct': [],
        'rpm_t':   [], 'rpm_v':     [],    # 0x054 gen RPM (no overflow)
        'torq_t':  [], 'torq_v':    [],    # 0x051 gen torque cmd
        'obd_rpm_t': [], 'obd_rpm_v': [],  # OBD Engine_Speed (real RPM)
    }
    # identify PT bus by 0x051
    pt_ch = None
    for frame in parse_file(log_path):
        if frame.arbitration_id == 0x051:
            pt_ch = frame.bus
            break

    # identify OBD bus by 0x044
    obd_ch = None
    for frame in parse_file(log_path):
        if frame.arbitration_id == 0x044:
            obd_ch = frame.bus
            break

    for frame in parse_file(log_path):
        t   = frame.timestamp
        aid = frame.arbitration_id
        d   = frame.data

        if frame.bus == pt_ch:
            if aid == 0x0599 and len(d) >= 6:
                padded = bytes(d[:8]) if len(d) >= 8 else bytes(d) + b'\x00' * (8 - len(d))
                dec = msg_0599.decode(padded, decode_choices=False)
                out['press_t'].append(t)
                out['gene_press'].append(dec['GeneOilPress'])
                out['trac_press'].append(dec['TracOilPress'])

            elif aid == 0x0479 and len(d) >= 3:
                padded = bytes(d[:4]) if len(d) >= 4 else bytes(d) + b'\x00' * (4 - len(d))
                dec = msg_0479.decode(padded, decode_choices=False)
                out['therm_t'].append(t)
                out['therm_pct'].append(dec['GENE_ThermInd_pct'])

            elif aid == 0x054 and len(d) >= 2:
                raw = (d[1] << 8) | d[0]
                out['rpm_t'].append(t)
                out['rpm_v'].append(raw - 32768)

            elif aid == 0x051 and len(d) >= 3:
                raw = (d[2] << 8) | d[1]
                out['torq_t'].append(t)
                out['torq_v'].append(raw - 32768)

        elif frame.bus == obd_ch:
            if aid == 0x0C9 and len(d) >= 3:
                raw = (d[1] << 8) | d[2]
                out['obd_rpm_t'].append(t)
                out['obd_rpm_v'].append(raw * 0.25)

    for k in out:
        out[k] = np.array(out[k])
    return out


def collect_drv(log_path):
    """Collect signals from drivetrain overheat log."""
    out = {
        'press_t':      [], 'gene_press': [], 'trac_press': [],
        'therm_t':      [], 'therm_raw':  [],   # 0x06000002 10-bit TRAC thermal proxy (PT bus)
        'trac_therm_t': [], 'trac_therm_pct': [], # 0x44A B2 TRAC_ThermInd_pct (OBD bus, confirmed scale)
        'torq_t':       [], 'torq_v':     [],   # 0x5A2 B4-B5 traction torque
        'rpm_t':        [], 'rpm_v':      [],   # 0x5A2 B2-B3 traction RPM
    }
    pt_ch = None
    for frame in parse_file(log_path):
        if frame.arbitration_id == 0x051:
            pt_ch = frame.bus
            break

    obd_ch = None
    for frame in parse_file(log_path):
        if frame.arbitration_id == 0x044:
            obd_ch = frame.bus
            break

    for frame in parse_file(log_path):
        t   = frame.timestamp
        aid = frame.arbitration_id
        d   = frame.data

        if frame.bus == pt_ch:
            if aid == 0x0599 and len(d) >= 6:
                padded = bytes(d[:8]) if len(d) >= 8 else bytes(d) + b'\x00' * (8 - len(d))
                dec = msg_0599.decode(padded, decode_choices=False)
                out['press_t'].append(t)
                out['gene_press'].append(dec['GeneOilPress'])
                out['trac_press'].append(dec['TracOilPress'])

            elif aid == 0x06000002 and len(d) >= 7:
                raw10 = (d[6] << 2) | (d[5] >> 6)
                out['therm_t'].append(t)
                out['therm_raw'].append(raw10)

            elif aid == 0x5A2 and len(d) >= 6:
                torq_raw = (d[5] << 8) | d[4]
                rpm_raw  = (d[3] << 8) | d[2]
                out['torq_t'].append(t)
                out['torq_v'].append(torq_raw - 32768)
                out['rpm_t'].append(t)
                out['rpm_v'].append(rpm_raw - 32768)

        elif frame.bus == obd_ch:
            if aid == 0x044A and len(d) >= 3:
                pct = d[2] * 0.78125
                out['trac_therm_t'].append(t)
                out['trac_therm_pct'].append(pct)

    for k in out:
        out[k] = np.array(out[k])
    return out


# ---------------------------------------------------------------------------
if PHASE == 'derate_check':
    # Known event times from investigation notes
    GEN_EVENT_T = 1930.9   # RPM peak / derate event in generator overheat log
    DRV_EVENT_T = 1953.0   # Torque cutback onset in drivetrain overheat log
    WIN = 120.0             # seconds either side to print

    def print_window(label, t_arr, v_arr, event_t, win, v_label, step=10.0):
        mask = (t_arr >= event_t - win) & (t_arr <= event_t + win)
        tw = t_arr[mask]; vw = v_arr[mask]
        print(f'\n{label} (event t={event_t:.1f}s, window +/-{win:.0f}s):')
        prev = -9999.0
        for t, v in zip(tw, vw):
            if t - prev >= step:
                marker = ' <-- event' if abs(t - event_t) < step else ''
                print(f'  t={t:8.1f}s  {v_label}={v:7.2f}{marker}')
                prev = t
        if vw.size:
            idx = int(np.argmin(np.abs(tw - event_t)))
            print(f'  => at event: {vw[idx]:.2f}  |  range in window: {vw.min():.2f} -- {vw.max():.2f}')

    # ---- Generator overheat log ----
    print('=' * 60)
    print('GENERATOR OVERHEAT LOG')
    print('=' * 60)
    print('Parsing...')
    g = collect_gen(LOG_GEN)
    print(f'  ThermInd frames: {g["therm_t"].size}  torque frames: {g["torq_t"].size}')

    print_window('GENE_ThermInd_pct', g['therm_t'], g['therm_pct'], GEN_EVENT_T, WIN, 'ThermInd_%')
    print_window('Gen torque cmd (0x051, centered at 0)',
                 g['torq_t'], g['torq_v'], GEN_EVENT_T, WIN, 'torque')

    # ---- Drivetrain overheat log ----
    print('\n' + '=' * 60)
    print('DRIVETRAIN OVERHEAT LOG')
    print('=' * 60)
    print('Parsing...')
    dv = collect_drv(LOG_DRV)
    print(f'  therm_raw frames: {dv["therm_t"].size}  torque frames: {dv["torq_t"].size}')

    print(f'  0x44A OBD ThermInd frames: {dv["trac_therm_t"].size}')
    print_window('TRAC_ThermInd_pct (0x44A B2, OBD bus, confirmed scale)',
                 dv['trac_therm_t'], dv['trac_therm_pct'], DRV_EVENT_T, WIN, 'ThermInd_%')
    print_window('TRAC thermal proxy (0x06000002 10-bit raw, PT bus, scale unconfirmed)',
                 dv['therm_t'], dv['therm_raw'], DRV_EVENT_T, WIN, 'raw10')
    print_window('Traction torque feedback (0x5A2 B4-B5, centered at 0)',
                 dv['torq_t'], dv['torq_v'], DRV_EVENT_T, WIN, 'torque')

    sys.exit(0)


# ---------------------------------------------------------------------------
elif PHASE == 'plot':
    print('Parsing generator overheat log...')
    g = collect_gen(LOG_GEN)
    print(f'  press={g["press_t"].size}  therm={g["therm_t"].size}  RPM={g["rpm_t"].size}  OBD RPM={g["obd_rpm_t"].size}')

    print('Parsing drivetrain overheat log...')
    dv = collect_drv(LOG_DRV)
    print(f'  press={dv["press_t"].size}  therm={dv["therm_t"].size}  torque={dv["torq_t"].size}')

    fig = plt.figure(figsize=(18, 14))
    fig.suptitle('Motor Oil Pressures (0x0599) -- Generator and Drivetrain Overheat Logs\n'
                 'Left: vtruxgeneratoroverheattest   Right: vtruxdrivetrainoverheattest',
                 fontsize=11)
    gs = gridspec.GridSpec(3, 2, hspace=0.42, wspace=0.30)

    # ---- Left: generator overheat ----
    ax_pg = fig.add_subplot(gs[0, 0])
    ax_tg = fig.add_subplot(gs[1, 0], sharex=ax_pg)
    ax_rg = fig.add_subplot(gs[2, 0], sharex=ax_pg)

    if g['press_t'].size:
        ax_pg.plot(g['press_t'], g['gene_press'], color='firebrick', lw=1.0, label='GeneOilPress')
        ax_pg.plot(g['press_t'], g['trac_press'], color='steelblue', lw=1.0, label='TracOilPress')
    ax_pg.set_ylabel('kPa')
    ax_pg.set_title('Oil Pressures (generator overheat)')
    ax_pg.legend(fontsize=7)
    ax_pg.grid(True, alpha=0.3)

    if g['therm_t'].size:
        ax_tg.plot(g['therm_t'], g['therm_pct'], color='purple', lw=1.2, label='GENE_ThermInd_pct (0x479 B2)')
    ax_tg.axhline(80, color='red', lw=0.8, linestyle='--', label='80%')
    ax_tg.set_ylim(-5, 110)
    ax_tg.set_ylabel('%')
    ax_tg.set_title('GENE ThermInd_pct')
    ax_tg.legend(fontsize=7)
    ax_tg.grid(True, alpha=0.3)

    if g['rpm_t'].size:
        ax_rg.plot(g['rpm_t'], g['rpm_v'], color='steelblue', lw=0.7, alpha=0.6, label='GENE RPM (0x054)')
    if g['obd_rpm_t'].size:
        ax_rg.plot(g['obd_rpm_t'], g['obd_rpm_v'], color='navy', lw=0.9, label='OBD Engine_Speed')
    ax_rg.set_ylabel('RPM')
    ax_rg.set_title('Generator RPM')
    ax_rg.legend(fontsize=7)
    ax_rg.grid(True, alpha=0.3)
    ax_rg.set_xlabel('Log time (s)')

    # ---- Right: drivetrain overheat ----
    ax_pd = fig.add_subplot(gs[0, 1])
    ax_td = fig.add_subplot(gs[1, 1], sharex=ax_pd)
    ax_qd = fig.add_subplot(gs[2, 1], sharex=ax_pd)

    if dv['press_t'].size:
        ax_pd.plot(dv['press_t'], dv['gene_press'], color='firebrick', lw=1.0, label='GeneOilPress')
        ax_pd.plot(dv['press_t'], dv['trac_press'], color='steelblue', lw=1.0, label='TracOilPress')
    ax_pd.set_ylabel('kPa')
    ax_pd.set_title('Oil Pressures (drivetrain overheat)')
    ax_pd.legend(fontsize=7)
    ax_pd.grid(True, alpha=0.3)

    if dv['therm_t'].size:
        ax_td.plot(dv['therm_t'], dv['therm_raw'], color='green', lw=1.0,
                   label='0x06000002 10-bit (TRAC thermal proxy)')
    ax_td.set_ylabel('raw (10-bit)')
    ax_td.set_title('TRAC ThermInd proxy (0x06000002 B5/B6)')
    ax_td.legend(fontsize=7)
    ax_td.grid(True, alpha=0.3)

    if dv['torq_t'].size:
        ax_qd.plot(dv['torq_t'], dv['torq_v'], color='darkorange', lw=0.7,
                   label='Traction torque (0x5A2 B4-B5)')
        ax_qd.axhline(0, color='black', lw=0.5)
    ax_qd.set_ylabel('raw - 32768')
    ax_qd.set_title('Traction Torque Feedback')
    ax_qd.legend(fontsize=7)
    ax_qd.grid(True, alpha=0.3)
    ax_qd.set_xlabel('Log time (s)')

    OUT = r'projects/vtrux/notes/artifacts/oil_pressure_overheat.png'
    plt.savefig(OUT, dpi=150, bbox_inches='tight')
    print(f'Saved: {OUT}')
