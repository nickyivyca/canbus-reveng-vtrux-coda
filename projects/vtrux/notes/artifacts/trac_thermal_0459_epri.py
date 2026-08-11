"""
TRAC MCU Thermal Signals -- 0x459 EPRI DBC decoding
====================================================
Decodes 0x459 (EPRI_MCU_Thermal1_0459) using the EPRI OBD-bus DBC.
Symmetric to GENE 0x479 on PT bus; identical encoding, OBD bus only.

  B0: TRAC_DrvCoolFlowReq_pct  -- drive/inverter cooling flow request (%)
  B1: TRAC_MotCoolFlowReq_pct  -- motor oil cooling flow request (%)
  B2: TRAC_ThermInd_pct        -- thermal indicator (%)

Plots against reference signals from the drivetrain overheat log:
  - Traction motor winding temp: 0x06000002 B5/B6, 10-bit LE startbit 46, *2.0 deg C
  - Traction torque feedback:    0x5A2 B4-B5 LE signed (centered at 32768)
  - Traction RPM:                0x5A2 B2-B3 LE unsigned (centered at 32768? -- raw)
  - Engine speed (OBD bus):      0x0C9 B1-B2 BE, *0.25 RPM (generator on/off indicator)

Key event timestamps (from investigation notes):
  t ~  393s -- drivetrain oil pump unplugged
  t ~ 1953s -- torque cutback onset
  t ~ 2253s -- pump reconnected

Phases:
  encode_check  -- print raw 0x459 frames and decoded values
  plot          -- multi-panel figure with all reference signals
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

OBD_DBC  = r'projects/vtrux/epri-obd-bus.dbc'
LOG      = r'projects/vtrux/logs/vtruxdrivetrainoverheattest.log'

PHASE = 'corr_obd'  # 'encode_check', 'plot', 'fallback', 'stats', or 'corr_obd'

# Key event times
T_PUMP_OFF    = 393
T_CUTBACK     = 1953
T_PUMP_ON     = 2253

# ---------------------------------------------------------------------------
db_obd = cantools.database.load_file(OBD_DBC, strict=False)
msg_0459 = db_obd.get_message_by_name('EPRI_MCU_Thermal1_0459')
print(f'Loaded OBD DBC. 0x459 signals: {[s.name for s in msg_0459.signals]}')

# ---------------------------------------------------------------------------
print(f'Parsing {LOG} ...')

drv_pct_t, drv_pct_v = [], []   # TRAC_DrvCoolFlowReq_pct
mot_pct_t, mot_pct_v = [], []   # TRAC_MotCoolFlowReq_pct
therm_t,   therm_v   = [], []   # TRAC_ThermInd_pct
raw_0459 = []                    # (t, b0, b1, b2)

wndg_t, wndg_v   = [], []       # 0x06000002 winding temp
trqfbk_t, trqfbk_v = [], []     # 0x5A2 B4-B5 traction torque feedback
rpm5a2_t, rpm5a2_v = [], []     # 0x5A2 B2-B3 traction RPM
eng_t,  eng_v    = [], []       # 0x0C9 engine speed (OBD)

# Fallback candidates (0x459 absent from log)
x441_t,  x441_d  = [], []       # 0x441 full data list (DLC=6, B5=counter)
x463_t,  x463_d  = [], []       # 0x463 full data list (1 Hz TRAC analog tier A)
x464_t,  x464_d  = [], []       # 0x464 full data list (1 Hz TRAC analog tier B)

for frame in parse_file(LOG):
    t   = frame.timestamp
    aid = frame.arbitration_id
    d   = frame.data

    if aid == 0x459:
        if len(d) >= 3:
            decoded = msg_0459.decode(bytes(d[:3]), decode_choices=False)
            drv_pct_t.append(t); drv_pct_v.append(decoded['TRAC_DrvCoolFlowReq_pct'])
            mot_pct_t.append(t); mot_pct_v.append(decoded['TRAC_MotCoolFlowReq_pct'])
            therm_t.append(t);   therm_v.append(decoded['TRAC_ThermInd_pct'])
            raw_0459.append((t, d[0], d[1], d[2]))

    elif aid == 0x06000002 and len(d) >= 7:
        b5 = d[5]; b6 = d[6]
        raw10 = (b6 << 2) | (b5 >> 6)
        wndg_t.append(t); wndg_v.append(raw10 * 2.0)

    elif aid == 0x5A2 and len(d) >= 6:
        rpm_raw  = (d[3] << 8) | d[2]   # B2-B3 LE
        trq_raw  = (d[5] << 8) | d[4]   # B4-B5 LE
        rpm5a2_t.append(t); rpm5a2_v.append(rpm_raw - 32768)
        trqfbk_t.append(t); trqfbk_v.append(trq_raw - 32768)

    elif aid == 0x0C9 and len(d) >= 3:
        raw = (d[1] << 8) | d[2]        # BE
        eng_t.append(t); eng_v.append(raw * 0.25)

    elif aid == 0x441 and len(d) >= 5:
        x441_t.append(t); x441_d.append(list(d[:5]))   # drop B5 counter

    elif aid == 0x463 and len(d) >= 7:
        x463_t.append(t); x463_d.append(list(d[:7]))

    elif aid == 0x464 and len(d) >= 7:
        x464_t.append(t); x464_d.append(list(d[:7]))

# convert to numpy
drv_pct_t = np.array(drv_pct_t); drv_pct_v = np.array(drv_pct_v)
mot_pct_t = np.array(mot_pct_t); mot_pct_v = np.array(mot_pct_v)
therm_t   = np.array(therm_t);   therm_v   = np.array(therm_v)
wndg_t    = np.array(wndg_t);    wndg_v    = np.array(wndg_v)
trqfbk_t  = np.array(trqfbk_t); trqfbk_v  = np.array(trqfbk_v)
rpm5a2_t  = np.array(rpm5a2_t); rpm5a2_v  = np.array(rpm5a2_v)
eng_t     = np.array(eng_t);    eng_v     = np.array(eng_v)

print(f'  0x459 frames:      {len(raw_0459)}')
print(f'  Winding temp:      {wndg_t.size} frames')
print(f'  Traction torque:   {trqfbk_t.size} frames')
print(f'  Engine speed:      {eng_t.size} frames')
print(f'  0x441 frames:      {len(x441_t)}')
print(f'  0x463 frames:      {len(x463_t)}')
print(f'  0x464 frames:      {len(x464_t)}')

# ---------------------------------------------------------------------------
if PHASE == 'encode_check':
    print('\n--- encode_check: raw 0x459 frames ---')
    for row in raw_0459[:30]:
        t, b0, b1, b2 = row
        print(f't={t:8.1f}s  B0={b0:3d} ({b0*0.78125:5.1f}%)  '
              f'B1={b1:3d} ({b1*0.78125:5.1f}%)  B2={b2:3d} ({b2*0.78125:5.1f}%)')
    if drv_pct_v.size:
        print(f'\nDrvCoolFlowReq_pct range: {drv_pct_v.min():.1f} -- {drv_pct_v.max():.1f} %')
        print(f'MotCoolFlowReq_pct range: {mot_pct_v.min():.1f} -- {mot_pct_v.max():.1f} %')
        print(f'ThermInd_pct range:       {therm_v.min():.1f} -- {therm_v.max():.1f} %')
    sys.exit(0)

# ---------------------------------------------------------------------------
fig = plt.figure(figsize=(16, 18))
fig.suptitle('Drivetrain Overheat Test -- EPRI 0x459 TRAC Thermal Signals\n'
             'vtruxdrivetrainoverheattest.log (2026-03-11, start 20:12:27)',
             fontsize=11)

gs = gridspec.GridSpec(5, 1, hspace=0.38)
ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1], sharex=ax1)
ax3 = fig.add_subplot(gs[2], sharex=ax1)
ax4 = fig.add_subplot(gs[3], sharex=ax1)
ax5 = fig.add_subplot(gs[4], sharex=ax1)

EVENT_STYLE = dict(linewidth=1.2, alpha=0.7)
for ax in [ax1, ax2, ax3, ax4, ax5]:
    ax.axvline(T_PUMP_OFF, color='orange', linestyle='--', label='Pump off (~393s)', **EVENT_STYLE)
    ax.axvline(T_CUTBACK,  color='red',    linestyle='--', label='Cutback (~1953s)', **EVENT_STYLE)
    ax.axvline(T_PUMP_ON,  color='green',  linestyle='--', label='Pump on (~2253s)', **EVENT_STYLE)

# Panel 1: Traction torque feedback + RPM (load reference)
ax1.plot(trqfbk_t, trqfbk_v, color='darkorange', linewidth=0.6, alpha=0.8,
         label='Traction torque fbk (0x5A2 B4-B5, raw-32768)')
ax1.axhline(0, color='black', linewidth=0.5)
ax1r = ax1.twinx()
ax1r.plot(rpm5a2_t, rpm5a2_v, color='steelblue', linewidth=0.5, alpha=0.6,
          label='Traction RPM (0x5A2 B2-B3, raw-32768)')
ax1.set_ylabel('Torque (centered)', color='darkorange')
ax1r.set_ylabel('RPM (centered)', color='steelblue')
ax1.set_title('Traction Motor Load (torque feedback + RPM)')
lines1, lab1 = ax1.get_legend_handles_labels()
lines2, lab2 = ax1r.get_legend_handles_labels()
ax1.legend(lines1[:1] + lines2[:1], lab1[:1] + lab2[:1], loc='upper left', fontsize=7)
ax1.grid(True, alpha=0.3)

# Panel 2: Engine speed (shows generator on/off for context)
ax2.plot(eng_t, eng_v, color='gray', linewidth=0.6,
         label='Engine speed (0x0C9 OBD, *0.25 RPM)')
ax2.set_ylabel('RPM')
ax2.set_title('Engine Speed (generator running indicator)')
ax2.legend(loc='upper left', fontsize=7)
ax2.grid(True, alpha=0.3)

# Panel 3: 0x459 cooling flow requests
ax3.plot(drv_pct_t, drv_pct_v, color='dodgerblue', linewidth=1.0,
         label='DrvCoolFlowReq_pct (B0, inverter PE glycol)')
ax3.plot(mot_pct_t, mot_pct_v, color='crimson', linewidth=1.2,
         label='MotCoolFlowReq_pct (B1, motor oil)')
ax3.set_ylim(-5, 110)
ax3.axhline(100, color='black', linewidth=0.5, linestyle=':')
ax3.set_ylabel('%')
ax3.set_title('0x459: TRAC Cooling Flow Requests')
ax3.legend(loc='upper left', fontsize=7)
ax3.grid(True, alpha=0.3)

# Panel 4: ThermInd_pct
ax4.plot(therm_t, therm_v, color='purple', linewidth=1.2,
         label='ThermInd_pct (B2, traction thermal load)')
ax4.set_ylim(-5, 110)
ax4.axhline(100, color='black', linewidth=0.5, linestyle=':')
ax4.set_ylabel('%')
ax4.set_title('0x459: TRAC Thermal Indicator')
ax4.legend(loc='upper left', fontsize=7)
ax4.grid(True, alpha=0.3)

# Panel 5: Confirmed winding temperature (cross-reference)
ax5.plot(wndg_t, wndg_v, color='green', linewidth=1.0,
         label='Winding temp (0x06000002 B5/B6, *2.0 deg C)')
ax5.set_ylabel('deg C')
ax5.set_title('Confirmed Traction Winding Temperature (cross-reference)')
ax5.legend(loc='upper left', fontsize=7)
ax5.grid(True, alpha=0.3)
ax5.set_xlabel('Log time (s)')

# Add shared event legend to first panel
ax1.legend(lines1[:1] + lines2[:1] +
           [plt.Line2D([0],[0], color='orange', linestyle='--'),
            plt.Line2D([0],[0], color='red',    linestyle='--'),
            plt.Line2D([0],[0], color='green',  linestyle='--')],
           lab1[:1] + lab2[:1] + ['Pump off', 'Cutback', 'Pump on'],
           loc='upper left', fontsize=7)

OUT = r'projects/vtrux/notes/artifacts/trac_0459_epri_overheat.png'
plt.savefig(OUT, dpi=150, bbox_inches='tight')
print(f'Saved: {OUT}')


# ---------------------------------------------------------------------------
# FALLBACK PHASE: 0x459 absent -- plot 0x441 and 0x463/0x464 against winding temp
# ---------------------------------------------------------------------------
if PHASE == 'fallback':
    if not x441_t:
        print('No 0x441 frames found -- cannot plot fallback')
        sys.exit(0)

    x441_t  = np.array(x441_t,  dtype=float)
    x441_d  = np.array(x441_d,  dtype=int)    # shape (N, 5)
    x463_t  = np.array(x463_t,  dtype=float)
    x463_d  = np.array(x463_d,  dtype=int)    # shape (N, 7)
    x464_t  = np.array(x464_t,  dtype=float)
    x464_d  = np.array(x464_d,  dtype=int)

    fig2, axes = plt.subplots(5, 1, figsize=(16, 18), sharex=True)
    fig2.suptitle('Drivetrain Overheat -- Fallback Candidates (0x459 absent)\n'
                  '0x441 B0-B4 (pct scale) and 0x463/0x464 per-byte',
                  fontsize=11)

    EVENT_S = dict(linewidth=1.0, alpha=0.6)
    for ax in axes:
        ax.axvline(T_PUMP_OFF, color='orange', linestyle='--', **EVENT_S)
        ax.axvline(T_CUTBACK,  color='red',    linestyle='--', **EVENT_S)
        ax.axvline(T_PUMP_ON,  color='green',  linestyle='--', **EVENT_S)

    # Panel 1: 0x441 B0-B2 as percentage (same scale as 0x479)
    COLORS = ['dodgerblue', 'crimson', 'purple', 'darkorange', 'gray']
    for i in range(min(5, x441_d.shape[1])):
        pct = x441_d[:, i] * 0.78125
        axes[0].plot(x441_t, pct, color=COLORS[i], linewidth=0.8,
                     label=f'0x441 B{i} (*0.78125 %)')
    axes[0].set_ylim(-5, 110)
    axes[0].axhline(100, color='black', linewidth=0.5, linestyle=':')
    axes[0].set_ylabel('%')
    axes[0].set_title('0x441 B0-B4 (percentage interpretation, same scale as GENE 0x479)')
    axes[0].legend(loc='upper left', fontsize=7)
    axes[0].grid(True, alpha=0.3)

    # Panel 2: 0x441 B0-B2 raw (to see actual values)
    for i in range(min(3, x441_d.shape[1])):
        axes[1].plot(x441_t, x441_d[:, i], color=COLORS[i], linewidth=0.8,
                     label=f'0x441 B{i} raw')
    axes[1].set_ylabel('Raw')
    axes[1].set_title('0x441 B0-B2 raw values')
    axes[1].legend(loc='upper left', fontsize=7)
    axes[1].grid(True, alpha=0.3)

    # Panel 3: 0x463 per-byte (1 Hz TRAC analog tier A)
    if x463_t.size:
        for i in range(min(7, x463_d.shape[1])):
            vals = x463_d[:, i]
            if vals.max() - vals.min() < 2:
                continue   # skip constant bytes
            axes[2].plot(x463_t, vals, linewidth=1.0, label=f'0x463 B{i}')
    axes[2].set_ylabel('Raw')
    axes[2].set_title('0x463 per-byte (TRAC analog tier A, 1 Hz) -- constant bytes omitted')
    axes[2].legend(loc='upper left', fontsize=7)
    axes[2].grid(True, alpha=0.3)

    # Panel 4: 0x464 per-byte (1 Hz TRAC analog tier B)
    if x464_t.size:
        for i in range(min(7, x464_d.shape[1])):
            vals = x464_d[:, i]
            if vals.max() - vals.min() < 2:
                continue
            axes[3].plot(x464_t, vals, linewidth=1.0, label=f'0x464 B{i}')
    axes[3].set_ylabel('Raw')
    axes[3].set_title('0x464 per-byte (TRAC analog tier B, 1 Hz) -- constant bytes omitted')
    axes[3].legend(loc='upper left', fontsize=7)
    axes[3].grid(True, alpha=0.3)

    # Panel 5: Confirmed winding temp (ground truth)
    axes[4].plot(wndg_t, wndg_v, color='green', linewidth=1.0,
                 label='Winding temp (0x06000002, *2.0 deg C)')
    axes[4].set_ylabel('deg C')
    axes[4].set_title('Confirmed Winding Temp (ground truth)')
    axes[4].legend(loc='upper left', fontsize=7)
    axes[4].grid(True, alpha=0.3)
    axes[4].set_xlabel('Log time (s)')

    # Event legend on first panel
    for ax in axes:
        handles, labels = ax.get_legend_handles_labels()
        # add event lines to first panel legend only
    axes[0].legend(
        axes[0].get_legend_handles_labels()[0] +
        [plt.Line2D([0],[0], color='orange', linestyle='--'),
         plt.Line2D([0],[0], color='red',    linestyle='--'),
         plt.Line2D([0],[0], color='green',  linestyle='--')],
        axes[0].get_legend_handles_labels()[1] +
        ['Pump off', 'Cutback', 'Pump on'],
        loc='upper left', fontsize=7)

    OUT2 = r'projects/vtrux/notes/artifacts/trac_fallback_candidates.png'
    plt.savefig(OUT2, dpi=150, bbox_inches='tight')
    print(f'Saved: {OUT2}')


# ---------------------------------------------------------------------------
# STATS PHASE: numeric summary of fallback candidates at key event windows
# ---------------------------------------------------------------------------
if PHASE == 'stats':
    x441_t_a = np.array(x441_t, dtype=float)
    x441_d_a = np.array(x441_d, dtype=float)
    x463_t_a = np.array(x463_t, dtype=float)
    x463_d_a = np.array(x463_d, dtype=float)
    x464_t_a = np.array(x464_t, dtype=float)
    x464_d_a = np.array(x464_d, dtype=float)
    wndg_t_a = np.array(wndg_t, dtype=float)
    wndg_v_a = np.array(wndg_v, dtype=float)

    WINDOWS = [
        ('pre-unplug  t= 200s', 200),
        ('pump-off    t= 393s', T_PUMP_OFF),
        ('mid-heat    t=1200s', 1200),
        ('cutback     t=1953s', T_CUTBACK),
        ('pump-on     t=2253s', T_PUMP_ON),
        ('recovery    t=2500s', 2500),
    ]
    HALF = 30  # +/- seconds per window

    def wmean(ts, vs, tc):
        m = (ts >= tc - HALF) & (ts <= tc + HALF)
        return vs[m].mean(axis=0) if m.any() else None

    def wndg_mean(tc):
        m = (wndg_t_a >= tc - HALF) & (wndg_t_a <= tc + HALF)
        return float(wndg_v_a[m].mean()) if m.any() else float('nan')

    print('\n=== 0x441 B0-B4 mean per window (B5 omitted -- rolling counter) ===')
    print(f'  {"Window":<22}  {"B0":>7}  {"B1":>7}  {"B2":>7}  {"B3":>7}  {"B4":>7}  | wndg_degC')
    for label, tc in WINDOWS:
        r = wmean(x441_t_a, x441_d_a, tc)
        w = wndg_mean(tc)
        if r is not None:
            print(f'  {label}  ' + '  '.join(f'{r[i]:7.1f}' for i in range(5)) + f'  | {w:5.0f}')
        else:
            print(f'  {label}  no data')

    # Also show 0x441 B0/B1 as pct
    print('\n  -- B0 and B1 as percentage (* 0.78125) --')
    for label, tc in WINDOWS:
        r = wmean(x441_t_a, x441_d_a, tc)
        if r is not None:
            print(f'  {label}  B0={r[0]*0.78125:5.1f}%  B1={r[1]*0.78125:5.1f}%  B2={r[2]*0.78125:5.1f}%')

    print('\n=== 0x463 varying bytes per window ===')
    if x463_t_a.size:
        # find which bytes vary across the full log
        vary = [i for i in range(x463_d_a.shape[1])
                if x463_d_a[:, i].max() - x463_d_a[:, i].min() >= 2]
        print(f'  Varying byte indices: {vary}')
        header = '  ' + f'{"Window":<22}' + ''.join(f'  {"B"+str(i):>6}' for i in vary) + '  | wndg_degC'
        print(header)
        for label, tc in WINDOWS:
            r = wmean(x463_t_a, x463_d_a, tc)
            w = wndg_mean(tc)
            if r is not None:
                row = '  ' + f'{label:<22}' + ''.join(f'  {r[i]:6.1f}' for i in vary) + f'  | {w:5.0f}'
                print(row)
            else:
                print(f'  {label}  no data')

    print('\n=== 0x464 varying bytes per window ===')
    if x464_t_a.size:
        vary = [i for i in range(x464_d_a.shape[1])
                if x464_d_a[:, i].max() - x464_d_a[:, i].min() >= 2]
        print(f'  Varying byte indices: {vary}')
        header = '  ' + f'{"Window":<22}' + ''.join(f'  {"B"+str(i):>6}' for i in vary) + '  | wndg_degC'
        print(header)
        for label, tc in WINDOWS:
            r = wmean(x464_t_a, x464_d_a, tc)
            w = wndg_mean(tc)
            if r is not None:
                row = '  ' + f'{label:<22}' + ''.join(f'  {r[i]:6.1f}' for i in vary) + f'  | {w:5.0f}'
                print(row)
            else:
                print(f'  {label}  no data')
    sys.exit(0)


# ---------------------------------------------------------------------------
# CORR_OBD PHASE: OBD-bus correlation sweep against confirmed winding temp
# ---------------------------------------------------------------------------
if PHASE == 'corr_obd':
    GMLAN_DBC   = r'projects/vtrux/GMW8762_PPEI_GMLAN.dbc'
    EPRI_OBD_DB = r'projects/vtrux/epri-obd-bus.dbc'

    # Build exclusion set from both DBCs
    db_gmlan = cantools.database.load_file(GMLAN_DBC, strict=False)
    db_epri2 = cantools.database.load_file(EPRI_OBD_DB, strict=False)
    known_ids = set()
    for db in (db_gmlan, db_epri2):
        for msg in db.messages:
            known_ids.add(msg.frame_id)
    known_ids.update(range(0x040, 0x044))   # VCU->TRAC commands
    print(f'Exclusion set: {len(known_ids)} known IDs from GMLAN + EPRI OBD DBCs')

    # Pass 1: identify OBD bus channel via anchor 0x044 (TRAC_RotSpd, OBD-only)
    obd_channel = None
    for frame in parse_file(LOG):
        if frame.arbitration_id == 0x044:
            obd_channel = frame.bus
            break
    if obd_channel is None:
        print('ERROR: 0x044 not found -- cannot identify OBD bus channel')
        sys.exit(1)
    print(f'OBD bus channel: {obd_channel}')

    # Pass 2: collect winding temp reference + novel OBD-bus frames
    ref_t2, ref_v2 = [], []
    cand = {}   # (aid, label) -> {t:[], v:[]}

    for frame in parse_file(LOG):
        t   = frame.timestamp
        aid = frame.arbitration_id
        d   = frame.data

        # Winding temp reference from PT bus
        if aid == 0x06000002 and len(d) >= 7:
            raw10 = (d[6] << 2) | (d[5] >> 6)
            ref_t2.append(t)
            ref_v2.append(raw10 * 2.0)

        if frame.bus != obd_channel:
            continue
        if frame.is_extended:
            continue
        if aid in known_ids:
            continue

        dlc = len(d)
        for i in range(dlc):
            key = (aid, f'B{i}')
            if key not in cand:
                cand[key] = {'t': [], 'v': []}
            cand[key]['t'].append(t)
            cand[key]['v'].append(d[i])

        for i in range(dlc - 1):
            for lbl, val in [(f'B{i}B{i+1}_LE', (d[i+1] << 8) | d[i]),
                             (f'B{i}B{i+1}_BE', (d[i]   << 8) | d[i+1])]:
                key = (aid, lbl)
                if key not in cand:
                    cand[key] = {'t': [], 'v': []}
                cand[key]['t'].append(t)
                cand[key]['v'].append(val)

    print(f'Reference frames: {len(ref_t2)}')
    print(f'Candidate signals: {len(cand)}')

    ref_t2 = np.array(ref_t2, dtype=float)
    ref_v2 = np.array(ref_v2, dtype=float)

    MIN_N = 20; MIN_UNIQUE = 4; MIN_RANGE = 3
    results = []
    for key, data in cand.items():
        ts = np.array(data['t'], dtype=float)
        vs = np.array(data['v'], dtype=float)
        if len(ts) < MIN_N or np.unique(vs).size < MIN_UNIQUE or (vs.max() - vs.min()) < MIN_RANGE:
            continue
        ref_i = np.interp(ts, ref_t2, ref_v2)
        if np.std(vs) < 1e-9 or np.std(ref_i) < 1e-9:
            continue
        r = float(np.corrcoef(vs, ref_i)[0, 1])
        results.append((abs(r), r, key, len(ts), int(vs.min()), int(vs.max()), int(np.unique(vs).size)))

    results.sort(reverse=True)
    print(f'\nTop 30 OBD-bus non-GMLAN candidates correlated with winding temp:')
    print(f'  {"ID":>6}  {"Signal":<18}  {"r":>7}  {"n":>7}  {"min":>5}  {"max":>5}  {"uniq":>5}')
    for _, r, (aid, sig), n, mn, mx, uniq in results[:30]:
        print(f'  0x{aid:03X}  {sig:<18}  {r:+7.3f}  {n:>7}  {mn:>5}  {mx:>5}  {uniq:>5}')
    sys.exit(0)
