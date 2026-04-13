"""
GENE MCU Thermal Signals — 0x479 EPRI DBC decoding
===================================================
Decodes 0x479 (EPRI_MCU_Thermal1_0479) using the EPRI PT-bus DBC:
  B0: GENE_DrvCoolFlowReq_pct  -- drive/inverter cooling flow request (%)
  B1: GENE_MotCoolFlowReq_pct  -- motor oil cooling flow request (%)
  B2: GENE_ThermInd_pct        -- thermal indicator (%)

Plots against:
  - Generator RPM: 0x63C B6 (overflows during overheat; overflow windows shown as dashed)
  - Engine_Speed (OBD bus, 0x0C9 B1-B2 *0.25 RPM) -- wraps around overflow
  - Generator torque cmd: 0x051 B1-B2 LE signed (centered at 32768)
  - Drivetrain motor winding temp: 0x06000002 10-bit LE, *2.0 deg C

Two logs shown side by side:
  LEFT:  vtruxgeneratorpumpunplug.log  -- normal -> pump unplug transition
  RIGHT: vtruxgeneratoroverheattest.log -- full overheat event

Phases:
  phase1: encode_check  -- print raw 0x479 frames and decoded values
  phase2: plot          -- multi-panel comparison figure
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

DBC_PATH  = r'projects/vtrux/epri-pt-bus.dbc'
LOG_UNPLUG = r'projects/vtrux/logs/vtruxgeneratorpumpunplug.log'
LOG_OVHEAT = r'projects/vtrux/logs/vtruxgeneratoroverheattest.log'

PHASE = 'plot'  # 'encode_check' or 'plot'

# ---------------------------------------------------------------------------
db = cantools.db.load_file(DBC_PATH, strict=False)
msg_0479 = db.get_message_by_name('EPRI_MCU_Thermal1_0479')
print(f'Loaded DBC. 0x479 signals: {[s.name for s in msg_0479.signals]}')


def collect(log_path):
    """Parse a log; return dict of signal arrays."""
    out = {
        'rpm_t': [], 'rpm_v': [],          # 0x63C B6 raw (pre-overflow-marked)
        'rpm_wrap': [],                      # True if this frame is in an overflow window
        'obd_rpm_t': [], 'obd_rpm_v': [],   # 0x0C9 Engine_Speed (OBD bus, real)
        'torq_t': [], 'torq_v': [],          # 0x051 gen torque cmd
        'drv_t': [], 'drv_v': [],            # 0x06000002 drivetrain motor winding temp
        'drv_pct_t': [], 'drv_pct_v': [],   # GENE_DrvCoolFlowReq_pct
        'mot_pct_t': [], 'mot_pct_v': [],   # GENE_MotCoolFlowReq_pct
        'therm_t': [], 'therm_v': [],        # GENE_ThermInd_pct
        'raw_0479': [],                      # (t, b0, b1, b2) raw for encode_check
    }
    for frame in parse_file(log_path):
        t  = frame.timestamp
        aid = frame.arbitration_id
        d  = frame.data

        if aid == 0x479:
            if len(d) >= 3:
                decoded = msg_0479.decode(bytes(d[:4]), decode_choices=False)
                drv_pct  = decoded['GENE_DrvCoolFlowReq_pct']
                mot_pct  = decoded['GENE_MotCoolFlowReq_pct']
                therm    = decoded['GENE_ThermInd_pct']
                out['drv_pct_t'].append(t);  out['drv_pct_v'].append(drv_pct)
                out['mot_pct_t'].append(t);  out['mot_pct_v'].append(mot_pct)
                out['therm_t'].append(t);    out['therm_v'].append(therm)
                out['raw_0479'].append((t, d[0], d[1], d[2]))

        elif aid == 0x63C and len(d) >= 7:
            b6 = d[6]
            rpm = 16 * b6 - 96
            out['rpm_t'].append(t)
            out['rpm_v'].append(max(rpm, 0))

        elif aid == 0x0C9 and len(d) >= 3:
            # Engine_Speed: Motorola B1-B2, big-endian: (B1<<8|B2) * 0.25 rpm
            raw = (d[1] << 8) | d[2]
            out['obd_rpm_t'].append(t)
            out['obd_rpm_v'].append(raw * 0.25)

        elif aid == 0x051 and len(d) >= 3:
            raw = (d[2] << 8) | d[1]  # LE
            out['torq_t'].append(t)
            out['torq_v'].append(raw - 32768)

        elif aid == 0x06000002 and len(d) >= 7:
            b5 = d[5]; b6 = d[6]
            raw10 = (b6 << 2) | (b5 >> 6)
            out['drv_t'].append(t)
            out['drv_v'].append(raw10 * 2.0)

    # convert to numpy
    for k in out:
        if k != 'raw_0479':
            out[k] = np.array(out[k])
    return out


# ---------------------------------------------------------------------------
if PHASE == 'encode_check':
    print('\n--- encode_check: raw 0x479 frames ---')
    data_ov = collect(LOG_OVHEAT)
    for row in data_ov['raw_0479'][:30]:
        t, b0, b1, b2 = row
        drv = b0 * 0.78125
        mot = b1 * 0.78125
        thi = b2 * 0.78125
        print(f't={t:8.1f}s  B0={b0:3d} ({drv:5.1f}%)  B1={b1:3d} ({mot:5.1f}%)  B2={b2:3d} ({thi:5.1f}%)')
    print(f'\nTotal 0x479 frames: {len(data_ov["raw_0479"])}')
    if data_ov['drv_pct_v'].size:
        print(f'DrvCoolFlowReq_pct range: {data_ov["drv_pct_v"].min():.1f} -- {data_ov["drv_pct_v"].max():.1f} %')
        print(f'MotCoolFlowReq_pct range: {data_ov["mot_pct_v"].min():.1f} -- {data_ov["mot_pct_v"].max():.1f} %')
        print(f'ThermInd_pct range:       {data_ov["therm_v"].min():.1f} -- {data_ov["therm_v"].max():.1f} %')
    sys.exit(0)


# ---------------------------------------------------------------------------
print('Parsing pumpunplug log...')
pu = collect(LOG_UNPLUG)
print(f'  0x479 frames: {len(pu["raw_0479"])}  RPM: {pu["rpm_t"].size}  OBD RPM: {pu["obd_rpm_t"].size}')

print('Parsing overheat log...')
ov = collect(LOG_OVHEAT)
print(f'  0x479 frames: {len(ov["raw_0479"])}  RPM: {ov["rpm_t"].size}  OBD RPM: {ov["obd_rpm_t"].size}')

# Mark 0x63C overflow windows in overheat log (B6 wraps 255->0, known to overflow at RPM peak)
# Simple heuristic: flag frames where B6-derived RPM drops > 1000 RPM in one step (wrap-around)
rpm_v_arr = ov['rpm_v']
rpm_overflow_mask = np.zeros(len(rpm_v_arr), dtype=bool)
for i in range(1, len(rpm_v_arr)):
    if rpm_v_arr[i - 1] > 1000 and rpm_v_arr[i] < 500:
        # start of overflow window -- mark until next big rise
        j = i
        while j < len(rpm_v_arr) and rpm_v_arr[j] < 1000:
            rpm_overflow_mask[j] = True
            j += 1

# overheat peak time from notes: t~1857.9s  (log-relative)
PEAK_T = 1857.9

# ---------------------------------------------------------------------------
fig = plt.figure(figsize=(18, 16))
fig.suptitle('Generator Overheat Test — EPRI 0x479 GENE Thermal Signals\n'
             'Left: pumpunplug (normal->unplug transition)   Right: overheat log (pump already off)',
             fontsize=11)

gs = gridspec.GridSpec(4, 2, hspace=0.40, wspace=0.28)

def make_axes(col, sharex_list):
    axes = []
    for row in range(4):
        kw = {}
        if axes:
            kw['sharex'] = axes[0]
        ax = fig.add_subplot(gs[row, col], **kw)
        axes.append(ax)
    return axes

ax_pu = make_axes(0, [])
ax_ov = make_axes(1, [])

def plot_col(axes, data, title_suffix, peak_t=None):
    ax_rpm, ax_torq, ax_0479, ax_therm = axes

    # --- RPM panel ---
    if data['rpm_t'].size:
        rpm_t = data['rpm_t']
        rpm_v = data['rpm_v']
        # split by overflow mask if overheat log
        ax_rpm.plot(rpm_t, rpm_v, color='steelblue', linewidth=0.6, alpha=0.7, label='0x63C B6 (overflows)')
    if data['obd_rpm_t'].size:
        ax_rpm.plot(data['obd_rpm_t'], data['obd_rpm_v'], color='navy', linewidth=0.8,
                    label='OBD Engine_Speed (0x0C9)')
    ax_rpm.set_ylabel('RPM')
    ax_rpm.set_title(f'Generator RPM {title_suffix}')
    ax_rpm.legend(loc='upper left', fontsize=7)
    ax_rpm.grid(True, alpha=0.3)

    # --- Torque cmd panel ---
    if data['torq_t'].size:
        ax_torq.plot(data['torq_t'], data['torq_v'], color='darkorange', linewidth=0.6,
                     label='Gen torque cmd (0x051)')
        ax_torq.axhline(0, color='black', linewidth=0.5)
    ax_torq.set_ylabel('Raw - 32768')
    ax_torq.set_title(f'Generator Torque Command {title_suffix}')
    ax_torq.legend(loc='upper left', fontsize=7)
    ax_torq.grid(True, alpha=0.3)

    # --- 0x479 flow requests panel ---
    if data['drv_pct_t'].size:
        ax_0479.plot(data['drv_pct_t'], data['drv_pct_v'], color='dodgerblue', linewidth=1.0,
                     label='DrvCoolFlowReq_pct (B0, inverter)')
        ax_0479.plot(data['mot_pct_t'], data['mot_pct_v'], color='crimson', linewidth=1.2,
                     label='MotCoolFlowReq_pct (B1, motor oil)')
    ax_0479.set_ylim(-5, 110)
    ax_0479.axhline(100, color='black', linewidth=0.5, linestyle=':')
    ax_0479.set_ylabel('%')
    ax_0479.set_title(f'0x479: Cooling Flow Requests {title_suffix}')
    ax_0479.legend(loc='upper left', fontsize=7)
    ax_0479.grid(True, alpha=0.3)

    # --- ThermInd + drivetrain motor temp panel ---
    if data['therm_t'].size:
        ax_therm.plot(data['therm_t'], data['therm_v'], color='purple', linewidth=1.2,
                      label='ThermInd_pct (B2, generator thermal load)')
    ax_therm2 = ax_therm.twinx()
    if data['drv_t'].size:
        ax_therm2.plot(data['drv_t'], data['drv_v'], color='green', linewidth=0.7, alpha=0.7,
                       label='Drivetrain winding (0x06000002, deg C)')
    ax_therm.set_ylim(-5, 110)
    ax_therm.set_ylabel('%', color='purple')
    ax_therm2.set_ylabel('deg C', color='green')
    ax_therm.set_title(f'ThermInd_pct + Drivetrain Motor Temp {title_suffix}')
    lines1, lab1 = ax_therm.get_legend_handles_labels()
    lines2, lab2 = ax_therm2.get_legend_handles_labels()
    ax_therm.legend(lines1 + lines2, lab1 + lab2, loc='upper left', fontsize=7)
    ax_therm.grid(True, alpha=0.3)
    ax_therm.set_xlabel('Log time (s)')

    # Peak marker for overheat log
    if peak_t is not None:
        for ax in axes:
            ax.axvline(peak_t, color='red', linestyle='--', alpha=0.6, linewidth=1.0)

plot_col(ax_pu, pu, '(pumpunplug)')
plot_col(ax_ov, ov, '(overheat)', peak_t=PEAK_T)

OUT = r'projects/vtrux/notes/artifacts/gene_0479_epri_overheat.png'
plt.savefig(OUT, dpi=150, bbox_inches='tight')
print(f'Saved: {OUT}')
