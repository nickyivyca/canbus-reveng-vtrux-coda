"""
Phase 2: Compute coolant dT/dt for three windows around the HVAC on/off event.
Windows defined by event timestamps from plot inspection:
  - HVAC on  (driving to quarry): t = 1668.9 to 1833
  - HVAC off (heat soak):         t = 1833   to 1985
  - HVAC on  (back on):           t = 1985   to end (~2010)

Uses coolant_temp_part2.csv (0x4C1 B2, raw - 40 = degC).
"""

import csv

COOLANT_OFFSET = -40

HVAC_ON_A  = (1668.9, 1833.0)   # driving to quarry, heater on
HVAC_OFF   = (1833.0, 1985.0)   # stopped, heater off (heat soak)
HVAC_ON_B  = (1985.0, 2011.0)   # heater back on

def read_csv(path):
    rows = []
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((float(row['timestamp']), int(row['value'])))
    return rows

def window_stats(data, t_start, t_end, label):
    w = [(t, v + COOLANT_OFFSET) for t, v in data if t_start <= t <= t_end]
    if len(w) < 2:
        print(f"  {label}: insufficient data")
        return
    t0, v0 = w[0]
    t1, v1 = w[-1]
    dt_s = t1 - t0
    dv   = v1 - v0
    rate = dv / dt_s * 60  # degC/min
    print(f"  {label}")
    print(f"    t = {t0:.1f} to {t1:.1f}s  ({dt_s:.0f}s)")
    print(f"    coolant: {v0:.0f} -> {v1:.0f} degC  (delta={dv:+.0f} degC)")
    print(f"    dT/dt = {rate:+.3f} degC/min")
    print()
    return rate

cool = read_csv("notes/artifacts/coolant_temp_part2.csv")

print("=== Phase 2: Coolant dT/dt by HVAC window ===")
print()
r_on_a = window_stats(cool, *HVAC_ON_A,  "HVAC ON  (driving, heater on)")
r_off  = window_stats(cool, *HVAC_OFF,   "HVAC OFF (stopped, heat soak)")
r_on_b = window_stats(cool, *HVAC_ON_B,  "HVAC ON  (back on, end of log)")

print("=== Summary ===")
if r_on_a and r_off:
    diff = r_on_a - r_off
    print(f"  dT/dt difference (heater-on vs heater-off): {diff:+.3f} degC/min")
    print(f"  Heater-off soak rate positive = engine still hot with no extraction")
    print(f"  Heater-on rate negative = fan extracting heat faster than residual production")
print()

# Also print all raw coolant readings in each window for reference
for label, t_start, t_end in [
    ("HVAC ON (driving)", *HVAC_ON_A),
    ("HVAC OFF (soak)",   *HVAC_OFF),
    ("HVAC ON (back on)", *HVAC_ON_B),
]:
    w = [(t, v + COOLANT_OFFSET) for t, v in cool if t_start <= t <= t_end]
    prev = None
    changed = [(t, v) for t, v in w if v != prev and not (prev := v) == None or (prev := v) is not None]
    # simpler deduplicate
    deduped = []
    last = None
    for t, v in w:
        if v != last:
            deduped.append((t, v))
            last = v
    print(f"  {label}: unique readings")
    for t, v in deduped:
        print(f"    t={t:8.1f}s  {v:5.1f} degC")
    print()
