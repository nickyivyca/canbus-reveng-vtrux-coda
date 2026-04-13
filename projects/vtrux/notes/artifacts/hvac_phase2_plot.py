"""
Phase 2 plot: HV battery current + engine coolant temp, end of Part 2.
Two-panel plot covering t=1668.9s (gen shutoff) to end.
Annotated with first-pass event timestamp guesses.
"""

import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# --- Signal encoding ---
CURRENT_CENTER = 32768
CURRENT_SCALE  = 0.04     # A/count (working scale, unconfirmed)
COOLANT_OFFSET = -40      # degC = raw - 40

GEN_SHUTOFF = 1668.9

# --- First-pass event timestamp guesses ---
EVENTS = [
    (1668.9, "Gen shutoff",              "red"),
    (1833.0, "Truck stops / HVAC off",   "orange"),
    (1985.0, "HVAC back on",             "green"),
]

def read_csv(path):
    rows = []
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((float(row['timestamp']), int(row['value'])))
    return rows

batt = read_csv("notes/artifacts/batt_current_le_part2.csv")
cool = read_csv("notes/artifacts/coolant_temp_part2.csv")

# Decode and filter to post-gen-shutoff window
batt_t = [t for t, v in batt if t >= GEN_SHUTOFF]
batt_a = [(v - CURRENT_CENTER) * CURRENT_SCALE for t, v in batt if t >= GEN_SHUTOFF]

cool_t = [t for t, v in cool if t >= GEN_SHUTOFF]
cool_c = [v + COOLANT_OFFSET for t, v in cool if t >= GEN_SHUTOFF]

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
fig.subplots_adjust(hspace=0.08)

# --- Top: HV battery current ---
ax1.plot(batt_t, batt_a, color='steelblue', linewidth=0.7, label='HV batt current (0x598 B0-B1 LE)')
ax1.axhline(0, color='black', linewidth=0.4, linestyle=':')
ax1.set_ylabel('HV Battery Current (A)\n+ = discharge', fontsize=9)
ax1.legend(loc='upper right', fontsize=8)
ax1.grid(True, alpha=0.25)
ax1.set_title('Part 2 -- gen shutoff to end  |  HV current + coolant temp\n'
              'Event markers: first-pass guesses', fontsize=10)

# --- Bottom: coolant temp ---
ax2.plot(cool_t, cool_c, color='firebrick', linewidth=1.2, label='Coolant temp (0x4C1 B2, -40 offset)')
ax2.set_ylabel('Coolant Temp (degC)', fontsize=9)
ax2.set_xlabel('Time (s)', fontsize=9)
ax2.legend(loc='upper right', fontsize=8)
ax2.grid(True, alpha=0.25)

# --- Annotate events on both panels ---
for t, label, color in EVENTS:
    for ax in (ax1, ax2):
        ax.axvline(t, color=color, linestyle='--', linewidth=1.2, alpha=0.85)
    # label only on top panel
    ymin, ymax = ax1.get_ylim()
    # place label near top of ax1
    ax1.text(t + 2, 0.92, label, transform=ax1.get_xaxis_transform(),
             fontsize=7, color=color, va='top', rotation=0,
             bbox=dict(boxstyle='round,pad=0.2', fc='white', ec=color, alpha=0.7))

ax2.xaxis.set_major_locator(ticker.MultipleLocator(30))
ax2.xaxis.set_minor_locator(ticker.MultipleLocator(10))

fig.tight_layout()
out = "notes/artifacts/hvac_phase2_plot.png"
fig.savefig(out, dpi=150)
print(f"Saved to {out}")
