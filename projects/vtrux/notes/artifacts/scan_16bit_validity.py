"""
Three tests to determine whether B3/B5 are true LSBs of a 16-bit current signal.

Test 1: Cross-message equality
  First verify 0x440 B2 == 0x410 B4 (MSB) -- establishes pairing baseline.
  Then check 0x440 B3 == 0x410 B5 (LSB) -- must match if same 16-bit value.

Test 2: Step-size ratio
  If B3 is real precision: RMS(delta of B2*256+B3) < 256 * RMS(delta of B2)
  If B3 is noise/counter:  RMS(delta of B2*256+B3) > 256 * RMS(delta of B2)
  Report ratio; < 1.0 supports real LSB, > 1.0 supports noise/counter.

Test 3: Autocorrelation of delta-B3
  Free-running counter: delta-B3 is nearly constant -> very high autocorrelation.
  Analog LSB: delta-B3 varies with signal -> moderate/lower autocorrelation.
  Plot histogram of delta-B3 and compute lag-1 autocorrelation of deltas.
"""
import sys, os, struct, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG = r'C:\Users\nicholas.ivy\seadrive_root\nickivyc_1\My Libraries\Projects\reverse-it\projects\vtrux\logs\vtruxcurrentlimitingtest.log'
OUT = os.path.join(os.path.dirname(__file__), 'scan_16bit_validity.png')

seq_440 = []  # (t, B2, B3)
seq_410 = []  # (t, B4, B5)

for frame in parse_file(LOG):
    fid = frame.arbitration_id
    d = frame.data
    t = frame.timestamp
    if fid == 0x440 and len(d) >= 4:
        seq_440.append((t, d[2], d[3]))
    if fid == 0x410 and len(d) >= 6:
        seq_410.append((t, d[4], d[5]))

print(f"0x440 frames: {len(seq_440)}  0x410 frames: {len(seq_410)}")

# ---- Test 1: cross-message equality ---------------------------------
# Pair nearest frames within 0.05s (both broadcast at 20Hz so ~0.05s apart)
print("\n--- Test 1: Cross-message equality ---")
msb_equal = msb_diff = lsb_equal = lsb_diff = 0
msb_diff_examples = []
lsb_diff_examples = []
i410 = 0
for t440, b2, b3 in seq_440:
    while i410 + 1 < len(seq_410) and abs(seq_410[i410+1][0] - t440) < abs(seq_410[i410][0] - t440):
        i410 += 1
    t410, b4, b5 = seq_410[i410]
    if abs(t410 - t440) > 0.05:
        continue
    if b2 == b4:
        msb_equal += 1
    else:
        msb_diff += 1
        if len(msb_diff_examples) < 5:
            msb_diff_examples.append(f"  t={t440:.3f}: 0x440 B2={b2}  0x410 B4={b4}")
    if b3 == b5:
        lsb_equal += 1
    else:
        lsb_diff += 1
        if len(lsb_diff_examples) < 8:
            lsb_diff_examples.append(f"  t={t440:.3f}: 0x440 B3={b3}  0x410 B5={b5}  diff={b3-b5}")

total = msb_equal + msb_diff
print(f"MSB (B2 vs B4): {msb_equal}/{total} equal ({100*msb_equal/total:.1f}%)")
if msb_diff_examples:
    print("  MSB diff examples:"); [print(e) for e in msb_diff_examples]

total = lsb_equal + lsb_diff
print(f"LSB (B3 vs B5): {lsb_equal}/{total} equal ({100*lsb_equal/total:.1f}%)")
if lsb_diff_examples:
    print("  LSB diff examples:"); [print(e) for e in lsb_diff_examples]

# ---- Test 2: step-size ratio ----------------------------------------
print("\n--- Test 2: Step-size ratio ---")

def rms_deltas(vals):
    d = [vals[i+1] - vals[i] for i in range(len(vals)-1)]
    return math.sqrt(sum(x*x for x in d) / len(d)), d

for label, seq in [("0x440 B2-B3", seq_440), ("0x410 B4-B5", seq_410)]:
    # Only consecutive frames (no gaps > 0.2s)
    consec = [(seq[i], seq[i+1]) for i in range(len(seq)-1)
              if seq[i+1][0] - seq[i][0] < 0.2]
    msb_vals  = [f[0][1] for f in consec]
    msb_next  = [f[1][1] for f in consec]
    lsb_vals  = [f[0][2] for f in consec]
    lsb_next  = [f[1][2] for f in consec]

    delta_msb = [msb_next[i] - msb_vals[i] for i in range(len(msb_vals))]
    # 16-bit deltas (handle wrap for LSB: signed difference mod 256)
    delta_16 = [(msb_next[i] - msb_vals[i]) * 256 +
                ((lsb_next[i] - lsb_vals[i] + 128) % 256 - 128)
                for i in range(len(msb_vals))]

    rms_msb_scaled = math.sqrt(sum(x*x for x in delta_msb) / len(delta_msb)) * 256
    rms_16         = math.sqrt(sum(x*x for x in delta_16)  / len(delta_16))
    ratio = rms_16 / rms_msb_scaled if rms_msb_scaled > 0 else 0

    print(f"{label}:")
    print(f"  RMS(delta MSB)*256 = {rms_msb_scaled:.1f}")
    print(f"  RMS(delta 16-bit)  = {rms_16:.1f}")
    print(f"  Ratio = {ratio:.4f}  ({'< 1.0 -> LSB adds precision' if ratio < 1.0 else '> 1.0 -> LSB adds noise'})")

# ---- Test 3: autocorrelation of delta-B3/B5 -------------------------
print("\n--- Test 3: Autocorrelation of delta-LSB ---")

def autocorr_lag1(vals):
    n = len(vals)
    mean = sum(vals) / n
    var  = sum((v - mean)**2 for v in vals) / n
    cov  = sum((vals[i] - mean) * (vals[i+1] - mean) for i in range(n-1)) / (n-1)
    return cov / var if var > 0 else 0

import collections

for label, seq in [("0x440 B3 (LSB)", seq_440), ("0x410 B5 (LSB)", seq_410)]:
    consec_lsb = [seq[i][2] for i in range(len(seq)-1)
                  if seq[i+1][0] - seq[i][0] < 0.2]
    consec_lsb_next = [seq[i+1][2] for i in range(len(seq)-1)
                       if seq[i+1][0] - seq[i][0] < 0.2]
    deltas = [(consec_lsb_next[i] - consec_lsb[i] + 128) % 256 - 128
              for i in range(len(consec_lsb))]

    ac = autocorr_lag1(deltas)
    mean_d = sum(deltas) / len(deltas)
    std_d  = math.sqrt(sum((d - mean_d)**2 for d in deltas) / len(deltas))

    # Delta histogram (coarse, +-30 range)
    hist = collections.Counter(max(-30, min(30, d)) for d in deltas)

    print(f"{label}:")
    print(f"  delta mean={mean_d:.2f}  std={std_d:.1f}  lag-1 autocorr={ac:.4f}")
    print(f"  delta histogram (clipped to +-30):")
    for k in sorted(hist):
        bar = '#' * (hist[k] // 50)
        print(f"    {k:4d}: {hist[k]:5d} {bar}")

# ---- Plot ------------------------------------------------------------
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(14, 9))

# T1: MSB equality scatter
msb_440 = [f[1] for f in seq_440]
msb_410_paired = []
i410 = 0
for t440, b2, b3 in seq_440:
    while i410+1 < len(seq_410) and abs(seq_410[i410+1][0]-t440) < abs(seq_410[i410][0]-t440):
        i410 += 1
    if abs(seq_410[i410][0]-t440) <= 0.05:
        msb_410_paired.append(seq_410[i410][1])
    else:
        msb_410_paired.append(None)

msb_pairs = [(b2, m4) for (_, b2, _), m4 in zip(seq_440, msb_410_paired) if m4 is not None]
axes[0,0].scatter([p[0] for p in msb_pairs], [p[1] for p in msb_pairs], s=1, alpha=0.2)
axes[0,0].plot([77,191],[77,191], 'r--', lw=1)
axes[0,0].set_xlabel('0x440 B2'); axes[0,0].set_ylabel('0x410 B4')
axes[0,0].set_title('MSB equality: 0x440 B2 vs 0x410 B4')
axes[0,0].grid(True, alpha=0.3)

# T1: LSB equality scatter
lsb_440 = [(b3) for _,_,b3 in seq_440]
lsb_410_paired = []
i410 = 0
for t440, b2, b3 in seq_440:
    while i410+1 < len(seq_410) and abs(seq_410[i410+1][0]-t440) < abs(seq_410[i410][0]-t440):
        i410 += 1
    if abs(seq_410[i410][0]-t440) <= 0.05:
        lsb_410_paired.append(seq_410[i410][2])
    else:
        lsb_410_paired.append(None)

lsb_pairs = [(b3, l5) for (_,_,b3), l5 in zip(seq_440, lsb_410_paired) if l5 is not None]
axes[0,1].scatter([p[0] for p in lsb_pairs], [p[1] for p in lsb_pairs], s=1, alpha=0.15)
axes[0,1].plot([0,255],[0,255], 'r--', lw=1)
axes[0,1].set_xlabel('0x440 B3'); axes[0,1].set_ylabel('0x410 B5')
axes[0,1].set_title('LSB equality: 0x440 B3 vs 0x410 B5')
axes[0,1].grid(True, alpha=0.3)

# T3: delta histograms
for ax, label, seq, col in [
    (axes[1,0], '0x440 B3 delta', seq_440, 'tab:blue'),
    (axes[1,1], '0x410 B5 delta', seq_410, 'tab:orange'),
]:
    consec = [(seq[i][2], seq[i+1][2]) for i in range(len(seq)-1)
              if seq[i+1][0]-seq[i][0] < 0.2]
    deltas = [(b-a+128)%256-128 for a,b in consec]
    ax.hist(deltas, bins=range(-60, 61, 1), color=col, alpha=0.7)
    ac = autocorr_lag1(deltas)
    ax.set_title(f'{label}  lag-1 autocorr={ac:.4f}')
    ax.set_xlabel('delta (signed)')
    ax.set_ylabel('count')
    ax.grid(True, alpha=0.3)

fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nPlot saved: {OUT}")
