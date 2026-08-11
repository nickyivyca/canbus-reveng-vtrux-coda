"""
scan_0x05x_brake.py

For every byte in the 0x05x cluster (0x050-0x054), compute:
  r_full    -- Pearson r vs traction torque feedback (all times)
  r_pos     -- r in positive-torque region (traction_fb > +200)
  r_neg     -- r in negative/regen region  (traction_fb < -200)
  brake_chg -- median(post-brake, 5s) - median(pre-brake, 5s)  at t=1108

Also prints full byte-statistics for 0x052 and 0x054 (unknown messages).

Reference:
  traction_fb = 0x5A2 B4-B5 LE, centered 32768
  brake event at t=1108 (marker: brake applied)

Output: scan_0x05x_brake.txt
"""

import sys, os, math, bisect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG    = 'projects/vtrux/logs/vtruxevapdrivelog4.log'
PT_BUS = 2
OUTPUT = 'projects/vtrux/notes/artifacts/scan_0x05x_brake.txt'
BRAKE_T = 1108.0

print("Parsing...")
frames_05x = {}   # aid -> [(t, bytes), ...]
tract_fb   = []   # (t, val)

for frame in parse_file(LOG):
    if frame.bus != PT_BUS: continue
    aid = frame.arbitration_id
    if 0x050 <= aid <= 0x05F:
        frames_05x.setdefault(aid, []).append((frame.timestamp, frame.data))
    elif aid == 0x5A2 and len(frame.data) >= 6:
        tract_fb.append((frame.timestamp, ((frame.data[5] << 8) | frame.data[4]) - 32768))

tract_fb.sort()
tf_t = [x[0] for x in tract_fb]
tf_v = [x[1] for x in tract_fb]
print(f"IDs found: {[hex(a) for a in sorted(frames_05x)]}")
print(f"Traction samples: {len(tract_fb)}")

def nearest(st, sv, t, tol=0.15):
    idx = bisect.bisect_left(st, t)
    bv = None; bd = tol + 1
    for i in (idx-1, idx):
        if 0 <= i < len(st):
            dt = abs(st[i] - t)
            if dt < bd: bd = dt; bv = sv[i]
    return bv if bd <= tol else None

def pearson(xs, ys, min_n=10):
    n = len(xs)
    if n < min_n: return float('nan')
    mx = sum(xs)/n; my = sum(ys)/n
    cov = sum((a-mx)*(b-my) for a,b in zip(xs,ys))/n
    sx = math.sqrt(sum((x-mx)**2 for x in xs)/n)
    sy = math.sqrt(sum((y-my)**2 for y in ys)/n)
    return cov/(sx*sy) if sx > 1e-9 and sy > 1e-9 else float('nan')

POS_THRESH  =  200
NEG_THRESH  = -200
BRAKE_WIN   =   5.0   # seconds each side

lines = []
def p(s=""):
    print(s)
    lines.append(s)

p("=" * 72)
p("0x05x cluster -- byte correlation vs traction torque feedback")
p(f"  Traction pos region: > {POS_THRESH}, neg region: < {NEG_THRESH}")
p(f"  Brake event at t={BRAKE_T}  (window +/-{BRAKE_WIN}s)")
p("=" * 72)

for aid in sorted(frames_05x):
    frames = frames_05x[aid]
    max_dlc = max(len(d) for _, d in frames)
    freq = len(frames) / (frames[-1][0] - frames[0][0]) if len(frames) > 1 else 0

    p(f"\n--- 0x{aid:03X}  ({len(frames)} frames, dlc={max_dlc}, {freq:.1f} Hz) ---")

    # Full byte stats table
    p(f"  {'B':>2s}  {'Min':>4s}  {'Max':>4s}  {'Uniq':>5s}  {'r_full':>8s}  {'r_pos':>7s}  {'r_neg':>7s}  {'brake_chg':>10s}")
    p("  " + "-" * 65)

    for b in range(max_dlc):
        vals_t = [(t, d[b]) for t, d in frames if len(d) > b]
        if not vals_t: continue
        raw_v = [v for _, v in vals_t]
        v_min, v_max = min(raw_v), max(raw_v)
        n_uniq = len(set(raw_v))

        # Pair with traction feedback
        matched = [(v, nearest(tf_t, tf_v, t)) for t, v in vals_t]
        pairs_all  = [(bv, g) for bv, g in matched if g is not None]
        pairs_pos  = [(bv, g) for bv, g in pairs_all if g > POS_THRESH]
        pairs_neg  = [(bv, g) for bv, g in pairs_all if g < NEG_THRESH]

        r_full = pearson([p[0] for p in pairs_all], [p[1] for p in pairs_all])
        r_pos  = pearson([p[0] for p in pairs_pos], [p[1] for p in pairs_pos])
        r_neg  = pearson([p[0] for p in pairs_neg], [p[1] for p in pairs_neg])

        # Brake event delta
        pre_b  = [v for t, v in vals_t if BRAKE_T - BRAKE_WIN <= t < BRAKE_T]
        post_b = [v for t, v in vals_t if BRAKE_T <= t <= BRAKE_T + BRAKE_WIN]
        if pre_b and post_b:
            pre_med  = sorted(pre_b)[len(pre_b)  // 2]
            post_med = sorted(post_b)[len(post_b) // 2]
            brake_chg = post_med - pre_med
        else:
            brake_chg = 0

        # Mark interesting rows
        flag = ""
        if n_uniq <= 1:
            flag = "  [const]"
        elif abs(r_neg) > 0.4 or abs(r_full) > 0.5 or brake_chg != 0:
            flag = "  <<<" if (abs(r_neg) > 0.5 or abs(brake_chg) > 5) else "  <--"

        r_full_s = f"{r_full:+8.4f}" if not math.isnan(r_full) else "     nan"
        r_pos_s  = f"{r_pos:+7.4f}"  if not math.isnan(r_pos)  else "    nan"
        r_neg_s  = f"{r_neg:+7.4f}"  if not math.isnan(r_neg)  else "    nan"

        p(f"  {b:2d}  {v_min:4d}  {v_max:4d}  {n_uniq:5d}  {r_full_s}  {r_pos_s}  {r_neg_s}  {brake_chg:+10.1f}{flag}")

# -----------------------------------------------------------------------
# Detailed breakdown of unknown message bytes: 0x052, 0x054
# -----------------------------------------------------------------------
for aid in (0x052, 0x054):
    if aid not in frames_05x: continue
    frames = frames_05x[aid]
    max_dlc = max(len(d) for _, d in frames)

    p(f"\n{'='*40}")
    p(f"Detail: 0x{aid:03X} unique value sets per byte")
    p(f"{'='*40}")
    for b in range(max_dlc):
        raw_v = sorted(set(d[b] for _, d in frames if len(d) > b))
        p(f"  B{b}: {raw_v}  ({len(raw_v)} unique)")

    # Value transition detail near brake event
    p(f"\n  Values near brake (t={BRAKE_T} +/-10s):")
    for t, d in frames:
        if BRAKE_T - 10 <= t <= BRAKE_T + 10:
            p(f"    t={t:9.3f}  {list(d[:max_dlc])}")

# -----------------------------------------------------------------------
# What changes AT brake event across all 0x05x messages (t=1108 +/-2s)
# -----------------------------------------------------------------------
p(f"\n{'='*72}")
p(f"Byte transitions in 0x05x window [t={BRAKE_T-2:.0f}-{BRAKE_T+2:.0f}]")
p("="*72)
for aid in sorted(frames_05x):
    frames = frames_05x[aid]
    max_dlc = max(len(d) for _, d in frames)
    window = [(t, d) for t, d in frames if BRAKE_T - 2 <= t <= BRAKE_T + 2]
    if not window: continue
    prev = None
    for t, d in window:
        if prev is not None:
            diffs = [b for b in range(min(len(d), len(prev), max_dlc)) if d[b] != prev[b]]
            if diffs:
                p(f"  0x{aid:03X} t={t:.3f}: bytes {diffs} changed -> {[d[b] for b in diffs]}")
        prev = d

with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f"\nSaved: {OUTPUT}")
