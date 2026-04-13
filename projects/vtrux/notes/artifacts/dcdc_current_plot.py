"""
DC-DC B2-B3 (likely LV output current) timeseries analysis and plot.
Focus: end of Part 2, from generator shutoff (t=1668.9s) to end.
Reports all steps; flags rapid steps (lights) vs slow ramps (fan motor).
"""

import csv
import sys
import math

GEN_SHUTOFF = 1668.9  # t of final generator shutoff in Part 2
RAMP_WINDOW = 3.0     # seconds -- if value changes slowly over >= this, flag as ramp
STEP_THRESHOLD = 50   # minimum count change to call a "step"

def read_csv(path):
    rows = []
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((float(row['timestamp']), int(row['value'])))
    return rows

data = read_csv("notes/artifacts/dcdc_lv_current_part2.csv")

# B3 upper nibble: mask to 12-bit (B3 can be 0-15 so LE uint16 = B2 + B3*256, already 12-bit)
# But double-check: strip any high nibble of B3 just in case
data12 = [(t, v & 0x0FFF) for t, v in data]

# Focus window: after generator shutoff
window = [(t, v) for t, v in data12 if t >= GEN_SHUTOFF]

print(f"DC-DC B2-B3 (12-bit LE) -- Part 2 after gen shutoff (t >= {GEN_SHUTOFF}s)")
print(f"Samples in window: {len(window)}")
if window:
    vals = [v for _, v in window]
    print(f"Value range: {min(vals)} to {max(vals)}  mean={sum(vals)/len(vals):.1f}")
print()

# Find all steps >= STEP_THRESHOLD counts between consecutive samples
print(f"=== All steps >= {STEP_THRESHOLD} counts (consecutive-sample deltas) ===")
print(f"  {'t_before':>10}  {'t_after':>10}  {'dt_s':>8}  {'v_before':>9}  {'v_after':>9}  {'delta':>7}  type")
steps = []
for i in range(1, len(window)):
    t0, v0 = window[i-1]
    t1, v1 = window[i]
    delta = v1 - v0
    if abs(delta) >= STEP_THRESHOLD:
        dt = t1 - t0
        # classify: if dt <= 1 sample (~0.1s) it's an instant step; longer = ramp start
        kind = "INSTANT" if dt < 0.2 else "SLOW"
        print(f"  {t0:10.2f}  {t1:10.2f}  {dt:8.3f}  {v0:9d}  {v1:9d}  {delta:+7d}  {kind}")
        steps.append((t0, t1, dt, v0, v1, delta, kind))

if not steps:
    print("  (none)")

print()

# Find slow ramps: windows where cumulative change over RAMP_WINDOW seconds is large
print(f"=== Slow ramps: cumulative change over {RAMP_WINDOW}s windows (step-by-step) ===")
print(f"  {'t_start':>10}  {'t_end':>10}  {'v_start':>9}  {'v_end':>9}  {'total_delta':>12}  rate/min")
i = 0
while i < len(window):
    t_start, v_start = window[i]
    # find end of ramp_window
    j = i
    while j < len(window) - 1 and window[j+1][0] - t_start < RAMP_WINDOW:
        j += 1
    t_end, v_end = window[j]
    total_delta = v_end - v_start
    dt = t_end - t_start
    if abs(total_delta) >= STEP_THRESHOLD and dt >= 1.0:
        rate = total_delta / dt * 60
        print(f"  {t_start:10.2f}  {t_end:10.2f}  {v_start:9d}  {v_end:9d}  {total_delta:+12d}  {rate:+.1f}/min")
    i = j + 1 if j > i else i + 1

print()
print("=== Raw sample dump (every sample in window) ===")
print(f"  {'timestamp':>12}  {'raw_12bit':>10}  {'delta':>7}")
prev_v = None
for t, v in window:
    delta = (v - prev_v) if prev_v is not None else 0
    delta_str = f"{delta:+7d}" if prev_v is not None else "      -"
    print(f"  {t:12.2f}  {v:10d}  {delta_str}")
    prev_v = v

# --- PLOT ---
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker

    fig, ax = plt.subplots(figsize=(14, 5))

    ts = [t for t, v in window]
    vs = [v for t, v in window]

    ax.plot(ts, vs, color='steelblue', linewidth=0.8, label='DC-DC B2-B3 (12-bit LE)')

    # Mark gen shutoff
    ax.axvline(GEN_SHUTOFF, color='red', linestyle='--', linewidth=1.2, label=f'Gen shutoff t={GEN_SHUTOFF}s')

    # Mark instant steps
    for t0, t1, dt, v0, v1, delta, kind in steps:
        color = 'orange' if kind == 'INSTANT' else 'green'
        ax.axvline(t0, color=color, linestyle=':', linewidth=0.8, alpha=0.7)

    ax.set_xlabel('Time (s)')
    ax.set_ylabel('DC-DC B2-B3 raw 12-bit value')
    ax.set_title('DC-DC 0x18FFD6B3 B2-B3 -- Part 2 after generator shutoff\n'
                 'Orange dashed = instant step (lights?), Green dashed = slow step')
    ax.legend(loc='upper right', fontsize=8)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(30))
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out_path = "notes/artifacts/dcdc_current_part2_plot.png"
    fig.savefig(out_path, dpi=150)
    print(f"\nPlot saved to {out_path}")
except ImportError:
    print("\n(matplotlib not available -- skipping plot)")
