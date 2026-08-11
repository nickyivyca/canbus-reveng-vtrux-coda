"""
Plot 0x63F B3 (top post-gen-shutdown thermal correlator, r=0.939)
vs 0x06000002 B6 (confirmed motor temp reference, ~10C/count)
over the full log, with 30s bucket median smoothing.

Both are on PT Bus = Bus 3 in this log.
"""

import sys, collections
sys.path.insert(0, ".")

from canre.parsers import parse_file

LOG = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"
PT_BUS = 3
BUCKET = 30

# Event markers
PUMP_OFF = 393
CUTBACK  = 1953
PUMP_ON  = 2253
GEN_OFF  = 1410

data_63F_B3   = collections.defaultdict(list)
data_06000002_B6 = collections.defaultdict(list)

print("Reading log...", flush=True)
n = 0
for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t = frame.timestamp
    bucket = int(t // BUCKET) * BUCKET
    aid = frame.arbitration_id

    if aid == 0x63F and len(frame.data) > 3:
        data_63F_B3[bucket].append(frame.data[3])

    if aid == 0x06000002 and len(frame.data) > 6:
        data_06000002_B6[bucket].append(frame.data[6])

    n += 1
    if n % 1_000_000 == 0:
        print(f"  {n//1_000_000}M frames...", flush=True)

print(f"Done ({n} frames). Plotting...", flush=True)

def bucket_median(d):
    out = {}
    for k, vals in d.items():
        s = sorted(vals)
        out[k] = s[len(s)//2]
    return out

med_63F   = bucket_median(data_63F_B3)
med_B6    = bucket_median(data_06000002_B6)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

t_63F = sorted(med_63F)
v_63F = [med_63F[t] for t in t_63F]

t_B6 = sorted(med_B6)
v_B6 = [med_B6[t] for t in t_B6]

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
fig.suptitle("0x63F B3 vs 0x06000002 B6 -- 30s bucket medians, PT Bus", fontsize=13)

ax1.plot(t_63F, v_63F, color="tab:blue", linewidth=1.5, label="0x63F B3 (candidate)")
ax1.set_ylabel("0x63F B3 raw value")
ax1.set_ylim(-1, 35)
ax1.legend(loc="upper left")
ax1.grid(True, alpha=0.3)
for x, label in [(PUMP_OFF,"pump off"), (GEN_OFF,"gen off"), (CUTBACK,"cutback"), (PUMP_ON,"pump on")]:
    ax1.axvline(x, color="red", linestyle="--", linewidth=0.8)
    ax1.text(x+10, ax1.get_ylim()[1]*0.95, label, color="red", fontsize=8, rotation=90, va="top")

ax2.plot(t_B6, v_B6, color="tab:orange", linewidth=1.5, label="0x06000002 B6 (ref ~10C/cnt)")
ax2.set_ylabel("0x06000002 B6 raw value")
ax2.set_xlabel("Elapsed time (s)")
ax2.set_ylim(-1, 25)
ax2.legend(loc="upper left")
ax2.grid(True, alpha=0.3)
for x, label in [(PUMP_OFF,"pump off"), (GEN_OFF,"gen off"), (CUTBACK,"cutback"), (PUMP_ON,"pump on")]:
    ax2.axvline(x, color="red", linestyle="--", linewidth=0.8)
    ax2.text(x+10, ax2.get_ylim()[1]*0.95, label, color="red", fontsize=8, rotation=90, va="top")

plt.tight_layout()
out = "projects/vtrux/notes/artifacts/step3_63F_B3_vs_B6.png"
plt.savefig(out, dpi=150)
print(f"Saved: {out}")
