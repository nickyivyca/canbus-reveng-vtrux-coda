"""
Did today's cell imbalance (vmax-vmin) widen over the session, or hold steady?

Tracks the RESTING spread (low current, settled) over the 19:39 session timeline.
Because spread is SoC-amplified (OCV steeper at low SoC), it also normalizes to a
SoC-% imbalance using the locally-measured dOCV/dSoC, and does a matched-SoC
early-vs-late comparison so SoC drift can't masquerade as a trend.
"""
import sys
sys.path.insert(0, ".")
from battery_degradation_characterize import collect, median, simple_slope, discover_sessions

LOGDIR = "../../CANLogs/VtruxLogs"
sess = discover_sessions(LOGDIR, "20260617")
files = dict(sess)["vtrux_20260617_193900"]
s = collect(files)   # cache hit -> fast

# ---- settled rest samples: |I|<10 now AND for the previous ~2s ----
REST_I = 10.0
rest = []
for i in range(len(s)):
    if abs(s[i]["ibat"]) >= REST_I:
        continue
    ok = True
    j = i - 1
    span = 0.0
    while j >= 0 and span < 2.0:
        dt = s[j + 1]["t"] - s[j]["t"]
        if dt < 0:            # chunk boundary / reset
            break
        span += dt
        if abs(s[j]["ibat"]) >= 15.0:
            ok = False
            break
        j -= 1
    if ok:
        rest.append(s[i])
print(f"total samples={len(s)}  settled-rest samples={len(rest)}")

# ---- local dOCV/dSoC from settled-rest avg-cell vs SoC ----
soc_r = [x["soc"] for x in rest]
avg_r = [x["avg"] for x in rest]
slope = simple_slope(soc_r, avg_r)
print(f"dOCV/dSoC (settled rest, avg cell) = {slope:.2f} mV/%  "
      f"(SoC range {min(soc_r):.1f}-{max(soc_r):.1f}%)")

# ---- timeline: split settled-rest samples into 10 equal-count segments ----
print("\n=== resting spread over the session (10 equal-count segments) ===")
print(f"  {'seg':>4}{'t_rel(s)':>10}{'meanSoC':>9}{'meanT(C)':>9}{'n':>6}"
      f"{'spread(mV)':>12}{'imbal(%SoC)':>12}")
t0 = s[0]["t"]
N = 10
per = max(1, len(rest) // N)
for k in range(N):
    seg = rest[k * per: (k + 1) * per] if k < N - 1 else rest[k * per:]
    if not seg:
        continue
    spr = [x["vmax"] - x["vmin"] for x in seg]
    msoc = sum(x["soc"] for x in seg) / len(seg)
    mt = sum((x["tmax"] or 0) for x in seg) / len(seg)
    msp = median(spr)
    imb = msp / slope if slope else float("nan")
    trel = seg[len(seg)//2]["t"] - t0
    print(f"  {k:>4}{trel:>10.0f}{msoc:>9.1f}{mt:>9.1f}{len(seg):>6}{msp:>12.1f}{imb:>12.2f}")

# ---- matched-SoC: compare resting spread at the same SoC, early vs late half ----
print("\n=== matched-SoC early-vs-late (settled rest) ===")
mid_t = (s[0]["t"] + s[-1]["t"]) / 2
print(f"  {'SoC band':>10}{'early n':>9}{'early mV':>10}{'late n':>9}{'late mV':>10}{'delta mV':>10}")
import math
soc_lo = math.floor(min(soc_r))
soc_hi = math.ceil(max(soc_r))
for lo in range(soc_lo, soc_hi):
    band = [x for x in rest if lo <= x["soc"] < lo + 1]
    early = [x["vmax"] - x["vmin"] for x in band if x["t"] < mid_t]
    late = [x["vmax"] - x["vmin"] for x in band if x["t"] >= mid_t]
    if len(early) >= 10 and len(late) >= 10:
        me, ml = median(early), median(late)
        print(f"  {lo:>4}-{lo+1:<5}{len(early):>9}{me:>10.1f}{len(late):>9}{ml:>10.1f}{ml-me:>+10.1f}")
