"""
Two tests on vtruxcurrentlimitingtest.log:

Test 1: Is 0x410 B3 the same signal as high-res SoC (0x411 B0-B1)?
  Pearson r of B3 vs decoded SoC%, plus scatter plot.

Test 2: LSB carry/borrow test for 0x440 B2-B3 and 0x410 B4-B5.
  If B3/B5 are true LSBs of a 16-bit value with B2/B4 as MSB, then:
    - when B3 overflows (255->0), B2 must increment by 1
    - when B3 underflows (0->255), B2 must decrement by 1
  Count how often this hold vs. violates.
"""
import sys, os, struct, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG = r'C:\Users\nicholas.ivy\seadrive_root\nickivyc_1\My Libraries\Projects\reverse-it\projects\vtrux\logs\vtruxcurrentlimitingtest.log'
OUT_PNG = os.path.join(os.path.dirname(__file__), 'scan_lsb_carry_and_soc.png')

ts_410b3 = []   # (t, B3)
ts_411   = []   # (t, decoded SoC%)
seq_440  = []   # (t, B2, B3)
seq_410  = []   # (t, B4, B5)

for frame in parse_file(LOG):
    fid = frame.arbitration_id
    d = frame.data
    t = frame.timestamp
    if fid == 0x410 and len(d) >= 4:
        ts_410b3.append((t, d[3]))
    if fid == 0x411 and len(d) >= 2:
        soc = (d[0] * 64 + (d[1] >> 2)) / 100.0
        ts_411.append((t, soc))
    if fid == 0x440 and len(d) >= 4:
        seq_440.append((t, d[2], d[3]))
    if fid == 0x410 and len(d) >= 6:
        seq_410.append((t, d[4], d[5]))

print(f"0x410 B3: {len(ts_410b3)}  0x411 SoC: {len(ts_411)}")
print(f"0x440 seq: {len(seq_440)}  0x410 B4-B5 seq: {len(seq_410)}")

# ---- Test 1: 0x410 B3 vs SoC ----------------------------------------
def nearest(ref, t, max_dt=1.0):
    best, bd = None, max_dt
    for rt, rv in ref:
        dt = abs(rt - t)
        if dt < bd: bd = dt; best = rv
    return best

# Use 0x411 as reference, pair to nearest 0x410 B3
paired = []
i = 0
for t411, soc in ts_411:
    while i+1 < len(ts_410b3) and abs(ts_410b3[i+1][0]-t411) < abs(ts_410b3[i][0]-t411):
        i += 1
    if abs(ts_410b3[i][0] - t411) <= 1.0:
        paired.append((soc, ts_410b3[i][1]))

xs = [p[0] for p in paired]
ys = [p[1] for p in paired]
n = len(paired)
mx, my = sum(xs)/n, sum(ys)/n
cov = sum((x-mx)*(y-my) for x,y in zip(xs,ys))/n
vx = sum((x-mx)**2 for x in xs)/n
vy = sum((y-my)**2 for y in ys)/n
r_soc = cov/math.sqrt(vx*vy) if vx*vy > 0 else 0
slope = cov/vx if vx > 0 else 0
intercept = my - slope*mx
print(f"\nTest 1: 0x410 B3 vs 0x411 SoC%")
print(f"  Pearson r = {r_soc:.4f}")
print(f"  Fit: B3 = {slope:.4f} * SoC% + {intercept:.2f}")
print(f"  At SoC=100%: B3 ~ {slope*100+intercept:.1f},  at SoC=0%: B3 ~ {intercept:.1f}")

# ---- Test 2: carry/borrow check -------------------------------------
OVERFLOW_THRESH = 200   # B3 goes from >THRESH to <(255-THRESH) = overflow up
UNDERFLOW_THRESH = 55   # B3 goes from <THRESH to >(255-THRESH) = overflow down

def carry_test(seq, msb_idx, lsb_idx, label):
    carry_ok = carry_fail = borrow_ok = borrow_fail = 0
    carry_examples = []
    borrow_examples = []
    for i in range(1, len(seq)):
        t0, t1 = seq[i-1][0], seq[i][0]
        msb0, lsb0 = seq[i-1][msb_idx], seq[i-1][lsb_idx]
        msb1, lsb1 = seq[i][msb_idx],   seq[i][lsb_idx]
        # Only check consecutive frames (not gaps)
        if t1 - t0 > 0.2: continue
        # Overflow: LSB went from high to low (carry into MSB)
        if lsb0 >= OVERFLOW_THRESH and lsb1 <= (255 - OVERFLOW_THRESH):
            expected_msb = (msb0 + 1) & 0xFF
            if msb1 == expected_msb:
                carry_ok += 1
            else:
                carry_fail += 1
                if len(carry_examples) < 5:
                    carry_examples.append(f"  t={t0:.2f} LSB {lsb0}->{lsb1} MSB {msb0}->{msb1} (expected {expected_msb})")
        # Underflow: LSB went from low to high (borrow from MSB)
        if lsb0 <= (255 - OVERFLOW_THRESH) and lsb1 >= OVERFLOW_THRESH:
            expected_msb = (msb0 - 1) & 0xFF
            if msb1 == expected_msb:
                borrow_ok += 1
            else:
                borrow_fail += 1
                if len(borrow_examples) < 5:
                    borrow_examples.append(f"  t={t0:.2f} LSB {lsb0}->{lsb1} MSB {msb0}->{msb1} (expected {expected_msb})")

    total_carry  = carry_ok + carry_fail
    total_borrow = borrow_ok + borrow_fail
    print(f"\nTest 2: carry/borrow check for {label}")
    print(f"  Overflow events (LSB wraps up):   {total_carry}  ->  carry OK: {carry_ok}  FAIL: {carry_fail}")
    if carry_fail and carry_examples:
        print("  Carry fail examples:")
        for e in carry_examples: print(e)
    print(f"  Underflow events (LSB wraps down): {total_borrow}  ->  borrow OK: {borrow_ok}  FAIL: {borrow_fail}")
    if borrow_fail and borrow_examples:
        print("  Borrow fail examples:")
        for e in borrow_examples: print(e)
    if total_carry + total_borrow == 0:
        print("  No overflow/underflow events found -- LSB may not wrap (check range)")
    elif carry_fail + borrow_fail == 0 and total_carry + total_borrow > 0:
        print("  PASS: all carry/borrow events respected MSB increment/decrement")
    else:
        total = total_carry + total_borrow
        ok    = carry_ok + borrow_ok
        print(f"  FAIL: {ok}/{total} ({100*ok/total:.1f}%) carry events correct")

# seq_440: (t, B2, B3) -> msb_idx=1, lsb_idx=2
carry_test(seq_440, msb_idx=1, lsb_idx=2, label="0x440 B2(MSB) B3(LSB)")
# seq_410: (t, B4, B5) -> msb_idx=1, lsb_idx=2
carry_test(seq_410, msb_idx=1, lsb_idx=2, label="0x410 B4(MSB) B5(LSB)")

# ---- Plot: B3 vs SoC ------------------------------------------------
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

# Scatter: SoC vs B3
ax1.scatter(xs, ys, s=2, alpha=0.3, color='tab:purple')
x_line = [min(xs), max(xs)]
y_line = [slope*x + intercept for x in x_line]
ax1.plot(x_line, y_line, color='red', lw=1.5, label=f'r={r_soc:.4f}')
ax1.set_xlabel('0x411 SoC (%)')
ax1.set_ylabel('0x410 B3 (raw byte)')
ax1.set_title('0x410 B3 vs high-res SoC (0x411)')
ax1.legend(fontsize=9)
ax1.grid(True, alpha=0.3)

# Time series overlay
t410, v410 = zip(*ts_410b3)
t411, v411 = zip(*ts_411)
ax2_r = ax2.twinx()
ax2.plot(t411, v411, color='tab:blue', lw=0.8, label='0x411 SoC% (left)')
ax2_r.plot(t410, v410, color='tab:purple', lw=0.8, alpha=0.7, label='0x410 B3 (right)')
ax2.set_xlabel('Time (s)')
ax2.set_ylabel('SoC (%)', color='tab:blue')
ax2_r.set_ylabel('0x410 B3 raw', color='tab:purple')
ax2.set_title('Time overlay: 0x411 SoC vs 0x410 B3')
lines1, labs1 = ax2.get_legend_handles_labels()
lines2, labs2 = ax2_r.get_legend_handles_labels()
ax2.legend(lines1+lines2, labs1+labs2, loc='upper right', fontsize=8)
ax2.grid(True, alpha=0.3)

fig.tight_layout()
fig.savefig(OUT_PNG, dpi=150)
print(f"\nPlot saved: {OUT_PNG}")
