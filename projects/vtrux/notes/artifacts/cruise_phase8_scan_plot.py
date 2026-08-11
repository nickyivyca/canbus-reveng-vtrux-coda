"""
cruise_phase8_scan_plot.py  --  Phase 8 cruise command search

Two searches over the 600-1200s window on the PT bus:

  Search A  (setpoint candidates)
    Signal is near-constant within each stable period and steps AT the
    button-event boundaries, nowhere else.
    Stable periods:
      s0  t=600-705   pre-cruise
      s1  t=707-1089  cruise period 1 (after decrement 1, before decrement 2)
      s2  t=1090-1103 cruise period 2 (after decrement 2, before exit cluster)
      s3  t=1110-1200 post-cancel
    Score_A = max_step_between_adjacent_periods / (max_within_sd + 0.1)
    Ranked by Score_A descending; shown if sd_max < threshold.

  Search B  (cruise-specific torque command)
    High |r| vs traction torque feedback ONLY during cruise active window.
    Manual windows: s0 + s3 combined.
    Cruise window:  t=707-1107
    Score_B = |r_cruise| - |r_manual|
    Filter: |r_cruise| >= 0.5, Score_B >= 0.3

Encodings: uint8, LE uint16, BE uint16.
Skip: 0x639.
Reference: 0x5A2 B4-B5 LE (traction motor torque feedback), PT Bus 2.

Outputs:
  cruise_phase8_scan.txt
  cruise_phase8_setpoint_plot.png   (Search A top candidates, t=600-1200s)
  cruise_phase8_torque_plot.png     (Search B top candidates, t=600-1200s)
"""

import sys, os, math, bisect
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

LOG    = 'projects/vtrux/logs/vtruxevapdrivelog4.log'
PT_BUS = 2
TORQ_ID    = 0x5A2
TORQ_B_LO  = 4   # B4-B5 LE = traction torque feedback
SKIP_IDS   = {0x639}

OUT_TXT  = 'projects/vtrux/notes/artifacts/cruise_phase8_scan.txt'
OUT_APNG = 'projects/vtrux/notes/artifacts/cruise_phase8_setpoint_plot.png'
OUT_BPNG = 'projects/vtrux/notes/artifacts/cruise_phase8_torque_plot.png'

TOP_N     = 10
MIN_PAIRS = 30

# Cruise button events (from Phase 7 burst detection)
# (start_t, end_t, tier)
EVENTS = [
    (705.68, 705.84, 5),    # engagement
    (706.18, 706.29, 3),    # decrement #1
    (1089.22, 1089.70, 3),  # decrement #2
    (1103.68, 1104.88, 3),  # decrement #3
    (1106.71, 1107.08, 3),  # decrement #4
    (1107.76, 1107.79, 5),  # cancel
]

# Stable periods for Search A
STABLE = {
    's0': (600,  705),
    's1': (707,  1089),
    's2': (1090, 1103),
    's3': (1110, 1200),
}
STABLE_ORDER = ['s0', 's1', 's2', 's3']

# Cruise window for Search B torque correlation
CRUISE_WIN = (707, 1107)
MANUAL_WINS = [STABLE['s0'], STABLE['s3']]   # combined for manual r

PARSE_LO = 580.0
PARSE_HI = 1220.0

# -------------------------------------------------------------------
# Parse PT bus frames in window
# -------------------------------------------------------------------
print("Parsing frames (PT bus, t=580-1220s only)...")
from canre.parsers import parse_file

# Store raw frames: {(aid, dlc): [(t, data_bytes)]}
raw_frames = defaultdict(list)
torq_ts, torq_vs = [], []

frame_count = 0
total = 0
for frame in parse_file(LOG):
    total += 1
    if frame.bus != PT_BUS:
        continue
    t = frame.timestamp
    if t < PARSE_LO or t > PARSE_HI:
        continue
    aid = frame.arbitration_id
    data = bytes(frame.data)
    dlc  = len(data)
    raw_frames[(aid, dlc)].append((t, data))
    if aid == TORQ_ID and dlc >= 6:
        tv = ((data[5] << 8) | data[4]) - 32768
        torq_ts.append(t)
        torq_vs.append(tv)
    frame_count += 1
    if total % 1000000 == 0:
        print(f"  {total:,} total frames / {frame_count:,} stored...")

print(f"Total log frames: {total:,}")
print(f"PT bus frames stored (580-1220s): {frame_count:,}")
print(f"Torque reference samples: {len(torq_ts)}")
print(f"Unique (ID, DLC) pairs: {len(raw_frames)}")


# -------------------------------------------------------------------
# Utility
# -------------------------------------------------------------------
def pearson_r(xs, ys):
    n = len(xs)
    if n < MIN_PAIRS:
        return None
    mx = sum(xs) / n; my = sum(ys) / n
    cov = sum((a-mx)*(b-my) for a,b in zip(xs,ys)) / n
    sx  = math.sqrt(sum((x-mx)**2 for x in xs) / n)
    sy  = math.sqrt(sum((y-my)**2 for y in ys) / n)
    if sx < 1e-9 or sy < 1e-9:
        return None
    return cov / (sx * sy)

def mean_sd(vals):
    n = len(vals)
    if n == 0:
        return float('nan'), float('nan')
    m = sum(vals) / n
    if n == 1:
        return m, 0.0
    sd = math.sqrt(sum((v-m)**2 for v in vals) / n)
    return m, sd

def nearest_torq(t, tol=0.06):
    idx = bisect.bisect_left(torq_ts, t)
    best_v, best_dt = None, tol+1
    for i in (idx-1, idx):
        if 0 <= i < len(torq_ts):
            dt = abs(torq_ts[i] - t)
            if dt < best_dt:
                best_dt, best_v = dt, torq_vs[i]
    return best_v if best_dt <= tol else None

def in_window(t, win):
    return win[0] <= t <= win[1]

def decode(data, b, enc):
    """Decode value from frame data bytes.  Returns None if out of range."""
    if enc == 'u8':
        if b >= len(data): return None
        return data[b]
    elif enc == 'le16':
        if b+1 >= len(data): return None
        return ((data[b+1] << 8) | data[b]) - 32768
    elif enc == 'be16':
        if b+1 >= len(data): return None
        return ((data[b] << 8) | data[b+1]) - 32768
    return None

def encodings_for_dlc(dlc):
    """Yield (enc, b) pairs to test."""
    for b in range(dlc):
        yield ('u8', b)
    for b in range(dlc - 1):
        yield ('le16', b)
        yield ('be16', b)


# -------------------------------------------------------------------
# Compute statistics for every candidate
# -------------------------------------------------------------------
print("\nComputing statistics...")

results = []

for (aid, dlc), frame_list in raw_frames.items():
    if aid in SKIP_IDS:
        continue

    for enc, b in encodings_for_dlc(dlc):
        # Per-stable-window value lists (Search A)
        stab_vals = {s: [] for s in STABLE_ORDER}
        # Per-window paired lists for torque correlation (Search B)
        cruise_sig, cruise_trq = [], []
        manual_sig, manual_trq = [], []

        for t, data in frame_list:
            v = decode(data, b, enc)
            if v is None:
                continue

            # Search A: stable window accumulation
            for sname, (t0, t1) in STABLE.items():
                if t0 <= t <= t1:
                    stab_vals[sname].append(v)
                    break

            # Search B: torque correlation
            tv = nearest_torq(t)
            if tv is not None:
                if CRUISE_WIN[0] <= t <= CRUISE_WIN[1]:
                    cruise_sig.append(v); cruise_trq.append(tv)
                elif any(w[0] <= t <= w[1] for w in MANUAL_WINS):
                    manual_sig.append(v); manual_trq.append(tv)

        # --- Search A scoring ---
        means, sds = {}, {}
        for sname in STABLE_ORDER:
            if stab_vals[sname]:
                m, sd = mean_sd(stab_vals[sname])
                means[sname] = m
                sds[sname] = sd

        # Require at least s0, s1, s2 to have data
        if not all(s in means for s in ('s0', 's1', 's2')):
            score_a = float('nan')
            max_sd = float('nan')
            max_step = float('nan')
        else:
            steps = []
            for sa, sb in [('s0','s1'), ('s1','s2'), ('s2','s3')]:
                if sa in means and sb in means:
                    steps.append(abs(means[sb] - means[sa]))
            max_step = max(steps) if steps else 0.0
            present_sds = [sds[s] for s in STABLE_ORDER if s in sds]
            max_sd = max(present_sds) if present_sds else float('nan')
            if not math.isnan(max_sd):
                score_a = max_step / (max_sd + 0.1)
            else:
                score_a = float('nan')

        # --- Search B scoring ---
        r_cruise = pearson_r(cruise_sig, cruise_trq)
        r_manual = pearson_r(manual_sig, manual_trq)
        if r_cruise is not None and r_manual is not None:
            score_b = abs(r_cruise) - abs(r_manual)
        elif r_cruise is not None:
            score_b = abs(r_cruise)
        else:
            score_b = float('nan')

        results.append({
            'id': aid, 'dlc': dlc, 'b': b, 'enc': enc,
            # Search A
            'score_a': score_a,
            'max_step': max_step,
            'max_sd': max_sd,
            'means': means,
            'sds': sds,
            # Search B
            'r_cruise': r_cruise if r_cruise is not None else float('nan'),
            'r_manual': r_manual if r_manual is not None else float('nan'),
            'score_b': score_b,
            'n_cruise': len(cruise_sig),
            'n_manual': len(manual_sig),
        })

print(f"Total candidates: {len(results)}")


# -------------------------------------------------------------------
# Rank candidates
# -------------------------------------------------------------------
def valid(v):
    return not math.isnan(v)

# Search A: sort by score_a, require step > 0.5 and max_sd < 20 (u8) or < 1000 (16-bit)
def a_threshold(row):
    if row['enc'] == 'u8':
        return row['max_sd'] < 15 and row['max_step'] > 0.5
    else:
        return row['max_sd'] < 600 and row['max_step'] > 5

top_a = sorted(
    [r for r in results if valid(r['score_a']) and a_threshold(r)],
    key=lambda x: x['score_a'], reverse=True
)

# Search B: sort by score_b, require |r_cruise| >= 0.5 and score_b >= 0.3
top_b = sorted(
    [r for r in results
     if valid(r['score_b'])
     and not math.isnan(r['r_cruise'])
     and abs(r['r_cruise']) >= 0.5
     and r['score_b'] >= 0.3],
    key=lambda x: x['score_b'], reverse=True
)

print(f"Search A candidates (step/sd filter): {len(top_a)}")
print(f"Search B candidates (|r_cruise|>=0.5, score>=0.3): {len(top_b)}")


# -------------------------------------------------------------------
# Write text output
# -------------------------------------------------------------------
def fv(v, w=8, d=3):
    return f"{v:{w}.{d}f}" if valid(v) else f"{'--':>{w}}"

with open(OUT_TXT, 'w', encoding='utf-8') as f:
    f.write("cruise_phase8_scan.py  --  Phase 8 cruise command search\n")
    f.write("Log: vtruxevapdrivelog4.log  Bus: 2 (PT)  Window: t=600-1200s\n")
    f.write("Encodings: uint8, LE uint16, BE uint16  |  Skip: 0x639\n")
    f.write("Stable periods: s0=600-705, s1=707-1089, s2=1090-1103, s3=1110-1200\n")
    f.write("Cruise window (Search B): t=707-1107  Manual: s0+s3\n\n")

    f.write("=== SEARCH A: SETPOINT CANDIDATES ===\n")
    f.write("Score_A = max_adjacent_step / (max_within_sd + 0.1)\n")
    f.write("Setpoint: flat within each period, steps at event boundaries.\n\n")
    hdr = (f"{'ID':10s} {'enc':5s} {'B':3s} {'score_A':>8s} {'max_step':>9s} {'max_sd':>8s} "
           f"{'m_s0':>8s} {'m_s1':>8s} {'m_s2':>8s} {'m_s3':>8s} "
           f"{'sd_s0':>7s} {'sd_s1':>7s} {'sd_s2':>7s}\n")
    f.write(hdr + '-'*96 + '\n')
    for row in top_a[:TOP_N*2]:
        m = row['means']; sd = row['sds']
        f.write(
            f"0x{row['id']:06X}   {row['enc']:5s} {row['b']:3d} "
            f"{fv(row['score_a'],8,2)} {fv(row['max_step'],9,2)} {fv(row['max_sd'],8,2)} "
            f"{fv(m.get('s0',float('nan')),8,2)} {fv(m.get('s1',float('nan')),8,2)} "
            f"{fv(m.get('s2',float('nan')),8,2)} {fv(m.get('s3',float('nan')),8,2)} "
            f"{fv(sd.get('s0',float('nan')),7,2)} {fv(sd.get('s1',float('nan')),7,2)} "
            f"{fv(sd.get('s2',float('nan')),7,2)}\n"
        )

    f.write("\n\n=== SEARCH B: CRUISE-SPECIFIC TORQUE COMMAND CANDIDATES ===\n")
    f.write("Score_B = |r_cruise| - |r_manual|  (high = correlates with torque ONLY during cruise)\n")
    f.write("Reference: 0x5A2 B4-B5 traction torque feedback.  Filter: |r_cruise|>=0.5, score>=0.3\n\n")
    hdr2 = (f"{'ID':10s} {'enc':5s} {'B':3s} {'score_B':>8s} {'r_cruise':>9s} {'r_manual':>9s} "
            f"{'n_crs':>6s} {'n_man':>6s}\n")
    f.write(hdr2 + '-'*68 + '\n')
    for row in top_b[:TOP_N*2]:
        f.write(
            f"0x{row['id']:06X}   {row['enc']:5s} {row['b']:3d} "
            f"{fv(row['score_b'],8,4)} {fv(row['r_cruise'],9,4)} {fv(row['r_manual'],9,4)} "
            f"{row['n_cruise']:6d} {row['n_manual']:6d}\n"
        )

print(f"Scan output -> {OUT_TXT}")

# Quick console preview
print("\n--- Search A top 10 ---")
print(f"{'ID':10s} {'enc':5s} {'B':3s} {'score_A':>8s} {'step':>7s} {'max_sd':>7s} "
      f"{'m_s0':>7s} {'m_s1':>7s} {'m_s2':>7s}")
print('-'*68)
for row in top_a[:10]:
    m = row['means']
    print(f"0x{row['id']:06X}   {row['enc']:5s} {row['b']:3d} "
          f"{row['score_a']:8.2f} {row['max_step']:7.2f} {row['max_sd']:7.2f} "
          f"{m.get('s0',float('nan')):7.2f} {m.get('s1',float('nan')):7.2f} "
          f"{m.get('s2',float('nan')):7.2f}")

print("\n--- Search B top 10 ---")
print(f"{'ID':10s} {'enc':5s} {'B':3s} {'score_B':>8s} {'r_crs':>7s} {'r_man':>7s}")
print('-'*52)
for row in top_b[:10]:
    print(f"0x{row['id']:06X}   {row['enc']:5s} {row['b']:3d} "
          f"{row['score_b']:8.4f} {row['r_cruise']:7.4f} {row['r_manual']:7.4f}")


# -------------------------------------------------------------------
# Collect timeseries for top candidates (for plotting)
# -------------------------------------------------------------------
print("\nCollecting plot timeseries...")

PLOT_WIN = (595, 1210)

def collect_ts(aid, dlc, b, enc):
    """Return (ts, vs) for this signal in the plot window."""
    ts_out, vs_out = [], []
    for t, data in raw_frames.get((aid, dlc), []):
        if PLOT_WIN[0] <= t <= PLOT_WIN[1]:
            v = decode(data, b, enc)
            if v is not None:
                ts_out.append(t)
                vs_out.append(v)
    return ts_out, vs_out

# Torque reference timeseries (already collected; filter to plot window)
torq_plot_t = [t for t in torq_ts if PLOT_WIN[0] <= t <= PLOT_WIN[1]]
torq_plot_v = [torq_vs[i] for i, t in enumerate(torq_ts) if PLOT_WIN[0] <= t <= PLOT_WIN[1]]


# -------------------------------------------------------------------
# Plot helpers
# -------------------------------------------------------------------
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

C_T3 = '#E87722'   # orange -- tier 3 (setpoint decrement)
C_T5 = '#CC2222'   # red    -- tier 5 (engage/cancel)
C_S0 = '#D0E8FF'
C_S1 = '#D0FFD8'
C_S2 = '#FFFAD0'
C_S3 = '#FFE8E8'
STABLE_COLORS = {'s0': C_S0, 's1': C_S1, 's2': C_S2, 's3': C_S3}

def draw_stable_shading(ax):
    for sname, (t0, t1) in STABLE.items():
        ax.axvspan(t0, t1, color=STABLE_COLORS[sname], alpha=0.4, linewidth=0)

def draw_events(ax):
    for (t0, t1, tier) in EVENTS:
        c = C_T5 if tier == 5 else C_T3
        ax.axvspan(t0, max(t1, t0+0.1), color=c, alpha=0.5, linewidth=0)
        ax.axvline(t0, color=c, linewidth=1.2, linestyle='--', alpha=0.85)

def draw_stable_means(ax, means, color='navy'):
    for sname, (t0, t1) in STABLE.items():
        if sname in means:
            ax.hlines(means[sname], t0, t1, color=color, linewidth=2, linestyle='-', alpha=0.7)


# -------------------------------------------------------------------
# Search A plot
# -------------------------------------------------------------------
print("Building Search A (setpoint) plot...")

n_a = min(len(top_a), TOP_N)
if n_a == 0:
    print("  No Search A candidates -- skipping plot.")
else:
    fig, axes = plt.subplots(n_a, 1, figsize=(18, 2.5*n_a), sharex=True)
    if n_a == 1:
        axes = [axes]
    fig.suptitle('Phase 8 Search A: Setpoint Candidates (t=600-1200s)', fontsize=12)

    for i, row in enumerate(top_a[:n_a]):
        ax = axes[i]
        ts, vs = collect_ts(row['id'], row['dlc'], row['b'], row['enc'])
        draw_stable_shading(ax)
        draw_events(ax)
        if ts:
            ax.plot(ts, vs, color='steelblue', linewidth=0.7)
        draw_stable_means(ax, row['means'])
        label = (f"0x{row['id']:06X} {row['enc']} B{row['b']}  "
                 f"score={row['score_a']:.1f}  step={row['max_step']:.2f}  "
                 f"max_sd={row['max_sd']:.2f}  "
                 f"means: s0={row['means'].get('s0',float('nan')):.1f} "
                 f"s1={row['means'].get('s1',float('nan')):.1f} "
                 f"s2={row['means'].get('s2',float('nan')):.1f}")
        ax.set_ylabel(f"0x{row['id']:06X}\n{row['enc']} B{row['b']}", fontsize=8)
        ax.set_title(label, fontsize=8, loc='left')
        ax.grid(True, alpha=0.2)
        ax.set_xlim(600, 1200)

    axes[-1].set_xlabel('Time (s)', fontsize=10)

    # Shared legend
    patches = [
        mpatches.Patch(color=C_S0, alpha=0.5, label='s0 pre-cruise'),
        mpatches.Patch(color=C_S1, alpha=0.5, label='s1 cruise stable 1'),
        mpatches.Patch(color=C_S2, alpha=0.5, label='s2 cruise stable 2'),
        mpatches.Patch(color=C_S3, alpha=0.5, label='s3 post-cancel'),
        mpatches.Patch(color=C_T3, alpha=0.6, label='tier 3 (Speed-)'),
        mpatches.Patch(color=C_T5, alpha=0.6, label='tier 5 (engage/cancel)'),
    ]
    fig.legend(handles=patches, loc='lower center', ncol=6, fontsize=8,
               bbox_to_anchor=(0.5, 0.005))

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    plt.savefig(OUT_APNG, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved -> {OUT_APNG}")


# -------------------------------------------------------------------
# Search B plot
# -------------------------------------------------------------------
print("Building Search B (torque command) plot...")

n_b = min(len(top_b), TOP_N)
if n_b == 0:
    print("  No Search B candidates -- skipping plot.")
else:
    n_panels = n_b + 1  # +1 for torque reference on top
    fig, axes = plt.subplots(n_panels, 1, figsize=(18, 2.5*n_panels), sharex=True)
    fig.suptitle('Phase 8 Search B: Cruise Torque Command Candidates (t=600-1200s)', fontsize=12)

    # Panel 0: torque reference
    ax = axes[0]
    draw_stable_shading(ax)
    draw_events(ax)
    ax.plot(torq_plot_t, torq_plot_v, color='black', linewidth=0.7)
    ax.set_ylabel('Torque fdbk\n0x5A2 B4-B5', fontsize=8)
    ax.set_title('Reference: traction motor torque feedback (0x5A2 B4-B5 LE)', fontsize=8, loc='left')
    ax.grid(True, alpha=0.2)
    ax.set_xlim(600, 1200)
    ax.axvspan(CRUISE_WIN[0], CRUISE_WIN[1], color='#E0F0FF', alpha=0.3, linewidth=0)

    for i, row in enumerate(top_b[:n_b]):
        ax = axes[i+1]
        ts, vs = collect_ts(row['id'], row['dlc'], row['b'], row['enc'])
        draw_stable_shading(ax)
        ax.axvspan(CRUISE_WIN[0], CRUISE_WIN[1], color='#E0F0FF', alpha=0.25, linewidth=0)
        draw_events(ax)
        if ts:
            ax.plot(ts, vs, color='firebrick', linewidth=0.7)
        label = (f"0x{row['id']:06X} {row['enc']} B{row['b']}  "
                 f"score={row['score_b']:.3f}  r_cruise={row['r_cruise']:.3f}  "
                 f"r_manual={row['r_manual']:.3f}  n_crs={row['n_cruise']}  n_man={row['n_manual']}")
        ax.set_ylabel(f"0x{row['id']:06X}\n{row['enc']} B{row['b']}", fontsize=8)
        ax.set_title(label, fontsize=8, loc='left')
        ax.grid(True, alpha=0.2)
        ax.set_xlim(600, 1200)

    axes[-1].set_xlabel('Time (s)', fontsize=10)

    patches = [
        mpatches.Patch(color='#E0F0FF', alpha=0.5, label='cruise active (t=707-1107)'),
        mpatches.Patch(color=C_T3, alpha=0.6, label='tier 3 (Speed-)'),
        mpatches.Patch(color=C_T5, alpha=0.6, label='tier 5 (engage/cancel)'),
    ]
    fig.legend(handles=patches, loc='lower center', ncol=3, fontsize=8,
               bbox_to_anchor=(0.5, 0.005))

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    plt.savefig(OUT_BPNG, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved -> {OUT_BPNG}")

print("\nDone.")
