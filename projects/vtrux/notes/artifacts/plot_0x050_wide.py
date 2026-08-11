"""
plot_0x050_wide.py

Investigate whether 0x050 B0 is only the low byte of a wider signal.
B1 has 3 values (32-34 = 0x20-0x22), meaning bits 1-0 of B1 vary (0,1,2).
B2 has 6 values (237-242 = 0xED-0xF2), meaning bits 2-0 vary.

Tests:
  A) B0 alone (8-bit)
  B) 10-bit: (B1 & 0x03) << 8 | B0   -- B1 low 2 bits as MSB
  C) LE uint16 B0-B1                  -- B0=low, B1=high
  D) (B2 & 0x07) << 10 | (B1&0x03)<<8 | B0   -- 13-bit if B2 contributes too

For each: compute Pearson r vs traction torque feedback in the three segments.
Plot the widened signal vs traction feedback scaled to match.
Also plot transitions: when does B1 change? When does B2 change?

Output: plot_0x050_wide.png
"""

import sys, os, math, bisect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG    = 'projects/vtrux/logs/vtruxevapdrivelog4.log'
PT_BUS = 2
OUTPUT = 'projects/vtrux/notes/artifacts/plot_0x050_wide.png'

SEGMENTS = {'pre_hybrid':(431,720), 'cruise':(720,1080), 'post_hybrid':(1122,1462)}
MARKERS = {431:'gen start', 720:'cruise start', 1103:'exit', 1108:'brake'}

print("Parsing...")
b0_raw=[]; b1_raw=[]; b2_raw=[]; tract_fb=[]

for frame in parse_file(LOG):
    if frame.bus != PT_BUS: continue
    t=frame.timestamp; d=frame.data; aid=frame.arbitration_id
    if aid==0x050 and len(d)>=3:
        b0_raw.append((t, d[0], d[1], d[2]))
    elif aid==0x5A2 and len(d)>=6:
        tract_fb.append((t, ((d[5]<<8)|d[4])-32768))

print(f"0x050 frames: {len(b0_raw)}  traction samples: {len(tract_fb)}")

# Sort traction for nearest-value lookup
tract_fb.sort()
tf_t=[x[0] for x in tract_fb]; tf_v=[x[1] for x in tract_fb]

def nearest(st,sv,t,tol=0.15):
    idx=bisect.bisect_left(st,t)
    bv=None; bd=tol+1
    for i in (idx-1,idx):
        if 0<=i<len(st):
            dt=abs(st[i]-t)
            if dt<bd: bd=dt; bv=sv[i]
    return bv if bd<=tol else None

def pearson(xs,ys,min_n=10):
    n=len(xs)
    if n<min_n: return float('nan')
    mx=sum(xs)/n; my=sum(ys)/n
    cov=sum((a-mx)*(b-my) for a,b in zip(xs,ys))/n
    sx=math.sqrt(sum((x-mx)**2 for x in xs)/n)
    sy=math.sqrt(sum((y-my)**2 for y in ys)/n)
    return cov/(sx*sy) if sx>1e-9 and sy>1e-9 else float('nan')

# Build candidate signals
# A: B0 alone, center 128
# B: (B1&3)<<8 | B0, center at (1<<9)=512  (midpoint of 0-767 range)
# C: LE16 B0+B1*256, center at midpoint
# D: 13-bit (B2&7)<<10|(B1&3)<<8|B0, center at midpoint
sigs = {
    'A_B0_8bit':   [(t, b0-128)              for t,b0,b1,b2 in b0_raw],
    'B_10bit':     [(t, ((b1&3)<<8|b0) - (1<<9))   for t,b0,b1,b2 in b0_raw],
    'C_LE16':      [(t, (b0 + b1*256) - ((32*256+128)//2*2))  for t,b0,b1,b2 in b0_raw],
    'D_13bit':     [(t, ((b2&7)<<10|(b1&3)<<8|b0) - (1<<12)) for t,b0,b1,b2 in b0_raw],
}

# Also track B1 and B2 change events
b1_changes=[]; b2_changes=[]
prev_b1=None; prev_b2=None
for t,b0,b1,b2 in b0_raw:
    if prev_b1 is not None and b1!=prev_b1:
        b1_changes.append((t, b1-32))   # relative to min (32)
    if prev_b2 is not None and b2!=prev_b2:
        b2_changes.append((t, b2-237))  # relative to min (237)
    prev_b1=b1; prev_b2=b2

print(f"\nB1 transitions: {len(b1_changes)}  B2 transitions: {len(b2_changes)}")
print(f"B1 change times (first 30): {[round(t,1) for t,v in b1_changes[:30]]}")
print(f"B2 change times (first 20): {[round(t,1) for t,v in b2_changes[:20]]}")

# Print correlation table
print(f"\n{'Signal':15s}  {'pre_hybrid':>10s}  {'cruise':>10s}  {'post_hybrid':>10s}")
print('-'*52)
for name, s in sigs.items():
    s.sort()
    st=[x[0] for x in s]; sv=[x[1] for x in s]
    row=[]
    for seg,(t0,t1) in SEGMENTS.items():
        seg_s=[(t,v) for t,v in s if t0<=t<t1]
        seg_tf=[nearest(tf_t,tf_v,t) for t,_ in seg_s]
        pairs=[(b,g) for (_,b),g in zip(seg_s,seg_tf) if g is not None]
        r=pearson([p[0] for p in pairs],[p[1] for p in pairs])
        row.append(r)
    print(f'{name:15s}  {row[0]:+10.4f}  {row[1]:+10.4f}  {row[2]:+10.4f}')

# Check if B1 transitions coincide with any known events
print(f"\nB1 transitions vs known events:")
for t,dv in b1_changes:
    note=''
    if 430<=t<435: note='<-- gen start'
    elif 715<=t<725: note='<-- cruise start'
    elif 1100<=t<1110: note='<-- exit cluster'
    print(f"  t={t:8.3f}  B1_delta={dv:+d}  {note}")

# -----------------------------------------------------------------------
# Plot
# -----------------------------------------------------------------------
print("\nPlotting...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(4, 1, figsize=(18, 14), sharex=True)
fig.suptitle('0x050: B0 alone vs wider bit combinations\nvtruxevapdrivelog4.log', fontsize=12)

MCOL = {431:'green', 720:'blue', 1103:'orange', 1108:'red'}

def mlines(ax):
    for tm,lb in MARKERS.items():
        ax.axvline(tm, color=MCOL[tm], lw=1.0, ls='--', alpha=0.7)
    ax.axhline(0, color='k', lw=0.4, ls=':')

tf_t2=[x[0] for x in tract_fb]
tf_v2=[x[1] for x in tract_fb]

# Panel 1: B0 alone vs traction feedback
ax=axes[0]
ts_a,vs_a=zip(*sigs['A_B0_8bit'])
ax.plot(ts_a,vs_a,color='purple',lw=0.7,label='B0 alone (centered 128)')
ax.plot(tf_t2,[v/64 for v in tf_v2],color='steelblue',lw=0.5,alpha=0.6,
        label='Traction fb (0x5A2 B4-B5) /64')
mlines(ax)
ax.set_ylabel('counts'); ax.legend(loc='upper left',fontsize=8)
ax.set_title('A: B0 alone (8-bit)')

# Panel 2: 10-bit (B1 low 2 bits as MSB) vs traction feedback
ax=axes[1]
ts_b,vs_b=zip(*sigs['B_10bit'])
scale_b = max(abs(v) for v in vs_b) / max(abs(v) for v in tf_v2) if tf_v2 else 1
ax.plot(ts_b,vs_b,color='darkgreen',lw=0.7,label='(B1&3)<<8|B0 - 512 (10-bit)')
ax.plot(tf_t2,[v/8 for v in tf_v2],color='steelblue',lw=0.5,alpha=0.6,
        label='Traction fb /8')
mlines(ax)
ax.set_ylabel('counts'); ax.legend(loc='upper left',fontsize=8)
ax.set_title('B: (B1 low-2-bits)<<8 | B0  (10-bit wide)')

# Panel 3: 13-bit
ax=axes[2]
ts_d,vs_d=zip(*sigs['D_13bit'])
ax.plot(ts_d,vs_d,color='firebrick',lw=0.7,label='(B2&7)<<10|(B1&3)<<8|B0 - 4096 (13-bit)')
ax.plot(tf_t2,[v/1 for v in tf_v2],color='steelblue',lw=0.5,alpha=0.6,
        label='Traction fb (raw centered)')
mlines(ax)
ax.set_ylabel('counts'); ax.legend(loc='upper left',fontsize=8)
ax.set_title('D: 13-bit (B2 low-3-bits + B1 low-2-bits + B0)')

# Panel 4: B1 and B2 raw values + traction feedback
ax=axes[3]
ts_all=[x[0] for x in b0_raw]
b1_vals=[x[2]-32 for x in b0_raw]  # B1 relative to min (32)
b2_vals=[x[3]-237 for x in b0_raw] # B2 relative to min (237)
ax2=ax.twinx()
ax.plot(ts_all, b1_vals, color='orangered', lw=0.8, drawstyle='steps-post',
        label='B1-32 (0,1,2)', alpha=0.8)
ax.plot(ts_all, b2_vals, color='goldenrod', lw=0.6, drawstyle='steps-post',
        label='B2-237 (0..5)', alpha=0.8)
ax2.plot(tf_t2,[v/512 for v in tf_v2],color='steelblue',lw=0.5,alpha=0.5,
         label='Traction fb /512')
ax.set_ylabel('B1/B2 relative value'); ax2.set_ylabel('Traction fb /512')
lines1,labs1=ax.get_legend_handles_labels()
lines2,labs2=ax2.get_legend_handles_labels()
ax.legend(lines1+lines2,labs1+labs2,loc='upper left',fontsize=8)
mlines(ax)
ax.set_xlabel('Time (s)')
ax.set_title('B1 and B2 raw variation (step-plot) vs traction feedback')

plt.tight_layout()
plt.savefig(OUTPUT, dpi=130, bbox_inches='tight')
print(f"Saved: {OUTPUT}")
