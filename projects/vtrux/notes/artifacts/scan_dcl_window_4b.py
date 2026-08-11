"""
scan_dcl_window_4b.py  --  Step 4b: DCL/CCL scan with updated methodology

Addresses two known blind spots from Step 4:
  1. MSB-step artifact: multi-byte signals where the MSB steps by +-1 within
     the correlation window collapse full-log Pearson r to near zero.
  2. Monotone-acceleration spurious correlation: the ramp window (t=598-630s)
     has a single long power ramp that makes many unrelated bytes appear correlated.

Three passes:

Pass A -- Delta correlation (immune to MSB-step artifacts)
  Compute delta_byte = byte[i] - byte[i-1] and delta_power for each ID/byte.
  Pearson(delta_byte, delta_power) is unaffected by MSB step jumps because
  the step appears as a single large delta spike rather than a sustained level shift.
  Sub-windows:
    A1: t=598-680s (merge ramp + post-accel, DCL likely active, power varies)
    A2: t=503-580s (reference, no DCL, baseline)
  Cross-reference: flag candidates present in A1 but absent from A2.

Pass B -- Multi-window stable Pearson
  Run raw Pearson in 4 short windows (30-60s) where MSB steps are unlikely:
    W1=100-160s  W2=200-260s  W3=503-560s  W4=625-685s
  Candidates with |r| >= 0.50 in 2+ windows are consistently correlated with
  power across different drive conditions -- more reliable than single-window r.

Pass C -- J1939 extended ID inventory
  List all 0x18FFxxxx IDs seen in the full log with byte ranges, unique-value
  counts, and source address decoding. J1939 PGNs in 0xFFxx range commonly
  carry BMS current limit parameters.

Output: scan_dcl_window_4b.txt
"""

import sys, bisect
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
OUT = Path(__file__).parent / "scan_dcl_window_4b.txt"

I_SCALE = 0.04124    # A/count, from signal_scaling.py
V_SCALE = 0.015031   # V/count, from plot_drive_overview calibration

# ---------- windows ------------------------------------------------------------
WIN_A1 = (598.0, 680.0)    # delta window: DCL-active merge ramp + post-accel
WIN_A2 = (503.0, 580.0)    # delta window: pre-stop-sign reference (no DCL)
STABLE = [(100.0, 160.0), (200.0, 260.0), (503.0, 560.0), (625.0, 685.0)]

ALL_MIN = min(WIN_A2[0], WIN_A1[0], min(w[0] for w in STABLE))
ALL_MAX = max(WIN_A2[1], WIN_A1[1], max(w[1] for w in STABLE))

# ---------- helpers ------------------------------------------------------------
def pearson(xs, ys):
    n = len(xs)
    if n < 5: return float('nan')
    mx = sum(xs) / n; my = sum(ys) / n
    num = sum((x-mx)*(y-my) for x,y in zip(xs, ys))
    dx = sum((x-mx)**2 for x in xs)**0.5
    dy = sum((y-my)**2 for y in ys)**0.5
    if dx == 0 or dy == 0: return 0.0
    return num / (dx*dy)

def interp1(ts, vs, t_q):
    i = bisect.bisect_left(ts, t_q)
    if i == 0: return vs[0]
    if i >= len(ts): return vs[-1]
    return vs[i] if abs(ts[i]-t_q) < abs(ts[i-1]-t_q) else vs[i-1]

def bms_flag(aid):
    if 0x400 <= aid <= 0x507:      return '*'
    if 0x18FF0000 <= aid <= 0x18FFFFFF: return 'J'
    return ' '

lines = []
def p(s=''):
    print(s)
    lines.append(s)

# ---------- collect data in one pass ------------------------------------------
# by_a1[aid][bi] = [(t, val)]   -- frames in WIN_A1
# by_a2[aid][bi] = [(t, val)]   -- frames in WIN_A2
# by_stab[wi][aid][bi] = [(t, val)] -- frames in STABLE[wi]
by_a1 = defaultdict(lambda: defaultdict(list))
by_a2 = defaultdict(lambda: defaultdict(list))
by_stab = [defaultdict(lambda: defaultdict(list)) for _ in STABLE]

# Power reference (full log, for interpolation)
I_ts = []; I_vs = []   # 0x598 B4-B5 drive current
V_ts = []; V_vs = []   # 0x440 B3-B4 pack voltage

# J1939 extended ID inventory (full log)
j1939 = defaultdict(lambda: defaultdict(list))  # aid -> byte_idx -> [vals]

print("Parsing log (full)...")
frame_count = 0
for frame in parse_file(str(LOG)):
    t   = frame.timestamp
    d   = frame.data
    aid = frame.arbitration_id
    frame_count += 1

    # Power reference -- collect always
    if aid == 0x598 and len(d) >= 6:
        I_ts.append(t); I_vs.append((d[4] | d[5] << 8) - 32768)
    if aid == 0x440 and len(d) >= 5:
        V_ts.append(t); V_vs.append(d[3] | d[4] << 8)

    # J1939 extended ID inventory -- collect always
    if 0x18FF0000 <= aid <= 0x18FFFFFF:
        for i, b in enumerate(d):
            j1939[aid][i].append(b)

    # Skip data collection if outside all analysis windows
    if t < ALL_MIN or t > ALL_MAX:
        continue

    # Delta window A1
    if WIN_A1[0] <= t <= WIN_A1[1]:
        for i, b in enumerate(d):
            by_a1[aid][i].append((t, b))

    # Delta window A2
    if WIN_A2[0] <= t <= WIN_A2[1]:
        for i, b in enumerate(d):
            by_a2[aid][i].append((t, b))

    # Stable windows
    for wi, (wlo, whi) in enumerate(STABLE):
        if wlo <= t <= whi:
            for i, b in enumerate(d):
                by_stab[wi][aid][i].append((t, b))

print(f"  Frames: {frame_count}  |  I_drive samples: {len(I_ts)}"
      f"  |  V_pack samples: {len(V_ts)}  |  J1939 IDs: {len(j1939)}")

# ---------- build power interpolator ------------------------------------------
def power_at(t_q):
    if not I_ts or not V_ts: return 0.0
    ic = interp1(I_ts, I_vs, t_q)
    vc = interp1(V_ts, V_vs, t_q)
    return ic * I_SCALE * vc * V_SCALE / 1000.0  # kW

# ---------- PASS A: delta correlation -----------------------------------------
DELTA_THRESH = 0.35

def delta_scan(by_win):
    """Return list of (aid, bi, r, n, val_min, val_max, n_uniq) sorted by |r|."""
    results = []
    for aid in sorted(by_win.keys()):
        for bi in sorted(by_win[aid].keys()):
            tv = sorted(by_win[aid][bi])   # ensure time order
            if len(tv) < 6: continue
            ts_  = [x[0] for x in tv]
            vs_  = [x[1] for x in tv]
            pws_ = [power_at(t) for t in ts_]

            db = [vs_[i] - vs_[i-1] for i in range(1, len(vs_))]
            dp = [pws_[i] - pws_[i-1] for i in range(1, len(pws_))]

            # Require some power variation (otherwise delta_power is uninformative)
            if max(abs(x) for x in dp) < 0.5: continue  # <0.5 kW max change

            r = pearson(db, dp)
            if r != r: continue   # nan guard
            if abs(r) >= DELTA_THRESH:
                results.append((aid, bi, r, len(db),
                                min(vs_), max(vs_), len(set(vs_))))
    results.sort(key=lambda x: -abs(x[2]))
    return results

p("=" * 72)
p("PASS A  --  Delta correlation (delta_byte vs delta_drivetrain_power)")
p("Immune to MSB-step artifacts. Threshold |delta_r| >= 0.35.")
p("Flags: * = BMS cluster (0x400-0x507)  J = J1939 extended")
p()

hdr_a = (f"{'F':1} {'ID':>10}  {'B':>2}  {'delta_r':>8}  {'n_delta':>7}  "
         f"{'min':>5}  {'max':>5}  {'uniq':>4}")

p(f"--- A1: Merge ramp + post-accel (t={WIN_A1[0]:.0f}-{WIN_A1[1]:.0f}s, "
  f"DCL-active window) ---")
p(hdr_a); p("-" * len(hdr_a))
res_a1 = delta_scan(by_a1)
for aid, bi, r, n, mn, mx, uq in res_a1[:60]:
    p(f"{bms_flag(aid)} 0x{aid:08X}  B{bi}  {r:>+8.3f}  {n:>7}  "
      f"{mn:>5}  {mx:>5}  {uq:>4}")

p()
p(f"--- A2: Reference (t={WIN_A2[0]:.0f}-{WIN_A2[1]:.0f}s, no DCL expected) ---")
p(hdr_a); p("-" * len(hdr_a))
res_a2 = delta_scan(by_a2)
for aid, bi, r, n, mn, mx, uq in res_a2[:40]:
    p(f"{bms_flag(aid)} 0x{aid:08X}  B{bi}  {r:>+8.3f}  {n:>7}  "
      f"{mn:>5}  {mx:>5}  {uq:>4}")

# Cross-reference: in A1 but absent or weak in A2
a2_lookup = {(aid, bi): r for aid, bi, r, *_ in res_a2}
p()
p("--- A-cross: A1 candidates with |delta_r| < 0.20 in A2 ---")
p("  (Signals uniquely responsive in the DCL-active window)")
p(hdr_a + "  A2_r")
p("-" * (len(hdr_a) + 8))
cross_found = 0
for aid, bi, r1, n, mn, mx, uq in res_a1:
    r2 = a2_lookup.get((aid, bi), 0.0)
    if abs(r2) < 0.20:
        p(f"{bms_flag(aid)} 0x{aid:08X}  B{bi}  {r1:>+8.3f}  {n:>7}  "
          f"{mn:>5}  {mx:>5}  {uq:>4}  {r2:>+6.3f}")
        cross_found += 1
if cross_found == 0:
    p("  (none)")

# ---------- PASS B: multi-window stable Pearson --------------------------------
p()
p("=" * 72)
p("PASS B  --  Multi-window stable Pearson (raw byte vs drivetrain power)")
p("Windows: " + "  ".join(f"W{i+1}={w[0]:.0f}-{w[1]:.0f}s"
                           for i, w in enumerate(STABLE)))
p("Candidates with |r| >= 0.50 in 2+ windows.")
p()

WIN_RESULTS = []
for wi, (wlo, whi) in enumerate(STABLE):
    wr = {}
    for aid in by_stab[wi]:
        for bi in by_stab[wi][aid]:
            tv = sorted(by_stab[wi][aid][bi])
            if len(tv) < 5: continue
            ts_ = [x[0] for x in tv]; vs_ = [x[1] for x in tv]
            pws_ = [power_at(t) for t in ts_]
            r = pearson(vs_, pws_)
            if r == r:  # nan guard
                wr[(aid, bi)] = r
    WIN_RESULTS.append(wr)
    p(f"  W{wi+1} ({wlo:.0f}-{whi:.0f}s): {len(wr)} byte-signals evaluated")

p()
all_keys = set()
for wr in WIN_RESULTS: all_keys.update(wr.keys())

multi = []
for key in sorted(all_keys):
    rs = [wr.get(key, float('nan')) for wr in WIN_RESULTS]
    n_strong = sum(1 for r in rs if r == r and abs(r) >= 0.50)
    if n_strong >= 2:
        aid, bi = key
        multi.append((aid, bi, rs, n_strong))
multi.sort(key=lambda x: (-x[3], -max(abs(r) for r in x[2] if r == r)))

hdr_b = (f"{'F':1} {'ID':>10}  {'B':>2}  {'W1':>7}  {'W2':>7}  "
         f"{'W3':>7}  {'W4':>7}  {'n_strong':>8}")
p(f"Multi-window candidates ({len(multi)} found):")
p(hdr_b); p("-" * len(hdr_b))
for aid, bi, rs, ns in multi[:60]:
    rs_str = '  '.join(f"{r:>+7.3f}" if r == r else f"{'  ---':>7}" for r in rs)
    p(f"{bms_flag(aid)} 0x{aid:08X}  B{bi}  {rs_str}  {ns:>8}")

# ---------- PASS C: J1939 extended ID inventory --------------------------------
p()
p("=" * 72)
p("PASS C  --  J1939 Extended IDs (0x18FFxxxx) -- full log")
p(f"  {len(j1939)} distinct 0x18FFxxxx IDs found")
p("  SA = source address (low byte of 29-bit ID)")
p()

hdr_c = f"{'ID':>12}  {'SA':>4}  {'n_frames':>9}  {'n_bytes':>7}  variable_bytes (n_unique)"
p(hdr_c); p("-" * len(hdr_c))
for aid in sorted(j1939.keys()):
    bd = j1939[aid]
    nf = max(len(v) for v in bd.values()) if bd else 0
    nb = len(bd)
    sa = aid & 0xFF
    var = [(bi, len(set(bd[bi]))) for bi in sorted(bd) if len(set(bd[bi])) > 1]
    var_str = ", ".join(f"B{bi}({nu})" for bi, nu in var) if var else "(all constant)"
    p(f"  0x{aid:08X}  0x{sa:02X}  {nf:>9}  {nb:>7}  {var_str}")

# Flag any J1939 IDs NOT already known
KNOWN_J1939 = {0x18FFD7C0, 0x18FFD6B3, 0x18EF2000, 0x18FF0320,
               0x18FFD4B3, 0x18FFD5B3, 0x18FFDAB3, 0x18FFD5C0, 0x18FFDAC0}
unknown = sorted(aid for aid in j1939 if aid not in KNOWN_J1939)
p()
if unknown:
    p(f"  New/unanalyzed J1939 IDs not in prior notes ({len(unknown)}):")
    for aid in unknown:
        bd = j1939[aid]
        nf = max(len(v) for v in bd.values()) if bd else 0
        var = [(bi, len(set(bd[bi]))) for bi in sorted(bd) if len(set(bd[bi])) > 1]
        var_str = ", ".join(f"B{bi}({nu})" for bi, nu in var) if var else "(all constant)"
        p(f"    0x{aid:08X}  SA=0x{aid&0xFF:02X}  n={nf}  varying: {var_str}")
else:
    p("  All J1939 IDs previously known.")

# ---------- summary ------------------------------------------------------------
p()
p("=" * 72)
p("SUMMARY")
p(f"  Pass A delta candidates (A1 |r|>=0.35): {len(res_a1)}")
p(f"  Pass A cross candidates (A1 strong, A2 weak): {cross_found}")
p(f"  Pass B multi-window candidates (2+ windows |r|>=0.50): {len(multi)}")
p(f"  Pass C J1939 IDs: {len(j1939)} total, {len(unknown)} unanalyzed")

# ---------- save ---------------------------------------------------------------
OUT.write_text('\n'.join(lines), encoding='utf-8')
print(f"\nSaved: {OUT}")
