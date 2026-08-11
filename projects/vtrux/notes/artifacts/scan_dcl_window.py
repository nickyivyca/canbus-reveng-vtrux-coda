"""
scan_dcl_window.py

Two-pass scan to find the DCL (discharge current limit) signal.

Pass 1 -- Step-change: compare every byte's mode/median in the pre-limit
  reference window vs the confirmed DCL-active window.
    Reference : t=503-560s  (post-regen-limit, pre-stop-sign, vehicle moving)
    DCL-active: t=614-622s  (full throttle, high RPM, power capped <150 kW)

Pass 2 -- Analog correlation: correlate each byte against drivetrain power
  during the highway merge ramp (t=598-630s) to find signals that track
  the progressive power limiting during acceleration.

Scans ALL CAN IDs. BMS cluster (0x400-0x507) flagged with '*'.
Output saved to scan_dcl_window.txt alongside this script.
"""

import sys, bisect
from pathlib import Path
from collections import defaultdict, Counter
import statistics

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
OUT = Path(__file__).parent / "scan_dcl_window.txt"

WIN_REF  = (503.0, 560.0)   # reference: no DCL, vehicle moving normally
WIN_DCL  = (614.0, 622.0)   # DCL-active: confirmed constrained frames
WIN_RAMP = (598.0, 630.0)   # merge ramp: for analog correlation

I_SCALE = 0.04124
V_SCALE = 0.015031   # from plot_drive_overview calibration

# ---------- collect -------------------------------------------------------------
ref_bytes  = defaultdict(lambda: defaultdict(list))   # aid -> byte_idx -> [val]
dcl_bytes  = defaultdict(lambda: defaultdict(list))
ramp_bytes = defaultdict(lambda: defaultdict(list))   # aid -> byte_idx -> [(t, val)]

idrive_ramp = []
vpack_ramp  = []

print("Parsing log...")
for frame in parse_file(str(LOG)):
    t   = frame.timestamp
    d   = frame.data
    aid = frame.arbitration_id

    if WIN_REF[0] <= t <= WIN_REF[1]:
        for i, b in enumerate(d):
            ref_bytes[aid][i].append(b)

    if WIN_DCL[0] <= t <= WIN_DCL[1]:
        for i, b in enumerate(d):
            dcl_bytes[aid][i].append(b)

    if WIN_RAMP[0] <= t <= WIN_RAMP[1]:
        for i, b in enumerate(d):
            ramp_bytes[aid][i].append((t, b))
        if aid == 0x598 and len(d) >= 6:
            idrive_ramp.append((t, (d[4] | d[5] << 8) - 32768))
        if aid == 0x440 and len(d) >= 5:
            vpack_ramp.append((t, d[3] | d[4] << 8))

    if t > WIN_RAMP[1] + 5:
        break  # all windows collected; stop early

print(f"  IDs in ref window : {len(ref_bytes)}")
print(f"  IDs in DCL window : {len(dcl_bytes)}")
print(f"  IDs in ramp window: {len(ramp_bytes)}")

# ---------- build power timeseries during ramp ---------------------------------
vt = [t for t, _ in vpack_ramp]
vv = [v for _, v in vpack_ramp]

def nearest_v(t_q):
    i = bisect.bisect_left(vt, t_q)
    if i == 0: return vv[0]
    if i >= len(vt): return vv[-1]
    return vv[i] if abs(vt[i]-t_q) < abs(vt[i-1]-t_q) else vv[i-1]

power_ramp = []
for t, i_cts in idrive_ramp:
    kw = i_cts * I_SCALE * nearest_v(t) * V_SCALE / 1000.0
    power_ramp.append((t, kw))

print(f"  Power ramp samples: {len(power_ramp)}")
if power_ramp:
    print(f"  Power range: {min(v for _,v in power_ramp):.1f} to "
          f"{max(v for _,v in power_ramp):.1f} kW")

# ---------- helpers ------------------------------------------------------------
def bms(aid):
    return '*' if 0x400 <= aid <= 0x507 else ' '

def pearson(xs, ys):
    n = len(xs)
    if n < 6: return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx  = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy  = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0: return 0.0
    return num / (dx * dy)

lines = []
def p(s=''):
    print(s)
    lines.append(s)

# ---------- Pass 1: step-change scan -------------------------------------------
common = set(ref_bytes.keys()) & set(dcl_bytes.keys())

step = []
for aid in sorted(common):
    for bi in sorted(ref_bytes[aid].keys()):
        if bi not in dcl_bytes[aid]:
            continue
        rv = ref_bytes[aid][bi]
        dv = dcl_bytes[aid][bi]
        r_mode = Counter(rv).most_common(1)[0][0]
        d_mode = Counter(dv).most_common(1)[0][0]
        if r_mode == d_mode:
            continue
        r_med  = statistics.median(rv)
        d_med  = statistics.median(dv)
        r_uniq = len(set(rv))
        d_uniq = len(set(dv))
        step.append((aid, bi, r_mode, d_mode, r_med, d_med,
                     r_uniq, d_uniq, len(rv), len(dv)))

step.sort(key=lambda x: abs(x[3] - x[2]), reverse=True)

p("=== Pass 1: Step-change bytes (mode differs ref vs DCL) ===")
p(f"  Reference t={WIN_REF[0]:.0f}-{WIN_REF[1]:.0f}s  |  DCL t={WIN_DCL[0]:.0f}-{WIN_DCL[1]:.0f}s")
p(f"  {len(step)} bytes changed")
p(f"  * = BMS cluster (0x400-0x507)")
p()
hdr = (f"{'':1} {'ID':>6}  {'B':>2}  {'r_mode':>7}  {'d_mode':>7}  "
       f"{'delta':>7}  {'r_med':>6}  {'d_med':>6}  "
       f"{'r_uq':>4}  {'d_uq':>4}  {'n_ref':>5}  {'n_dcl':>5}")
p(hdr)
p("-" * len(hdr))
for aid, bi, rm, dm, rmed, dmed, ruq, duq, nr, nd in step:
    p(f"{bms(aid)} 0x{aid:03X}  B{bi}  {rm:>7}  {dm:>7}  "
      f"{dm-rm:>+7}  {rmed:>6.1f}  {dmed:>6.1f}  "
      f"{ruq:>4}  {duq:>4}  {nr:>5}  {nd:>5}")

# ---------- Pass 1b: 16-bit LE pairs -------------------------------------------
pair_step = []
for aid in sorted(common):
    max_b = max(ref_bytes[aid].keys())
    for b in range(max_b):
        if (b not in ref_bytes[aid] or (b+1) not in ref_bytes[aid] or
                b not in dcl_bytes[aid] or (b+1) not in dcl_bytes[aid]):
            continue
        rl = ref_bytes[aid][b];  rh = ref_bytes[aid][b+1]
        dl = dcl_bytes[aid][b];  dh = dcl_bytes[aid][b+1]
        n = min(len(rl), len(rh));  m = min(len(dl), len(dh))
        if n < 2 or m < 2: continue
        r16 = [rl[i] | rh[i] << 8 for i in range(n)]
        d16 = [dl[i] | dh[i] << 8 for i in range(m)]
        rm16 = Counter(r16).most_common(1)[0][0]
        dm16 = Counter(d16).most_common(1)[0][0]
        if rm16 == dm16: continue
        pair_step.append((aid, b, rm16, dm16,
                          statistics.median(r16), statistics.median(d16),
                          len(set(r16)), len(set(d16)), n, m))

pair_step.sort(key=lambda x: abs(x[3]-x[2]), reverse=True)

p()
p("=== Pass 1b: 16-bit LE pairs with changed mode ===")
hdr2 = (f"{'':1} {'ID':>6}  {'bytes':>6}  {'r_mode':>7}  {'d_mode':>7}  "
        f"{'delta':>7}  {'r_med':>7}  {'d_med':>7}  "
        f"{'r_uq':>4}  {'d_uq':>4}  {'n_ref':>5}  {'n_dcl':>5}")
p(hdr2)
p("-" * len(hdr2))
for aid, b, rm, dm, rmed, dmed, ruq, duq, nr, nd in pair_step[:40]:
    p(f"{bms(aid)} 0x{aid:03X}  B{b}-B{b+1}  {rm:>7}  {dm:>7}  "
      f"{dm-rm:>+7}  {rmed:>7.1f}  {dmed:>7.1f}  "
      f"{ruq:>4}  {duq:>4}  {nr:>5}  {nd:>5}")

# ---------- Pass 2: analog correlation with ramp power -------------------------
p()
p(f"=== Pass 2: Analog correlation with drivetrain power (t={WIN_RAMP[0]:.0f}-{WIN_RAMP[1]:.0f}s) ===")
p("  |r| >= 0.60 shown. + = rises with power, - = falls with power.")
p("  NOTE: monotone acceleration means many bytes will spuriously correlate.")
p("  Prefer candidates also found in Pass 1, or with unusual correlation sign.")
p()

if power_ramp:
    pt = [t for t, _ in power_ramp]
    pv = [v for _, v in power_ramp]

    def nearest_pwr(t_q):
        i = bisect.bisect_left(pt, t_q)
        if i == 0: return pv[0]
        if i >= len(pt): return pv[-1]
        return pv[i] if abs(pt[i]-t_q) < abs(pt[i-1]-t_q) else pv[i-1]

    corr = []
    for aid in sorted(ramp_bytes.keys()):
        for bi in sorted(ramp_bytes[aid].keys()):
            tv = ramp_bytes[aid][bi]
            if len(tv) < 8: continue
            bvals = [v for _, v in tv]
            pvals = [nearest_pwr(t) for t, _ in tv]
            r = pearson(bvals, pvals)
            if abs(r) >= 0.60:
                corr.append((aid, bi, r, len(tv),
                             min(bvals), max(bvals), len(set(bvals))))

    corr.sort(key=lambda x: -abs(x[2]))
    hdr3 = (f"{'':1} {'ID':>6}  {'B':>2}  {'r':>7}  {'n':>5}  "
            f"{'min':>5}  {'max':>5}  {'uniq':>4}")
    p(hdr3)
    p("-" * len(hdr3))
    for aid, bi, r, n, mn, mx, uq in corr[:50]:
        p(f"{bms(aid)} 0x{aid:03X}  B{bi}  {r:>+7.3f}  {n:>5}  "
          f"{mn:>5}  {mx:>5}  {uq:>4}")
else:
    p("  No power data collected in ramp window.")

# ---------- save output --------------------------------------------------------
OUT.write_text('\n'.join(lines), encoding='utf-8')
print(f"\nSaved: {OUT}")
