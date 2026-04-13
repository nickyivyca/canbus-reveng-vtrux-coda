"""
Phase 3 plot: Parts 3 and 4 side-by-side.
4x2 grid: HV battery current / coolant temp / OAT powertrain est / blower fan speed.
Part 3 (warm engine, EV+gen) on left; Part 4 (battery-only, ~2h later) on right.
Shared Y axes across rows for direct comparison.
"""

import csv
import os
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

CURRENT_CENTER = 32768
CURRENT_SCALE  = 0.04
COOLANT_SCALE  = 1.0
COOLANT_OFFSET = -40
OAT_SCALE      = 0.5
OAT_OFFSET     = -40
BLOWER_SCALE   = 0.392157   # Climate_Control_Front_Blower_Fan_Speed, %/count

BLOWER_ID  = 0x451
BLOWER_BUS = None   # present on both GM buses; no bus filter needed

LOG_PART3 = "logs/vtruxanotherevaplogpart3.log"
CSV_BLOWER3 = "notes/artifacts/blower_part3.csv"


def read_csv(path):
    rows = []
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((float(row['timestamp']), int(row['value'])))
    return rows


def extract_blower(log_path, csv_path):
    """Extract 0x451 B4 timeseries from log and save to CSV."""
    frames = list(parse_file(log_path))
    t0 = frames[0].timestamp if frames else 0.0
    rows = []
    seen_buses = set()
    for f in frames:
        if f.arbitration_id == BLOWER_ID:
            seen_buses.add(f.bus)
    # Pick the lowest-numbered bus if bridged on both (consistent with prior extraction)
    target_bus = min(seen_buses) if seen_buses else None
    for f in frames:
        if f.arbitration_id == BLOWER_ID and f.bus == target_bus and len(f.data) >= 5:
            rows.append((f.timestamp - t0, f.data[4]))
    with open(csv_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['timestamp', 'value'])
        for t, v in rows:
            w.writerow([f'{t:.6f}', v])
    print(f"Extracted {len(rows)} blower frames -> {csv_path}  (bus {target_bus})")
    return rows


def decode_current(rows):
    return [(t, (v - CURRENT_CENTER) * CURRENT_SCALE) for t, v in rows]

def decode_coolant(rows):
    return [(t, v * COOLANT_SCALE + COOLANT_OFFSET) for t, v in rows]

def decode_oat(rows):
    return [(t, v * OAT_SCALE + OAT_OFFSET) for t, v in rows]

def decode_blower(rows):
    return [(t, v * BLOWER_SCALE) for t, v in rows]


if not os.path.exists(CSV_BLOWER3):
    extract_blower(LOG_PART3, CSV_BLOWER3)

p3_cool = decode_coolant(read_csv("notes/artifacts/coolant_temp_part3.csv"))
p3_curr = decode_current(read_csv("notes/artifacts/batt_current_le_part3.csv"))
p3_oat  = decode_oat(read_csv("notes/artifacts/oat_powertrain_part3.csv"))
p3_blow = decode_blower(read_csv(CSV_BLOWER3))
p4_cool = decode_coolant(read_csv("notes/artifacts/coolant_temp_part4.csv"))
p4_curr = decode_current(read_csv("notes/artifacts/batt_current_le_part4.csv"))
p4_oat  = decode_oat(read_csv("notes/artifacts/oat_powertrain_part4.csv"))
p4_blow = decode_blower(read_csv("notes/artifacts/blower_part4.csv"))

for label, cool, curr, oat, blow in [
    ("Part 3", p3_cool, p3_curr, p3_oat, p3_blow),
    ("Part 4", p4_cool, p4_curr, p4_oat, p4_blow),
]:
    print(f"{label}: coolant {min(v for _,v in cool):.0f}-{max(v for _,v in cool):.0f} degC  "
          f"OAT {min(v for _,v in oat):.0f}-{max(v for _,v in oat):.0f} degC  "
          f"current {min(v for _,v in curr):.0f}-{max(v for _,v in curr):.0f} A  "
          f"blower {min(v for _,v in blow):.0f}-{max(v for _,v in blow):.0f}%  "
          f"dur {cool[-1][0]:.0f}s")

fig, axes = plt.subplots(4, 2, figsize=(16, 13),
                         gridspec_kw={'hspace': 0.08, 'wspace': 0.06})
(ax_c3, ax_c4), (ax_t3, ax_t4), (ax_o3, ax_o4), (ax_b3, ax_b4) = axes

# --- HV current row ---
for ax, data, label in [
    (ax_c3, p3_curr, "Part 3  (engine warm, EV+gen)"),
    (ax_c4, p4_curr, "Part 4  (battery-only, ~2h later)"),
]:
    ts = [t for t, v in data]
    vs = [v for t, v in data]
    ax.plot(ts, vs, color='steelblue', linewidth=0.7)
    ax.axhline(0, color='black', linewidth=0.4, linestyle=':')
    ax.set_title(label, fontsize=9)
    ax.grid(True, alpha=0.25)
    ax.set_xticklabels([])

ax_c3.set_ylabel('HV Batt Current (A)\n+ = discharge', fontsize=8)
ax_c4.set_yticklabels([])
c_min = min(min(v for _,v in p3_curr), min(v for _,v in p4_curr)) - 10
c_max = max(max(v for _,v in p3_curr), max(v for _,v in p4_curr)) + 10
ax_c3.set_ylim(c_min, c_max)
ax_c4.set_ylim(c_min, c_max)

# --- Coolant temp row ---
for ax, data in [(ax_t3, p3_cool), (ax_t4, p4_cool)]:
    ts = [t for t, v in data]
    vs = [v for t, v in data]
    ax.plot(ts, vs, color='firebrick', linewidth=1.2)
    ax.grid(True, alpha=0.25)
    ax.set_xticklabels([])

ax_t3.set_ylabel('Coolant Temp (degC)\n0x4C1 B2', fontsize=8)
ax_t4.set_yticklabels([])
t_min = min(min(v for _,v in p3_cool), min(v for _,v in p4_cool)) - 2
t_max = max(max(v for _,v in p3_cool), max(v for _,v in p4_cool)) + 2
ax_t3.set_ylim(t_min, t_max)
ax_t4.set_ylim(t_min, t_max)

# --- OAT Powertrain Estimated row ---
for ax, data in [(ax_o3, p3_oat), (ax_o4, p4_oat)]:
    ts = [t for t, v in data]
    vs = [v for t, v in data]
    ax.plot(ts, vs, color='darkorange', linewidth=1.2)
    ax.grid(True, alpha=0.25)
    ax.set_xticklabels([])

ax_o3.set_ylabel('0x4C1 B4 (degC)\nOAT Powertrain Est', fontsize=8)
ax_o4.set_yticklabels([])
o_min = min(min(v for _,v in p3_oat), min(v for _,v in p4_oat)) - 2
o_max = max(max(v for _,v in p3_oat), max(v for _,v in p4_oat)) + 2
ax_o3.set_ylim(o_min, o_max)
ax_o4.set_ylim(o_min, o_max)

# --- Blower fan speed row ---
for ax, data in [(ax_b3, p3_blow), (ax_b4, p4_blow)]:
    ts = [t for t, v in data]
    vs = [v for t, v in data]
    ax.plot(ts, vs, color='seagreen', linewidth=0.9)
    ax.grid(True, alpha=0.25)
    ax.set_xlabel('Time (s)', fontsize=8)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(60))

ax_b3.set_ylabel('Blower Speed (%)\n0x451 B4', fontsize=8)
ax_b4.set_yticklabels([])
b_min = 0
b_max = max(max(v for _,v in p3_blow), max(v for _,v in p4_blow)) + 5
ax_b3.set_ylim(b_min, b_max)
ax_b4.set_ylim(b_min, b_max)

fig.suptitle('Phase 3: HV battery current + coolant temp + OAT est + blower fan speed\n'
             'Part 3 (warm engine, EV+gen)  vs  Part 4 (battery-only with heater)',
             fontsize=10)

out = "notes/plots/phase3_plot.png"
fig.savefig(out, dpi=150, bbox_inches='tight')
print(f"\nSaved to {out}")
