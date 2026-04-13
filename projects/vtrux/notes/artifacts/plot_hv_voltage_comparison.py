"""
Plot all confirmed/candidate HV DC voltage signals from vtruxevapdrivelog4part2.log.

Signals:
  0x18FFD6B3 B4-B5  LE signed x0.05 V  -- DCDC HV input (confirmed reference)
  0x482      B1-B2  LE uint16 x1.0 V   -- post-contactor (confirmed 1 V/count)
  0x470      B1-B2  LE uint16 x1.0 V   -- post-contactor (confirmed 1 V/count)
  0x440      B3-B4  LE uint16 ?         -- post-contactor, scale unconfirmed

Outputs linear regression of 0x440 raw vs DCDC to suggest scale/offset.
Saves plot to artifacts/hv_voltage_comparison.png
"""

import struct
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file as parse_log

LOG = os.path.join(os.path.dirname(__file__), '..', '..', 'logs', 'vtruxevapdrivelog4part2.log')
OUT_PNG = os.path.join(os.path.dirname(__file__), 'hv_voltage_comparison.png')

# Target IDs
DCDC_ID   = 0x18FFD6B3
ID_482    = 0x482
ID_470    = 0x470
ID_440    = 0x440

# Accumulate timeseries per signal
dcdc_ts   = []   # (t, V)
ts_482    = []
ts_470    = []
ts_440    = []   # (t, raw)

print("Parsing log...")
for frame in parse_log(LOG):
    t = frame.timestamp
    d = frame.data
    fid = frame.arbitration_id
    if fid == DCDC_ID and len(d) >= 6:
        raw = struct.unpack_from('<h', d, 4)[0]
        V = raw * 0.05
        if V > 50:   # ignore pre-contact noise
            dcdc_ts.append((t, V))
    elif fid == ID_482 and len(d) >= 3:
        raw = struct.unpack_from('<H', d, 1)[0]
        ts_482.append((t, float(raw)))
    elif fid == ID_470 and len(d) >= 3:
        raw = struct.unpack_from('<H', d, 1)[0]
        ts_470.append((t, float(raw)))
    elif fid == ID_440 and len(d) >= 5:
        raw = struct.unpack_from('<H', d, 3)[0]
        ts_440.append((t, float(raw)))

print(f"  DCDC samples:  {len(dcdc_ts)}")
print(f"  0x482 samples: {len(ts_482)}")
print(f"  0x470 samples: {len(ts_470)}")
print(f"  0x440 samples: {len(ts_440)}")

if not dcdc_ts:
    print("ERROR: No DCDC frames found -- check log or bus filter")
    sys.exit(1)

# --- Linear regression of 0x440 raw vs nearest DCDC sample ---
# Build a lookup: for each 0x440 sample find nearest DCDC V in time
def nearest_val(ref_ts, query_t, max_dt=0.5):
    """Return value from ref_ts nearest in time to query_t, or None."""
    best_v = None
    best_dt = max_dt
    # Simple linear scan (small enough dataset)
    for rt, rv in ref_ts:
        dt = abs(rt - query_t)
        if dt < best_dt:
            best_dt = dt
            best_v = rv
    return best_v

if ts_440 and dcdc_ts:
    paired = []
    for t, raw in ts_440:
        ref_v = nearest_val(dcdc_ts, t)
        if ref_v is not None:
            paired.append((raw, ref_v))

    if paired:
        import statistics
        raws  = [p[0] for p in paired]
        volts = [p[1] for p in paired]
        n = len(paired)
        mean_r = statistics.mean(raws)
        mean_v = statistics.mean(volts)
        # slope = cov(r,v) / var(r)
        cov = sum((r - mean_r) * (v - mean_v) for r, v in zip(raws, volts)) / n
        var = sum((r - mean_r) ** 2 for r in raws) / n
        slope = cov / var if var > 0 else 0.0
        intercept = mean_v - slope * mean_r
        # Pearson r
        std_r = (var ** 0.5)
        std_v = (sum((v - mean_v)**2 for v in volts) / n) ** 0.5
        pearson = cov / (std_r * std_v) if std_r * std_v > 0 else 0.0
        print(f"\n0x440 B3-B4 linear fit vs DCDC:")
        print(f"  scale  = {slope:.6f} V/count")
        print(f"  offset = {intercept:.2f} V")
        print(f"  Pearson r = {pearson:.4f}")
        print(f"  Example: raw=24788 -> {24788*slope+intercept:.1f} V")
        print(f"  Example: raw=1161  -> {1161*slope+intercept:.1f} V  (post-HVAC interlock)")
        print(f"  Example: raw=720   -> {720*slope+intercept:.1f} V   (post-HVD interlock)")
    else:
        slope, intercept, pearson = 0, 0, 0
        print("No paired 0x440 / DCDC samples found")
else:
    slope, intercept, pearson = 0, 0, 0

# --- Plot ---
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except ImportError:
    print("matplotlib not available -- skipping plot")
    sys.exit(0)

fig, ax = plt.subplots(figsize=(14, 6))

def unzip(ts): return [x[0] for x in ts], [x[1] for x in ts]

if dcdc_ts:
    t, v = unzip(dcdc_ts)
    ax.plot(t, v, color='black', lw=1.2, label='0x18FFD6B3 B4-B5 (DCDC HV, x0.05, confirmed)')

if ts_482:
    t, v = unzip(ts_482)
    ax.plot(t, v, color='tab:blue', lw=1.0, alpha=0.85, label='0x482 B1-B2 (1 V/count, confirmed)')

if ts_470:
    t, v = unzip(ts_470)
    ax.plot(t, v, color='tab:orange', lw=1.0, alpha=0.85, label='0x470 B1-B2 (1 V/count, confirmed)')

if ts_440 and slope != 0:
    t, raw = unzip(ts_440)
    v = [r * slope + intercept for r in raw]
    ax.plot(t, v, color='tab:green', lw=1.0, alpha=0.85,
            label=f'0x440 B3-B4 (fitted: x{slope:.5f}+{intercept:.1f}, r={pearson:.4f})')

ax.set_xlabel('Time (s)')
ax.set_ylabel('Voltage (V)')
ax.set_title('HV DC Voltage Signals -- vtruxevapdrivelog4part2.log')
ax.legend(loc='lower right', fontsize=8)
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(OUT_PNG, dpi=150)
print(f"\nPlot saved to: {OUT_PNG}")
