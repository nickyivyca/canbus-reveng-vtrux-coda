"""
scan_ccl_bits.py

Find BMS-originated bit transitions that align with the two CCL step-change
inflection points in vtruxcurrentlimitingtest.log.

Approach:
  1. Extract CCL (0x050) in t=300-400s; print 1s-bucket table to show both steps.
  2. Auto-detect the two inflection times via threshold crossing.
  3. For every bit in every BMS-originated byte, find state-transition times.
  4. Score bits by proximity to both inflections.
  5. Print top candidates and save a multi-panel plot.

BMS-originated IDs (drop at BMS LV connector unplug):
  0x370-0x375, 0x400, 0x410-0x412, 0x420, 0x430, 0x440, 0x460, 0x506, 0x507

Output:
  scan_ccl_bits_output.txt  -- text report (run with redirect)
  plot_ccl_bits.png         -- CCL + top bit candidates
"""

import os, sys, collections, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG    = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                      '..', '..', 'logs',
                                      'vtruxcurrentlimitingtest.log'))
OUTPUT_PNG = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                           'plot_ccl_bits.png'))

BMS_IDS = set([
    0x370, 0x371, 0x372, 0x373, 0x374, 0x375,
    0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460,
    0x506, 0x507,
])

T_SCAN_START = 300.0
T_SCAN_END   = 410.0

# Step-detection thresholds (raw CCL 10-bit)
STEP1_THRESH = 260   # first partial step (baseline ~322 drops below this)
STEP2_THRESH = 100   # deep step (near-zero region)
STEP_HOLD    = 3.0   # must stay below threshold for this many seconds
# Scoring window: bit transition must occur within this many seconds of inflection
SCORE_WINDOW = 15.0

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
print("Detecting PT bus ...")
bus_051 = {}
for frame in parse_file(LOG):
    if frame.arbitration_id == 0x051:
        bus_051[frame.bus] = bus_051.get(frame.bus, 0) + 1
    if sum(bus_051.values()) > 200:
        break
if not bus_051:
    raise RuntimeError("0x051 not found")
PT_BUS = max(bus_051, key=bus_051.get)
print(f"PT bus = {PT_BUS}")

print("Parsing ...")
ccl_ts = []               # (t, raw_ccl) -- full log for threshold detection
bms_data = collections.defaultdict(lambda: collections.defaultdict(list))
# bms_data[cid][byte_idx] = [(t, val), ...]

for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t   = frame.timestamp
    aid = frame.arbitration_id
    d   = frame.data

    if aid == 0x050 and len(d) >= 2:
        ccl_ts.append((t, (d[1] & 0x03) << 8 | d[0]))

    if aid in BMS_IDS and T_SCAN_START <= t <= T_SCAN_END:
        for bi, bv in enumerate(d):
            bms_data[aid][bi].append((t, bv))

print(f"  CCL frames: {len(ccl_ts)}  BMS IDs in window: {sorted(bms_data.keys())}")

# ---------------------------------------------------------------------------
# 1. CCL 1s-bucket table (t=310-390s)
# ---------------------------------------------------------------------------
print("\n--- CCL raw values (1s buckets, t=310-390s) ---")
print(f"  {'t(s)':>6}  {'CCL_raw':>7}")
ccl_in_range = [(t, v) for t, v in ccl_ts if 310 <= t <= 390]
bucket = {}
for t, v in ccl_in_range:
    b = int(t)
    if b not in bucket:
        bucket[b] = []
    bucket[b].append(v)
for b in sorted(bucket):
    vals = bucket[b]
    med  = sorted(vals)[len(vals)//2]
    print(f"  {b:>6}  {med:>7}")

# ---------------------------------------------------------------------------
# 2. Detect inflection times (first sustained crossing of each threshold)
# ---------------------------------------------------------------------------
def find_first_sustained(ccl_ts, threshold, hold_sec):
    """Return the first time CCL stays below threshold continuously for hold_sec."""
    below_since = None
    for i, (t, v) in enumerate(ccl_ts):
        if v < threshold:
            if below_since is None:
                below_since = t
            elif t - below_since >= hold_sec:
                return below_since
        else:
            below_since = None
    return None

T_STEP1 = find_first_sustained(ccl_ts, STEP1_THRESH, STEP_HOLD)
T_STEP2 = find_first_sustained(ccl_ts, STEP2_THRESH, STEP_HOLD)
print(f"\nInflection times:")
print(f"  Step1 (CCL < {STEP1_THRESH}, hold {STEP_HOLD}s): t={T_STEP1:.1f}s" if T_STEP1 else
      f"  Step1: not detected")
print(f"  Step2 (CCL < {STEP2_THRESH}, hold {STEP_HOLD}s): t={T_STEP2:.1f}s" if T_STEP2 else
      f"  Step2: not detected")

inflection_times = [t for t in [T_STEP1, T_STEP2] if t is not None]

# ---------------------------------------------------------------------------
# 3. Per-bit transition scan
# ---------------------------------------------------------------------------
# For each (cid, byte, bit): find all transition timestamps
# Score = sum over inflections of 1/(1 + min_dt_to_this_inflection) for min_dt < SCORE_WINDOW

candidates = []

for cid in sorted(bms_data.keys()):
    for bi in sorted(bms_data[cid].keys()):
        ts_vals = bms_data[cid][bi]
        if len(ts_vals) < 4:
            continue
        # Extract per-bit transition times
        for bit in range(8):
            mask = 1 << bit
            transitions = []   # (t, 0->1 or 1->0)
            prev_state = (ts_vals[0][1] >> bit) & 1
            for t, v in ts_vals[1:]:
                state = (v >> bit) & 1
                if state != prev_state:
                    transitions.append((t, prev_state, state))
                    prev_state = state
            if not transitions:
                continue

            t_trans = [t for t, _, _ in transitions]

            # Score vs each inflection
            score = 0.0
            match_info = []
            for t_inf in inflection_times:
                dts = [abs(t - t_inf) for t in t_trans]
                min_dt = min(dts)
                if min_dt < SCORE_WINDOW:
                    score += 1.0 / (1.0 + min_dt)
                    closest_t = t_trans[dts.index(min_dt)]
                    match_info.append((t_inf, closest_t, min_dt))

            if score > 0:
                n_trans = len(transitions)
                # Also track if bit is stable before/after (fewer transitions = better)
                candidates.append((score, n_trans, cid, bi, bit, transitions, match_info))

candidates.sort(key=lambda x: (-x[0], x[1]))

print(f"\n--- Bit transition candidates (within {SCORE_WINDOW}s of inflections) ---")
print(f"  {'ID':>8} {'B':>2} {'bit':>3}  {'score':>6}  {'n_trans':>7}  match details")
for score, n_trans, cid, bi, bit, transitions, match_info in candidates[:40]:
    detail = "; ".join(
        f"inf@{ti:.1f}s bit@{tb:.1f}s dt={dt:.1f}s"
        for ti, tb, dt in match_info
    )
    print(f"  {cid:#08x}  {bi:>2}  {bit:>3}  {score:>6.3f}  {n_trans:>7}  [{detail}]")

# ---------------------------------------------------------------------------
# 4. Plot: CCL + top bit candidates
# ---------------------------------------------------------------------------
print("\nPlotting ...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Pick top N candidates with n_trans <= 8 (prefer clean bit signals)
TOP_N = 6
plot_cands = [c for c in candidates if c[1] <= 8][:TOP_N]
# fallback if few clean ones
if len(plot_cands) < 3:
    plot_cands = candidates[:TOP_N]

n_panels = 1 + len(plot_cands)
fig, axes = plt.subplots(n_panels, 1,
                         figsize=(14, 3 + 2 * n_panels),
                         sharex=True)
if n_panels == 1:
    axes = [axes]

T_PLOT_START = max(300.0, (min(inflection_times) - 20.0)) if inflection_times else 300.0
T_PLOT_END   = 400.0

def shade_inf(ax):
    for t_inf in inflection_times:
        ax.axvline(t_inf, color='orangered', lw=1.2, ls='--', alpha=0.7,
                   label=f'Step t={t_inf:.1f}s')

# Panel 0: CCL
ax0 = axes[0]
ccl_plot = [(t, v) for t, v in ccl_ts if T_PLOT_START <= t <= T_PLOT_END]
if ccl_plot:
    tc, vc = zip(*ccl_plot)
    ax0.plot(tc, vc, color='purple', lw=1.0)
shade_inf(ax0)
ax0.axhline(STEP1_THRESH, color='gray', lw=0.7, ls=':', alpha=0.6, label=f'Thr={STEP1_THRESH}')
ax0.axhline(STEP2_THRESH, color='silver', lw=0.7, ls=':', alpha=0.6, label=f'Thr={STEP2_THRESH}')
ax0.set_ylabel('CCL raw')
ax0.set_title('0x050 CCL (raw) -- two-step drop')
ax0.legend(loc='lower left', fontsize=7, ncol=3)

# Panels 1+: per-bit step traces
COLORS = ['steelblue', 'darkorange', 'forestgreen', 'crimson', 'mediumpurple', 'saddlebrown']
for i, (score, n_trans, cid, bi, bit, transitions, match_info) in enumerate(plot_cands):
    ax = axes[i + 1]
    # Reconstruct step trace
    all_pts = bms_data[cid][bi]
    pts_in_range = [(t, (v >> bit) & 1) for t, v in all_pts if T_PLOT_START <= t <= T_PLOT_END]
    if pts_in_range:
        tt, vv = zip(*pts_in_range)
        ax.step(tt, vv, where='post', color=COLORS[i % len(COLORS)], lw=1.2)
    shade_inf(ax)
    ax.set_ylabel(f'Bit {bit}')
    ax.set_ylim(-0.1, 1.1)
    ax.set_yticks([0, 1])
    ax.set_title(f'{cid:#06x} B{bi} bit{bit}  (score={score:.3f}, n_trans={n_trans})', fontsize=9)

axes[-1].set_xlabel('Time (s)')
axes[-1].set_xlim(T_PLOT_START, T_PLOT_END)

fig.suptitle('CCL step-change inflection alignment -- BMS bit candidates\n'
             'Dashed orange lines = detected inflection times',
             fontsize=10)
plt.tight_layout()
plt.savefig(OUTPUT_PNG, dpi=130, bbox_inches='tight')
print(f"Saved: {OUTPUT_PNG}")
