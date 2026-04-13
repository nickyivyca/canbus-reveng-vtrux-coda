"""
Scatter + overlay: 0x440 B2 (flipped: 255-B2) vs 0x598 B0-B1 battery current.
Log: vtruxcurrentlimitingtest.log
"""
import sys, os, struct, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG = r'C:\Users\nicholas.ivy\seadrive_root\nickivyc_1\My Libraries\Projects\reverse-it\projects\vtrux\logs\vtruxcurrentlimitingtest.log'
OUT = os.path.join(os.path.dirname(__file__), 'plot_440b2_vs_598_current.png')

ts_440b2, ts_598 = [], []

for frame in parse_file(LOG):
    fid = frame.arbitration_id
    d = frame.data
    t = frame.timestamp
    if fid == 0x440 and len(d) >= 3:
        ts_440b2.append((t, 255 - d[2]))   # flipped
    elif fid == 0x598 and len(d) >= 2:
        raw = struct.unpack_from('<H', d, 0)[0]
        ts_598.append((t, raw - 32768))

print(f"0x440 B2 (flipped): {len(ts_440b2)}  0x598 batt: {len(ts_598)}")

# Nearest-match pairing (max 0.5s)
ref = ts_598   # lower rate -- pair each 598 sample to nearest 440
paired = []
ts440_arr = ts_440b2
i440 = 0
for t_ref, v_ref in ref:
    # advance i440 to nearest
    while i440 + 1 < len(ts440_arr) and abs(ts440_arr[i440+1][0] - t_ref) < abs(ts440_arr[i440][0] - t_ref):
        i440 += 1
    dt = abs(ts440_arr[i440][0] - t_ref)
    if dt <= 0.5:
        paired.append((v_ref, ts440_arr[i440][1]))

print(f"Paired samples: {len(paired)}")

xs = [p[0] for p in paired]   # 0x598 current (raw-32768)
ys = [p[1] for p in paired]   # 255 - 0x440 B2

# Linear fit
n = len(xs)
mx, my = sum(xs)/n, sum(ys)/n
cov = sum((x-mx)*(y-my) for x,y in zip(xs,ys))/n
vx  = sum((x-mx)**2 for x in xs)/n
vy  = sum((y-my)**2 for y in ys)/n
slope = cov/vx if vx > 0 else 0
intercept = my - slope*mx
r = cov / math.sqrt(vx*vy) if vx*vy > 0 else 0
print(f"Linear fit: y = {slope:.6f}*x + {intercept:.2f}  r={r:.4f}")

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9))

# Panel 1: time overlay -- scale 440 B2 to 598 units for visual comparison
# scaled_440 = (y - intercept) / slope
ax1_r = ax1.twinx()
t440, v440 = zip(*ts_440b2)
t598, v598 = zip(*ts_598)
ax1.plot(t598, v598, color='tab:green', lw=0.8, alpha=0.8, label='0x598 B0-B1 (raw-32768, left)')
ax1_r.plot(t440, v440, color='tab:blue', lw=0.8, alpha=0.7, label='255 - 0x440 B2 (right)')
ax1.set_ylabel('0x598 batt current (counts)', color='tab:green')
ax1_r.set_ylabel('255 - 0x440 B2', color='tab:blue')
ax1.set_title('0x440 B2 (flipped) vs 0x598 battery current -- vtruxcurrentlimitingtest.log')
lines1, labs1 = ax1.get_legend_handles_labels()
lines2, labs2 = ax1_r.get_legend_handles_labels()
ax1.legend(lines1+lines2, labs1+labs2, loc='upper right', fontsize=8)
ax1.grid(True, alpha=0.3)

# Panel 2: scatter
ax2.scatter(xs, ys, s=3, alpha=0.4, color='tab:blue')
x_line = [min(xs), max(xs)]
y_line = [slope*x + intercept for x in x_line]
ax2.plot(x_line, y_line, color='red', lw=1.5, label=f'fit: slope={slope:.5f}  r={r:.4f}')
ax2.set_xlabel('0x598 B0-B1 battery current (raw-32768)')
ax2.set_ylabel('255 - 0x440 B2')
ax2.set_title('Scatter: 0x440 B2 (flipped) vs 0x598 battery current')
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.3)

fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"Saved: {OUT}")
