"""
verify_0x420_limits.py

Verify bcm_dis_max and bcm_chg_max (EPRI-confirmed 12-bit Motorola signals in 0x420)
against the known event windows in vtruxcurrentlimitingtest.log.

Signals decoded via cantools from epri-pt-bus.dbc:
  0x420: bcm_dis_max (A), bcm_chg_max (A)
  0x410: bcm_ibat (A, unsigned discharge-only -- regen not captured)
  0x592: Veh_BrakePdl_Pos (%), EVSESwitchState, IgnitionKeyState
  0x598: DBL_ESSPwrAvg (kW, signed -- negative = regen/charging)

Hand-decoded (not in any DBC):
  0x050 B0+(B1&0x03)<<8   VCU CCL command (10-bit, 9.1 Hz)
  0x5A2 B4-B5 LE-32768     motor torque feedback (raw counts)
  0x5A2 B2-B3 LE-32768     motor speed proxy (raw counts)

Event windows (from current-limits-investigation.md):
  t=30-72s      Unrestricted regen baseline
  t=348.6-365.6 Regen (charge) current limit active -- CCL engaged
  t=606-625s    Discharge current limit active -- DCL engaged
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

import cantools

ROOT = Path(__file__).parents[4]
LOG  = ROOT / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
DBC_PT  = ROOT / "projects/vtrux/epri-pt-bus.dbc"
DBC_OBD = ROOT / "projects/vtrux/epri-obd-bus.dbc"

db_pt  = cantools.db.load_file(str(DBC_PT))
db_obd = cantools.db.load_file(str(DBC_OBD))

dis_max  = []   # (t, A)
chg_max  = []   # (t, A)
ccl_050  = []   # (t, raw)   -- hand-decoded, not in DBC
ibat     = []   # (t, A)     -- unsigned, discharge only; 0 or sentinel during regen
ess_pwr  = []   # (t, kW)    -- signed virtual sensor; sign convention unclear
hv_curr  = []   # (t, A)     -- TRAC_HighPwr_Curr: traction inverter HV DC bus current (OBD bus)
hv_volt  = []   # (t, V)     -- TRAC_HighPwr_Volt: traction inverter HV DC bus voltage (OBD bus)
x420_b3  = []   # (t, raw)   -- isolation resistance byte (B3, not a named signal)
x420_b4  = []   # (t, raw)   -- unknown byte
brake    = []   # (t, %)     -- Veh_BrakePdl_Pos
mtr_spd  = []   # (t, raw)   -- hand-decoded motor speed proxy
torque   = []   # (t, raw)   -- hand-decoded motor torque

print("Parsing log...")
for frame in parse_file(str(LOG)):
    t   = frame.timestamp
    d   = frame.data
    aid = frame.arbitration_id

    if aid == 0x420 and len(d) >= 5:
        try:
            sigs = db_pt.decode_message(aid, bytes(d))
            dis_max.append((t, sigs['bcm_dis_max']))
            chg_max.append((t, sigs['bcm_chg_max']))
        except Exception:
            pass
        x420_b3.append((t, d[3]))
        x420_b4.append((t, d[4]))

    elif aid == 0x050 and len(d) >= 2:
        raw = d[0] | ((d[1] & 0x03) << 8)
        ccl_050.append((t, raw))

    elif aid == 0x410 and len(d) >= 3:
        try:
            sigs = db_pt.decode_message(aid, bytes(d))
            ibat.append((t, sigs['bcm_ibat']))
        except Exception:
            pass

    elif aid == 0x5A2 and len(d) >= 6:
        torque.append((t, (d[4] | d[5] << 8) - 32768))
        mtr_spd.append((t, (d[2] | d[3] << 8) - 32768))

    elif aid == 0x592 and len(d) >= 6:
        try:
            sigs = db_pt.decode_message(aid, bytes(d))
            brake.append((t, sigs['Veh_BrakePdl_Pos']))
        except Exception:
            pass

    elif aid == 0x462 and len(d) >= 5:
        try:
            sigs = db_obd.decode_message(aid, bytes(d))
            hv_curr.append((t, sigs['TRAC_HighPwr_Curr']))
            hv_volt.append((t, sigs['TRAC_HighPwr_Volt']))
        except Exception:
            pass

    elif aid == 0x598 and len(d) >= 6:
        try:
            sigs = db_pt.decode_message(aid, bytes(d))
            ess_pwr.append((t, sigs['DBL_ESSPwrAvg']))
        except Exception:
            pass

print(f"  0x420 frames: {len(dis_max)}")
print(f"  0x050 frames: {len(ccl_050)}")
print(f"  0x410 ibat frames: {len(ibat)}")
print(f"  0x462 hv_curr frames: {len(hv_curr)}")
print(f"  0x598 ess_pwr frames: {len(ess_pwr)}")
print(f"  0x5A2 torque frames: {len(torque)}")

# ── per-window stats ──────────────────────────────────────────────────────────

windows = [
    ("baseline (t=30-72s)",       30,   72),
    ("CCL active (t=348-366s)",  348,  366),
    ("post-CCL ref (t=400-560s)",400,  560),
    ("DCL active (t=606-625s)",  606,  625),
    ("post-DCL (t=700-800s)",    700,  800),
]

def window_vals(series, t0, t1):
    return [v for t, v in series if t0 <= t <= t1]

def stats_line(label, vals, fmt='.2f'):
    if not vals:
        return f"  {label}: (no data)"
    s = sorted(vals)
    return (f"  {label}: min={min(vals):{fmt}}  max={max(vals):{fmt}}  "
            f"median={s[len(s)//2]:{fmt}}  n_unique={len(set(vals))}")

print("\n--- bcm_dis_max (A) by window ---")
for label, t0, t1 in windows:
    print(stats_line(label, window_vals(dis_max, t0, t1)))

print("\n--- bcm_chg_max (A) by window ---")
for label, t0, t1 in windows:
    print(stats_line(label, window_vals(chg_max, t0, t1)))

print("\n--- 0x050 CCL raw by window ---")
for label, t0, t1 in windows:
    print(stats_line(label, window_vals(ccl_050, t0, t1), fmt='d'))

print("\n--- TRAC_HighPwr_Curr (A, traction inverter HV DC, 0x462) by window ---")
for label, t0, t1 in windows:
    print(stats_line(label, window_vals(hv_curr, t0, t1)))

print("\n--- TRAC_HighPwr_Volt (V, traction inverter HV DC, 0x462) by window ---")
for label, t0, t1 in windows:
    print(stats_line(label, window_vals(hv_volt, t0, t1), fmt='.0f'))

print("\n--- DBL_ESSPwrAvg (kW) by window ---")
for label, t0, t1 in windows:
    print(stats_line(label, window_vals(ess_pwr, t0, t1)))

print("\n--- 0x420 B3 (isolation resistance) by window ---")
for label, t0, t1 in windows:
    vals = window_vals(x420_b3, t0, t1)
    if vals:
        print(f"  {label}: min={min(vals)}  max={max(vals)}  n_unique={len(set(vals))}")

print("\n--- 0x420 B4 (unknown) by window ---")
for label, t0, t1 in windows:
    vals = window_vals(x420_b4, t0, t1)
    if vals:
        print(f"  {label}: min={min(vals)}  max={max(vals)}  n_unique={len(set(vals))}")

# ── CCL event timeseries: driver inputs + limits around t=344-370s ───────────
print("\n--- CCL-window timeseries (t=344-370s): chg_max, 0x050, brake_pct, torque, hv_curr, ess_kW ---")
print(f"  {'time':>7}  {'chg_A':>7}  {'0x050':>6}  {'brake%':>7}  {'torque':>7}  {'spd_raw':>8}  {'hv_A':>7}  {'ess_kW':>7}  note")

def nearest(series, t_ref, tol=0.15):
    best = None
    for t, v in series:
        if abs(t - t_ref) < tol:
            if best is None or abs(t - t_ref) < abs(best[0] - t_ref):
                best = (t, v)
    return best

ccl_w  = [(t, v) for t, v in ccl_050  if 340 <= t <= 375]
brake_w= [(t, v) for t, v in brake    if 340 <= t <= 375]
torq_w = [(t, v) for t, v in torque   if 340 <= t <= 375]
spd_w  = [(t, v) for t, v in mtr_spd  if 340 <= t <= 375]
hvc_w  = [(t, v) for t, v in hv_curr  if 340 <= t <= 375]
pwr_w  = [(t, v) for t, v in ess_pwr  if 340 <= t <= 375]

prev_chg = None
prev_050 = None
for t, v_c in chg_max:
    if 344 <= t <= 370:
        c50 = nearest(ccl_w,   t)
        cbr = nearest(brake_w, t)
        ctr = nearest(torq_w,  t)
        csp = nearest(spd_w,   t)
        chc = nearest(hvc_w,   t)
        cpw = nearest(pwr_w,   t)
        v50 = c50[1] if c50 else float('nan')
        vbr = cbr[1] if cbr else float('nan')
        vtr = ctr[1] if ctr else float('nan')
        vsp = csp[1] if csp else float('nan')
        vhc = chc[1] if chc else float('nan')
        vpw = cpw[1] if cpw else float('nan')
        notes = []
        if prev_chg is not None and abs(v_c - prev_chg) > 1:
            notes.append('chg_chg')
        if prev_050 is not None and not (isinstance(v50, float) and v50 != v50):
            if abs(v50 - prev_050) > 5:
                notes.append('050_chg')
        print(f"  {t:7.2f}  {v_c:7.2f}  {v50:6.0f}  {vbr:7.2f}  {vtr:7.0f}  {vsp:8.0f}  {vhc:7.2f}  {vpw:7.2f}  {', '.join(notes)}")
        prev_chg = v_c
        if not (isinstance(v50, float) and v50 != v50):
            prev_050 = v50

# ── full-log range summary ────────────────────────────────────────────────────
print("\n--- full log ranges ---")
all_dis = [v for _, v in dis_max]
all_chg = [v for _, v in chg_max]
all_pwr = [v for _, v in ess_pwr]
print(f"  bcm_dis_max: {min(all_dis):.2f}-{max(all_dis):.2f} A, n_unique={len(set(all_dis))}")
print(f"  bcm_chg_max: {min(all_chg):.2f}-{max(all_chg):.2f} A, n_unique={len(set(all_chg))}")
if all_pwr:
    print(f"  DBL_ESSPwrAvg: {min(all_pwr):.2f}-{max(all_pwr):.2f} kW, n_unique={len(set(all_pwr))}")

# ── plot ─────────────────────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    event_regions = [
        (30,   72,   'Unrestricted regen', 'lime',   0.12),
        (348.6,365.6,'CCL active',          'yellow', 0.15),
        (606,  625,  'DCL active',          'orange', 0.15),
    ]

    def shade(ax):
        for t0, t1, lbl, col, alpha in event_regions:
            ax.axvspan(t0, t1, color=col, alpha=alpha, zorder=0)

    def unzip(series):
        if not series:
            return [], []
        return [r[0] for r in series], [r[1] for r in series]

    fig, axes = plt.subplots(4, 1, figsize=(18, 14), sharex=True)
    fig.suptitle("0x420 bcm_dis_max / bcm_chg_max vs event windows\n"
                 "vtruxcurrentlimitingtest.log", fontsize=12)

    # panel 1: bcm limits in A
    ax = axes[0]
    shade(ax)
    t_d, v_d = unzip(dis_max)
    t_c, v_c = unzip(chg_max)
    ax.plot(t_d, v_d, color='orange', lw=1.2, label='bcm_dis_max (A)')
    ax.plot(t_c, v_c, color='cyan',   lw=1.2, label='bcm_chg_max (A)')
    ax.set_ylabel('Current limit (A)')
    ax.legend(loc='upper right', fontsize=9)
    ax.set_title('BMS current limits (0x420, cantools/epri-pt-bus.dbc)')

    # panel 2: 0x050 VCU CCL
    ax = axes[1]
    shade(ax)
    t_050, v_050 = unzip(ccl_050)
    ax.plot(t_050, v_050, color='yellow', lw=1.0, label='0x050 CCL raw (VCU, hand-decoded)')
    ax.set_ylabel('Raw counts')
    ax.legend(loc='upper right', fontsize=9)
    ax.set_title('0x050 VCU CCL command')

    # panel 3: ESS power (kW, signed)
    ax = axes[2]
    shade(ax)
    t_p, v_p = unzip(ess_pwr)
    ax.plot(t_p, v_p, color='cyan', lw=0.8, label='DBL_ESSPwrAvg (kW, 0x598)')
    ax.axhline(0, color='white', lw=0.5, ls='--')
    ax.set_ylabel('ESS power (kW)')
    ax.legend(loc='upper right', fontsize=9)
    ax.set_title('ESS power (0x598 DBL_ESSPwrAvg, negative=regen)')

    # panel 4: motor torque + B4
    ax = axes[3]
    shade(ax)
    t_t, v_t = unzip(torque)
    t_b4, v_b4 = unzip(x420_b4)
    ax.plot(t_t,  [v / 40 for v in v_t],  color='magenta', lw=0.8, label='Motor torque /40')
    ax.plot(t_b4, v_b4,                    color='lime',    lw=1.0, label='0x420 B4 (unknown)')
    ax.set_ylabel('Counts')
    ax.set_xlabel('Time (s)')
    ax.legend(loc='upper right', fontsize=9)
    ax.set_title('Motor torque reference + 0x420 B4 (unknown byte)')

    import matplotlib.patches as mpatches
    patches = [mpatches.Patch(color=c, alpha=a+0.3, label=l)
               for _, _, l, c, a in event_regions]
    fig.legend(handles=patches, loc='upper left', fontsize=8, bbox_to_anchor=(0.01, 0.99))

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    out = Path(__file__).parent / "verify_0x420_limits.png"
    plt.savefig(out, dpi=130, bbox_inches='tight')
    print(f"\nPlot saved to {out}")

except Exception as e:
    print(f"\nPlot skipped: {e}")
