#!/usr/bin/env python3
"""
Plot multi-signal view of the export session shutdown window.
Signals: battery DC current, AC output current, leg currents, cell V_min/V_max/V_avg, 0x411 B1.
Time window: t=7010-7025s  (shutdown at t=7019.49s)
"""
import sys
import os
sys.path.insert(0, r"<repo> Libraries\Projects\reverse-it")

from canre.parsers import parse_file
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

LOG = r"<repo> Libraries\Projects\reverse-it\projects\vtrux\logs\vtruxexporttest.log"
OUT = r"<repo> Libraries\Projects\reverse-it\projects\vtrux\notes\artifacts\export_shutdown_graph.png"

T_START = 7010.0
T_END   = 7025.0
SHUTDOWN_T = 7019.49

# CAN IDs
ID_HV_BATT = 0x18FFD7C0   # hvBatteryCurrent B2-B3 LE s16 x0.05, chargerInputCurrent B6-B7 LE s16 x0.05
ID_INV_OUT = 0x18FFD6C0   # leg1Current B4-B5 LE u16 x0.05, leg2Current B6-B7 LE u16 x0.05
ID_DCDC    = 0x18FFD6B3   # DCDC HV voltage B4-B5 LE s16 x0.05 V -> /117*1000 mV = avg cell mV
ID_CELL_V  = 0x430        # V_max (B0&0xF)*256+B1 mV, V_min (B2&0xF)*256+B3 mV; sentinel=4094
ID_411     = 0x411        # B1 countdown

def le_s16(data, lo):
    val = data[lo] | (data[lo+1] << 8)
    if val >= 0x8000:
        val -= 0x10000
    return val

def le_u16(data, lo):
    return data[lo] | (data[lo+1] << 8)

# (timestamps, values) tuples
ts = {k: [] for k in ['batt_dc', 'ac_out', 'leg1', 'leg2', 'vmin', 'vmax', 'vavg', 'cnt']}
vs = {k: [] for k in ts}

print("Scanning log (this may take several minutes for a 1.4GB file)...")
n = 0
for frame in parse_file(LOG):
    t = frame.timestamp
    if t > T_END:
        break
    if t < T_START:
        continue

    d = frame.data
    aid = frame.arbitration_id
    n += 1

    if aid == ID_HV_BATT and len(d) >= 8:
        ts['batt_dc'].append(t); vs['batt_dc'].append(le_s16(d, 2) * 0.05)
        ts['ac_out'].append(t);  vs['ac_out'].append(le_s16(d, 6) * 0.05)

    elif aid == ID_INV_OUT and len(d) >= 8:
        ts['leg1'].append(t); vs['leg1'].append(le_u16(d, 4) * 0.05)
        ts['leg2'].append(t); vs['leg2'].append(le_u16(d, 6) * 0.05)

    elif aid == ID_DCDC and len(d) >= 6:
        avg_mv = le_s16(d, 4) * 50.0 / 117.0   # x0.05V -> mV, /117 cells
        ts['vavg'].append(t); vs['vavg'].append(avg_mv)

    elif aid == ID_CELL_V and len(d) >= 4:
        vmax = (d[0] & 0x0F) * 256 + d[1]
        vmin = (d[2] & 0x0F) * 256 + d[3]
        if vmax != 4094:
            ts['vmax'].append(t); vs['vmax'].append(vmax)
        if vmin != 4094:
            ts['vmin'].append(t); vs['vmin'].append(vmin)

    elif aid == ID_411 and len(d) >= 2:
        ts['cnt'].append(t); vs['cnt'].append(d[1])

print("Frames in window: {}".format(n))
print("Samples per signal: " + ", ".join("{}={}".format(k, len(v)) for k, v in vs.items()))

# --- Plot ---
fig = plt.figure(figsize=(14, 10))
gs = gridspec.GridSpec(3, 1, hspace=0.42)

ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1])
ax3 = fig.add_subplot(gs[2])

# ---- Subplot 1: Currents ----
if ts['batt_dc']:
    ax1.plot(ts['batt_dc'], vs['batt_dc'], label='Battery DC  (hvBattCur A)', color='tab:blue', lw=1.5)
if ts['ac_out']:
    ax1.plot(ts['ac_out'], vs['ac_out'], label='AC out  (chargerInputCur A)', color='tab:orange', lw=1.5)
if ts['leg1']:
    ax1.plot(ts['leg1'], vs['leg1'], label='Leg1 AC (A)', color='tab:green', lw=1, alpha=0.75)
if ts['leg2']:
    ax1.plot(ts['leg2'], vs['leg2'], label='Leg2 AC (A)', color='tab:red', lw=1, alpha=0.75)
ax1.axvline(SHUTDOWN_T, color='darkred', ls='--', lw=1, alpha=0.7)
ax1.set_ylabel('Current (A)')
ax1.set_title('Export Session Shutdown Window  (vtruxexporttest.log, t=7010-7025s)')
ax1.legend(fontsize=8, loc='upper right')
ax1.grid(True, alpha=0.3)
ax1.set_xlim(T_START, T_END)

# ---- Subplot 2: Cell voltages ----
if ts['vmin']:
    ax2.plot(ts['vmin'], vs['vmin'], label='V_min (mV)', color='tab:red', lw=1.5)
if ts['vmax']:
    ax2.plot(ts['vmax'], vs['vmax'], label='V_max (mV)', color='tab:blue', lw=1.5)
if ts['vavg']:
    ax2.plot(ts['vavg'], vs['vavg'], label='V_avg = pack/117 (mV)', color='tab:purple', lw=1.5)
ax2.axvline(SHUTDOWN_T, color='darkred', ls='--', lw=1, alpha=0.7)
ax2.set_ylabel('Cell Voltage (mV)')
ax2.legend(fontsize=8, loc='upper right')
ax2.grid(True, alpha=0.3)
ax2.set_xlim(T_START, T_END)

# ---- Subplot 3: 0x411 B1 countdown ----
if ts['cnt']:
    ax3.step(ts['cnt'], vs['cnt'], where='post', label='0x411 B1 (raw)', color='tab:brown', lw=1.5)
ax3.axvline(SHUTDOWN_T, color='darkred', ls='--', lw=1, alpha=0.7, label='shutdown t={:.2f}s'.format(SHUTDOWN_T))
ax3.set_ylabel('0x411 B1')
ax3.set_xlabel('Time (s)')
ax3.legend(fontsize=8)
ax3.grid(True, alpha=0.3)
ax3.set_xlim(T_START, T_END)

plt.savefig(OUT, dpi=150, bbox_inches='tight')
print("Saved: {}".format(OUT))
