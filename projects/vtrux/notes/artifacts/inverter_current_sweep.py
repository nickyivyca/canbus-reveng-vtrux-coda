"""
inverter_current_sweep.py

Correlate 0x598 generator (B2-B3) and drivetrain (B4-B5) current channels
against all non-BMS-tier signals on the bus, to find the inverter source
signals that the VCU rebroadcasts into 0x598.

Hypothesis: generator and drivetrain channels are sourced from the respective
inverters, not from the BMS. The BMS sweep (bms_current_source_sweep.py) was
negative for all three 0x598 channels.

References (LE uint16, centered at 32768):
  0x598 B2-B3  generator current
  0x598 B4-B5  drivetrain current

Candidate pool: all standard IDs in the log except confirmed BMS-tier:
  (0x370-0x375, 0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460, 0x506, 0x507)
  Also excludes 0x598 itself.

Windows (vtruxevapdrivelog4.log, generator starts t=431.7s):
  W1:  50-400s  -- generator OFF (EV driving baseline)
  W2: 550-750s  -- generator ON
  W3: 800-1000s -- generator ON
  W4: 1100-1300s -- generator ON

A true generator current signal should correlate strongly in W2-W4 but weakly
or with flipped sign in W1. A drivetrain current signal should correlate across
all windows.

Candidate pool: PT bus (bus 2) only -- GMLAN buses excluded since any GMLAN
  message carrying generator current is a VCM rebroadcast, not the inverter source.

Two passes per reference:
  Pass A -- delta correlation (diagnostic only; not used as a gate)
  Pass B -- generator-discriminant Pearson:
    require |r| >= 0.70 in 2+ gen-ON windows (W2/W3/W4)
    AND |r_W1| < 0.35 (weak when generator is off)
    sorted by mean gen-ON |r| descending

Output: artifacts/inverter_current_sweep.txt

Log: logs/vtruxevapdrivelog4.log
"""

import sys
import bisect
import math
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxevapdrivelog4.log"
OUT = Path(__file__).parent / "inverter_current_sweep.txt"

# BMS-tier IDs to exclude from candidates
BMS_IDS = set(range(0x370, 0x376)) | {
    0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460, 0x506, 0x507
}

# Reference channels: name -> (arb_id, byte_lo, byte_hi)
# All LE uint16, centered at 32768
REFS = {
    'generator':  (0x598, 2, 3),
    'drivetrain': (0x598, 4, 5),
}

# Multi-window Pearson windows
# W1: generator OFF; W2-W4: generator ON
STABLE = [
    (50.0,   400.0),   # W1: generator off
    (550.0,  750.0),   # W2: generator on
    (800.0,  1000.0),  # W3: generator on
    (1100.0, 1300.0),  # W4: generator on
]

# Pass B thresholds (generator-discriminant methodology)
# Require strong correlation in gen-ON windows and weak in gen-OFF window.
# Gen-ON: W2/W3/W4 must have |r| >= GEN_ON_THRESH in at least GEN_ON_MIN_WINDOWS.
# Gen-OFF: W1 must have |r| < GEN_OFF_MAX (signals correlated in W1 are not gen-specific).
# Note: W1 r may be undefined (nan) if reference is near-constant when gen is off -- treat nan as passing.
GEN_ON_THRESH      = 0.70
GEN_ON_MIN_WINDOWS = 2   # out of W2, W3, W4
GEN_OFF_MAX        = 0.35

# Delta correlation (Pass A) -- kept for diagnostic output only, not used as a gate
DELTA_THRESH  = 0.35
MIN_N_DELTA   = 5
MIN_N_WIN     = 5

# ---------- helpers -----------------------------------------------------------

def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return float('nan')
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx  = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy  = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0.0 or dy == 0.0:
        return 0.0
    return num / (dx * dy)


def interp_nearest(sorted_ts, sorted_vs, t):
    i = bisect.bisect_left(sorted_ts, t)
    if i == 0:
        return sorted_vs[0]
    if i >= len(sorted_ts):
        return sorted_vs[-1]
    if abs(sorted_ts[i] - t) <= abs(sorted_ts[i - 1] - t):
        return sorted_vs[i]
    return sorted_vs[i - 1]


def le16(data, b):
    return (data[b + 1] << 8) | data[b]


def be16(data, b):
    return (data[b] << 8) | data[b + 1]


# ---------- collect data in one pass ------------------------------------------

print("Parsing log...")

ref_ts = {k: [] for k in REFS}
ref_vs = {k: [] for k in REFS}

# cand_raw[aid][bi] = [(t, byte_val), ...]
cand_raw = defaultdict(lambda: defaultdict(list))

frame_count = 0
for frame in parse_file(str(LOG)):
    t   = frame.timestamp
    d   = frame.data
    aid = frame.arbitration_id
    frame_count += 1

    # Collect reference channels from 0x598
    if aid == 0x598 and len(d) >= 6:
        for ref_name, (rid, blo, bhi) in REFS.items():
            ref_ts[ref_name].append(t)
            ref_vs[ref_name].append(le16(d, blo) - 32768)

    # Collect candidate bytes -- PT bus (bus 2) only, skip BMS-tier and 0x598
    if frame.bus != 2:
        continue
    if aid in BMS_IDS or aid == 0x598:
        continue
    # Only standard IDs (extended IDs are charger/DCDC, not inverter candidates)
    if aid > 0x7FF:
        continue
    for bi, bval in enumerate(d):
        cand_raw[aid][bi].append((t, bval))

print(f"  Frames total: {frame_count:,}")
for rn in REFS:
    print(f"  Reference '{rn}' (0x598): {len(ref_ts[rn])} samples, "
          f"range [{min(ref_vs[rn])}, {max(ref_vs[rn])}]")
print(f"  Candidate IDs collected: {len(cand_raw)}")

# ---------- build candidate signal list ---------------------------------------

candidates = []

for aid in sorted(cand_raw):
    dlc = max(cand_raw[aid].keys()) + 1 if cand_raw[aid] else 0

    # Single bytes
    for bi in sorted(cand_raw[aid]):
        tv = sorted(cand_raw[aid][bi])
        if len(tv) < MIN_N_DELTA:
            continue
        candidates.append((aid, bi, 'byte', tv))

    # LE uint16 pairs
    for blo_c in range(dlc - 1):
        bhi_c = blo_c + 1
        if blo_c not in cand_raw[aid] or bhi_c not in cand_raw[aid]:
            continue
        tv_lo = {t: v for t, v in cand_raw[aid][blo_c]}
        tv_hi = {t: v for t, v in cand_raw[aid][bhi_c]}
        common_ts = sorted(set(tv_lo) & set(tv_hi))
        if len(common_ts) < MIN_N_DELTA:
            continue
        tv = [(t, (tv_hi[t] << 8) | tv_lo[t]) for t in common_ts]
        candidates.append((aid, blo_c, 'le16', tv))

    # BE uint16 pairs
    for blo_c in range(dlc - 1):
        bhi_c = blo_c + 1
        if blo_c not in cand_raw[aid] or bhi_c not in cand_raw[aid]:
            continue
        tv_lo = {t: v for t, v in cand_raw[aid][blo_c]}
        tv_hi = {t: v for t, v in cand_raw[aid][bhi_c]}
        common_ts = sorted(set(tv_lo) & set(tv_hi))
        if len(common_ts) < MIN_N_DELTA:
            continue
        tv = [(t, (tv_lo[t] << 8) | tv_hi[t]) for t in common_ts]
        candidates.append((aid, blo_c, 'be16', tv))

print(f"  Total candidate signals: {len(candidates)}")

# ---------- output helpers ----------------------------------------------------

lines = []

def p(s=''):
    print(s)
    lines.append(s)

def enc_label(kind):
    return {'byte': 'byte', 'le16': 'LE16', 'be16': 'BE16'}[kind]

# ---------- per-reference sweep -----------------------------------------------

for ref_name, (rid, blo, bhi) in REFS.items():

    rts = ref_ts[ref_name]
    rvs = ref_vs[ref_name]

    if len(rts) < MIN_N_DELTA:
        p(f"\n*** Reference '{ref_name}' has too few samples -- skipping ***")
        continue

    p()
    p("=" * 74)
    p(f"REFERENCE: {ref_name.upper()} CURRENT  (0x{rid:03X} B{blo}-B{bhi} LE, centered 32768)")
    p(f"  Samples: {len(rts)}   range: [{min(rvs)}, {max(rvs)}]")
    p("=" * 74)

    # ------------------------------------------------------------------
    # Pass A: Delta correlation
    # ------------------------------------------------------------------
    p()
    p(f"--- Pass A: Delta correlation (threshold |r| >= {DELTA_THRESH}) ---")
    p(f"{'ID':>10}  {'B':>2}  {'enc':>4}  {'delta_r':>8}  "
      f"{'n':>5}  {'uniq':>4}  {'min':>7}  {'max':>7}")
    p("-" * 62)

    pass_a_results = []

    for aid, bstart, kind, tv in candidates:
        ts_ = [x[0] for x in tv]
        vs_ = [x[1] for x in tv]

        if len(ts_) < MIN_N_DELTA + 1:
            continue

        dv_cand = []
        dv_ref  = []
        for i in range(1, len(ts_)):
            dc = vs_[i] - vs_[i - 1]
            r0 = interp_nearest(rts, rvs, ts_[i - 1])
            r1 = interp_nearest(rts, rvs, ts_[i])
            dr = r1 - r0
            dv_cand.append(dc)
            dv_ref.append(dr)

        r = pearson(dv_cand, dv_ref)
        if math.isnan(r):
            continue

        pass_a_results.append((aid, bstart, kind, r, len(dv_cand),
                               len(set(vs_)), min(vs_), max(vs_)))

    pass_a_results.sort(key=lambda x: -abs(x[3]))

    shown = 0
    for aid, bstart, kind, r, n, uniq, mn, mx in pass_a_results:
        if abs(r) < DELTA_THRESH:
            break
        p(f"  0x{aid:03X}  B{bstart}  {enc_label(kind):>4}  {r:>+8.3f}  "
          f"{n:>5}  {uniq:>4}  {mn:>7}  {mx:>7}")
        shown += 1

    if shown == 0:
        p("  (no candidates above threshold)")

    # ------------------------------------------------------------------
    # Pass B: Generator-discriminant multi-window Pearson
    # Require |r| >= GEN_ON_THRESH in GEN_ON_MIN_WINDOWS of W2/W3/W4 (gen-ON)
    # AND |r_W1| < GEN_OFF_MAX (gen-OFF weak; nan passes -- ref near-constant)
    # Sort by mean gen-ON |r| descending.
    # ------------------------------------------------------------------
    p()
    win_labels = [f"W{i+1}({int(w[0])}-{int(w[1])}s)" for i, w in enumerate(STABLE)]
    p(f"--- Pass B: Generator-discriminant Pearson")
    p(f"    gen-ON:  |r| >= {GEN_ON_THRESH} in {GEN_ON_MIN_WINDOWS}+ of W2/W3/W4")
    p(f"    gen-OFF: |r_W1| < {GEN_OFF_MAX} (or nan)")
    p(f"  Note: W1=generator OFF; W2-W4=generator ON")
    p(f"{'ID':>10}  {'B':>2}  {'enc':>4}  " +
      "  ".join(f"{wl:>14}" for wl in win_labels) + f"  {'mean_on':>8}")
    p("-" * (44 + 16 * len(STABLE)))

    pass_b_results = []

    for aid, bstart, kind, tv in candidates:
        ts_ = [x[0] for x in tv]
        vs_ = [x[1] for x in tv]

        win_rs = []
        for wlo, whi in STABLE:
            cand_vals = []
            ref_vals  = []
            for i, t in enumerate(ts_):
                if wlo <= t <= whi:
                    rv = interp_nearest(rts, rvs, t)
                    cand_vals.append(vs_[i])
                    ref_vals.append(rv)
            if len(cand_vals) < MIN_N_WIN:
                win_rs.append(float('nan'))
            else:
                win_rs.append(pearson(cand_vals, ref_vals))

        # gen-OFF check: W1 must be weak (nan is OK)
        r_w1 = win_rs[0]
        if not math.isnan(r_w1) and abs(r_w1) >= GEN_OFF_MAX:
            continue

        # gen-ON check: need GEN_ON_MIN_WINDOWS windows above threshold in W2/W3/W4
        on_rs = [win_rs[i] for i in (1, 2, 3)]
        n_strong_on = sum(1 for r in on_rs if not math.isnan(r) and abs(r) >= GEN_ON_THRESH)
        if n_strong_on < GEN_ON_MIN_WINDOWS:
            continue

        valid_on = [abs(r) for r in on_rs if not math.isnan(r)]
        mean_on = sum(valid_on) / len(valid_on) if valid_on else 0.0
        pass_b_results.append((aid, bstart, kind, win_rs, n_strong_on, mean_on))

    pass_b_results.sort(key=lambda x: -x[5])

    for aid, bstart, kind, win_rs, n_strong_on, mean_on in pass_b_results:
        rs_str = "  ".join(
            f"{r:>+14.3f}" if not math.isnan(r) else f"{'---':>14}"
            for r in win_rs
        )
        p(f"  0x{aid:03X}  B{bstart}  {enc_label(kind):>4}  {rs_str}  {mean_on:>8.3f}")

    if not pass_b_results:
        p("  (no candidates passed generator-discriminant filter)")

    # Summary
    p()
    p(f"--- Summary for {ref_name} ---")
    a_set = {(aid, bstart, kind) for aid, bstart, kind, r, *_ in pass_a_results
             if abs(r) >= DELTA_THRESH}
    b_set = {(aid, bstart, kind) for aid, bstart, kind, *_ in pass_b_results}
    p(f"  Pass A diagnostic candidates (delta_r >= {DELTA_THRESH}): {len(a_set)}")
    p(f"  Pass B generator-discriminant candidates: {len(b_set)}")
    for aid, bstart, kind, win_rs, n_strong_on, mean_on in pass_b_results:
        p(f"    -> 0x{aid:03X} B{bstart} {enc_label(kind)}  mean_on_r={mean_on:+.3f}")

p()
p("--- END ---")

OUT.write_text('\n'.join(lines), encoding='utf-8')
print(f"\nSaved: {OUT}")
