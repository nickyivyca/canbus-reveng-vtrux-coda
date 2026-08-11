"""
scan_ccl_bits2.py

Focused search: find BMS bits with very few transitions (n_trans <= 6) that
change state near the two CCL inflection points.

Also: for each BMS byte, show the raw byte values at the two step times.

CCL step times (from scan_ccl_bits.py):
  Step 1: t=350.8s (CCL drops from ~305 to ~187)
  Step 2: t=357.8s (CCL drops from ~187 to ~42)
  Recovery: t=362-363s (CCL returns to ~265-306)

Window: t=300-410s on PT bus
"""

import os, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                   '..', '..', 'logs',
                                   'vtruxcurrentlimitingtest.log'))

BMS_IDS = set([
    0x370, 0x371, 0x372, 0x373, 0x374, 0x375,
    0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460,
    0x506, 0x507,
])

T_SCAN_START = 280.0
T_SCAN_END   = 420.0

T_STEP1 = 350.8   # CCL step 1 onset (305->187)
T_STEP2 = 357.8   # CCL step 2 onset (187->42)
T_RECOV = 362.0   # CCL recovery

MAX_TRANS = 6     # max transitions for a "digital" bit
NEAR_WIN  = 8.0   # transition must be within this many seconds of an inflection

# ---------------------------------------------------------------------------
print("Detecting PT bus ...")
bus_051 = {}
for frame in parse_file(LOG):
    if frame.arbitration_id == 0x051:
        bus_051[frame.bus] = bus_051.get(frame.bus, 0) + 1
    if sum(bus_051.values()) > 200:
        break
PT_BUS = max(bus_051, key=bus_051.get)
print(f"PT bus = {PT_BUS}")

print("Parsing ...")
bms_data = collections.defaultdict(lambda: collections.defaultdict(list))

for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t   = frame.timestamp
    aid = frame.arbitration_id
    if aid not in BMS_IDS:
        continue
    if not (T_SCAN_START <= t <= T_SCAN_END):
        continue
    for bi, bv in enumerate(frame.data):
        bms_data[aid][bi].append((t, bv))

print(f"  IDs found: {[hex(x) for x in sorted(bms_data.keys())]}")

# ---------------------------------------------------------------------------
# Section A: byte-level raw value table at key moments
# ---------------------------------------------------------------------------
inflection_ts = {
    'pre_step': 345.0,
    'step1':    351.5,   # just after step 1
    'step2':    359.0,   # just after step 2 (near zero)
    'recovery': 365.0,   # recovery
    'baseline': 340.0,
}

def nearest_val(ts_vals, t_target, tol=2.0):
    best = None; bd = tol + 1
    for t, v in ts_vals:
        dt = abs(t - t_target)
        if dt < bd:
            bd = dt; best = v
    return best

print("\n--- Section A: Byte values at key moments (nearest frame within 2s) ---")
print(f"  {'ID':>8} {'B':>2}  {'baseline':>9} {'pre_step':>9} {'step1':>9} {'step2':>9} {'recovery':>9}  {'uniq':>5}")
for cid in sorted(bms_data.keys()):
    for bi in sorted(bms_data[cid].keys()):
        ts_vals = bms_data[cid][bi]
        vals_at = {name: nearest_val(ts_vals, t) for name, t in inflection_ts.items()}
        # Only print if at least one of step1/step2 differs from baseline
        bl = vals_at['baseline']
        if bl is None:
            continue
        if vals_at['step1'] == bl and vals_at['step2'] == bl:
            continue
        all_vals = [v for _, v in ts_vals]
        uniq = len(set(all_vals))
        def fv(v): return f"{v:>9}" if v is not None else f"{'?':>9}"
        print(f"  {cid:#08x}  {bi:>2}  "
              f"{fv(vals_at['baseline'])} {fv(vals_at['pre_step'])} "
              f"{fv(vals_at['step1'])} {fv(vals_at['step2'])} "
              f"{fv(vals_at['recovery'])}  {uniq:>5}")

# ---------------------------------------------------------------------------
# Section B: Clean bit candidates (n_trans <= MAX_TRANS, near inflections)
# ---------------------------------------------------------------------------
inflection_times = [T_STEP1, T_STEP2]
recovery_time    = T_RECOV

print(f"\n--- Section B: Clean bit candidates (n_trans <= {MAX_TRANS}, within {NEAR_WIN}s of inflection) ---")
print(f"  {'ID':>8} {'B':>2} {'bit':>3}  {'n_trans':>7}  transitions")

clean = []
for cid in sorted(bms_data.keys()):
    for bi in sorted(bms_data[cid].keys()):
        ts_vals = bms_data[cid][bi]
        if len(ts_vals) < 4:
            continue
        for bit in range(8):
            prev_state = (ts_vals[0][1] >> bit) & 1
            transitions = []
            for t, v in ts_vals[1:]:
                state = (v >> bit) & 1
                if state != prev_state:
                    transitions.append((t, prev_state, state))
                    prev_state = state
            n = len(transitions)
            if n == 0 or n > MAX_TRANS:
                continue
            # Check if any transition is near an inflection
            t_trans = [t for t, _, _ in transitions]
            hits = any(
                any(abs(t - t_inf) <= NEAR_WIN for t_inf in inflection_times)
                for t in t_trans
            )
            if not hits:
                continue
            clean.append((n, cid, bi, bit, transitions))

clean.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

for n, cid, bi, bit, transitions in clean:
    trans_strs = [f"t={t:.2f}s {fr}->{to}" for t, fr, to in transitions]
    print(f"  {cid:#08x}  {bi:>2}  {bit:>3}  {n:>7}  " + ", ".join(trans_strs))

# ---------------------------------------------------------------------------
# Section C: Plot CCL + clean bit candidates
# ---------------------------------------------------------------------------
print("\nPlotting ...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUTPUT_PNG = os.path.abspath(os.path.join(os.path.dirname(__file__), 'plot_ccl_bits2.png'))

# Reload CCL
ccl_ts = []
for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    if frame.arbitration_id == 0x050 and len(frame.data) >= 2:
        d = frame.data
        ccl_ts.append((frame.timestamp, (d[1] & 0x03) << 8 | d[0]))

T_PLT_S = 338.0
T_PLT_E = 378.0

# Pick candidates for plot (prefer fewest transitions)
plot_cands = clean[:8]

n_panels = 1 + len(plot_cands)
fig, axes = plt.subplots(n_panels, 1,
                         figsize=(14, 3 + 1.8 * n_panels),
                         sharex=True)
if n_panels == 1:
    axes = [axes]

def shade(ax):
    ax.axvline(T_STEP1, color='orangered', lw=1.2, ls='--', alpha=0.7)
    ax.axvline(T_STEP2, color='red', lw=1.2, ls='-', alpha=0.7)
    ax.axvline(T_RECOV, color='steelblue', lw=1.0, ls=':', alpha=0.6)

# CCL panel
ax0 = axes[0]
ccl_plot = [(t, v) for t, v in ccl_ts if T_PLT_S <= t <= T_PLT_E]
if ccl_plot:
    tc, vc = zip(*ccl_plot)
    ax0.plot(tc, vc, color='purple', lw=1.2)
shade(ax0)
ax0.set_ylabel('CCL raw')
ax0.set_title(
    f'0x050 CCL -- Step1@{T_STEP1}s (orange dashed), Step2@{T_STEP2}s (red solid), '
    f'Recovery@{T_RECOV}s (blue dotted)')
ax0.legend(
    [plt.Line2D([0],[0],color='orangered',ls='--'),
     plt.Line2D([0],[0],color='red',ls='-'),
     plt.Line2D([0],[0],color='steelblue',ls=':')],
    ['Step1 (305->187)', 'Step2 (187->42)', 'Recovery'],
    loc='lower left', fontsize=7)

COLORS = ['steelblue', 'darkorange', 'forestgreen', 'crimson',
          'mediumpurple', 'saddlebrown', 'teal', 'gray']
for i, (n, cid, bi, bit, transitions) in enumerate(plot_cands):
    ax = axes[i + 1]
    ts_vals = bms_data[cid][bi]
    pts = [(t, (v >> bit) & 1) for t, v in ts_vals if T_PLT_S <= t <= T_PLT_E]
    if pts:
        tt, vv = zip(*pts)
        ax.step(tt, vv, where='post', color=COLORS[i % len(COLORS)], lw=1.5)
    shade(ax)
    ax.set_ylabel(f'Bit {bit}')
    ax.set_ylim(-0.15, 1.15)
    ax.set_yticks([0, 1])
    trans_lbl = ", ".join(f"{t:.1f}s:{fr}->{to}" for t, fr, to in transitions
                          if T_PLT_S <= t <= T_PLT_E)
    ax.set_title(f'{cid:#06x} B{bi} bit{bit}  n_trans={n}  [{trans_lbl}]', fontsize=9)

axes[-1].set_xlabel('Time (s)')
axes[-1].set_xlim(T_PLT_S, T_PLT_E)
fig.suptitle('CCL step alignment -- clean BMS bit candidates (n_trans <= 6)', fontsize=10)
plt.tight_layout()
plt.savefig(OUTPUT_PNG, dpi=130, bbox_inches='tight')
print(f"Saved: {OUTPUT_PNG}")
