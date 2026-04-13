"""
bms_current_source_sweep.py

Sweep BMS-tier message IDs (0x370-0x375, 0x400-0x507) for signals correlated
with 0x598 battery, generator, and drivetrain current channels.

Hypothesis: 0x598 (B0-B1 battery, B2-B3 generator, B4-B5 drivetrain) are VCU
rebroadcasts of BMS-sourced current data. This sweep finds the BMS source(s).

References (all LE uint16, centered at 32768; roles confirmed VCU-sourced):
  0x598 B0-B1  battery current
  0x598 B2-B3  generator current
  0x598 B4-B5  drivetrain current

Candidate pool: BMS-tier IDs confirmed absent from parts truck and killed by
HV battery LV connector unplug (dropout at t=75-76s in disconnect test).

Three passes per reference:
  Pass A -- Delta correlation (immune to MSB-step artifacts)
            delta_candidate vs delta_reference across full log.
            For each consecutive pair of candidate frames, reference is
            interpolated at both timestamps and differenced in sync.
  Pass B -- Multi-window stable Pearson
            Raw Pearson in 4 short stable windows. Candidates with |r|>=0.50
            in 2+ windows are consistently correlated across drive conditions.
  Encodings tested per candidate: uint8 byte, LE uint16, BE uint16.

Log: logs/vtruxcurrentlimitingtest.log
Output: artifacts/bms_current_source_sweep.txt
"""

import sys
import bisect
import math
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
OUT = Path(__file__).parent / "bms_current_source_sweep.txt"

# BMS-tier IDs (confirmed by HV battery LV connector dropout test)
BMS_IDS = set(range(0x370, 0x376)) | {
    0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460, 0x506, 0x507
}

# Reference channels: name -> (arb_id, byte_lo, byte_hi)
# All LE uint16, centered at 32768
REFS = {
    'battery':    (0x598, 0, 1),
    'generator':  (0x598, 2, 3),
    'drivetrain': (0x598, 4, 5),
}

# Multi-window Pearson: 4 short stable windows across the log
STABLE = [
    (30.0,  70.0),    # W1: downhill regen
    (150.0, 250.0),   # W2: flat baseline
    (400.0, 500.0),   # W3: mixed driving
    (600.0, 700.0),   # W4: highway
]

DELTA_THRESH  = 0.35   # minimum |r| to report in Pass A
WINDOW_THRESH = 0.50   # minimum |r| in Pass B per window
MIN_WINDOWS   = 2      # must exceed threshold in this many windows
MIN_N_DELTA   = 5      # minimum delta pairs for Pass A
MIN_N_WIN     = 5      # minimum samples per stable window

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
    """Return value from sorted list nearest to t (no tolerance limit)."""
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

# ref_ts[ref_name] = sorted list of timestamps
# ref_vs[ref_name] = corresponding values (centered at 0)
ref_ts = {k: [] for k in REFS}
ref_vs = {k: [] for k in REFS}

# bms[aid][bi] = [(t, byte_val), ...]  -- full log
bms_raw = defaultdict(lambda: defaultdict(list))

frame_count = 0
for frame in parse_file(str(LOG)):
    t   = frame.timestamp
    d   = frame.data
    aid = frame.arbitration_id
    frame_count += 1

    # Collect reference channels from 0x598
    if aid == 0x598 and len(d) >= 6:
        for ref_name, (rid, blo, bhi) in REFS.items():
            if len(d) > bhi:
                ref_ts[ref_name].append(t)
                ref_vs[ref_name].append(le16(d, blo) - 32768)

    # Collect BMS-tier candidates
    if aid in BMS_IDS:
        for bi, bval in enumerate(d):
            bms_raw[aid][bi].append((t, bval))

print(f"  Frames total: {frame_count:,}")
for rn in REFS:
    print(f"  Reference '{rn}' (0x598): {len(ref_ts[rn])} samples")
for aid in sorted(bms_raw):
    n = max(len(v) for v in bms_raw[aid].values()) if bms_raw[aid] else 0
    print(f"  BMS 0x{aid:03X}: {n} frames, {len(bms_raw[aid])} bytes")


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
    # Build candidate signals: byte, LE16, BE16 for each BMS ID
    # Each entry: (aid, byte_start, kind, [(t, val), ...])
    # ------------------------------------------------------------------
    candidates = []

    for aid in sorted(bms_raw):
        dlc = max(bms_raw[aid].keys()) + 1 if bms_raw[aid] else 0

        # Single bytes
        for bi in sorted(bms_raw[aid]):
            tv = sorted(bms_raw[aid][bi])
            if len(tv) < MIN_N_DELTA:
                continue
            candidates.append((aid, bi, 'byte', tv))

        # LE uint16 pairs
        for blo_c in range(dlc - 1):
            bhi_c = blo_c + 1
            # Need both bytes present in every frame
            if blo_c not in bms_raw[aid] or bhi_c not in bms_raw[aid]:
                continue
            # Merge by timestamp: only frames where both bytes were seen
            tv_lo = {t: v for t, v in bms_raw[aid][blo_c]}
            tv_hi = {t: v for t, v in bms_raw[aid][bhi_c]}
            common_ts = sorted(set(tv_lo) & set(tv_hi))
            if len(common_ts) < MIN_N_DELTA:
                continue
            tv = [(t, (tv_hi[t] << 8) | tv_lo[t]) for t in common_ts]
            candidates.append((aid, blo_c, 'le16', tv))

        # BE uint16 pairs
        for blo_c in range(dlc - 1):
            bhi_c = blo_c + 1
            if blo_c not in bms_raw[aid] or bhi_c not in bms_raw[aid]:
                continue
            tv_lo = {t: v for t, v in bms_raw[aid][blo_c]}
            tv_hi = {t: v for t, v in bms_raw[aid][bhi_c]}
            common_ts = sorted(set(tv_lo) & set(tv_hi))
            if len(common_ts) < MIN_N_DELTA:
                continue
            tv = [(t, (tv_lo[t] << 8) | tv_hi[t]) for t in common_ts]
            candidates.append((aid, blo_c, 'be16', tv))

    p(f"  Total candidate signals: {len(candidates)}")

    # ------------------------------------------------------------------
    # Pass A: Delta correlation
    # For each candidate: align deltas to reference via interpolation
    # ------------------------------------------------------------------
    p()
    p(f"--- Pass A: Delta correlation (threshold |r| >= {DELTA_THRESH}) ---")
    p(f"{'ID':>10}  {'B':>2}  {'enc':>4}  {'delta_r':>8}  "
      f"{'n':>5}  {'uniq':>4}  {'min':>6}  {'max':>6}")
    p("-" * 60)

    pass_a_results = []

    for aid, bstart, kind, tv in candidates:
        ts_ = [x[0] for x in tv]
        vs_ = [x[1] for x in tv]

        if len(ts_) < MIN_N_DELTA + 1:
            continue

        # Build delta pairs
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
          f"{n:>5}  {uniq:>4}  {mn:>6}  {mx:>6}")
        shown += 1

    if shown == 0:
        p("  (no candidates above threshold)")

    # ------------------------------------------------------------------
    # Pass B: Multi-window stable Pearson
    # ------------------------------------------------------------------
    p()
    p(f"--- Pass B: Multi-window Pearson (|r|>={WINDOW_THRESH} in {MIN_WINDOWS}+ of {len(STABLE)} windows) ---")

    win_labels = [f"W{i+1}({int(w[0])}-{int(w[1])}s)" for i, w in enumerate(STABLE)]
    p(f"{'ID':>10}  {'B':>2}  {'enc':>4}  " +
      "  ".join(f"{wl:>12}" for wl in win_labels) + f"  {'n_strong':>8}")
    p("-" * (40 + 14 * len(STABLE)))

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

        n_strong = sum(1 for r in win_rs
                       if not math.isnan(r) and abs(r) >= WINDOW_THRESH)
        if n_strong >= MIN_WINDOWS:
            pass_b_results.append((aid, bstart, kind, win_rs, n_strong))

    pass_b_results.sort(key=lambda x: (
        -x[4],
        -max((abs(r) for r in x[3] if not math.isnan(r)), default=0.0)
    ))

    for aid, bstart, kind, win_rs, n_strong in pass_b_results:
        rs_str = "  ".join(
            f"{r:>+12.3f}" if not math.isnan(r) else f"{'---':>12}"
            for r in win_rs
        )
        p(f"  0x{aid:03X}  B{bstart}  {enc_label(kind):>4}  {rs_str}  {n_strong:>8}")

    if not pass_b_results:
        p("  (no candidates above threshold in 2+ windows)")

    # ------------------------------------------------------------------
    # Summary for this reference
    # ------------------------------------------------------------------
    p()
    p(f"--- Summary for {ref_name} ---")
    a_top = [(aid, bstart, kind, r) for aid, bstart, kind, r, *_ in pass_a_results
             if abs(r) >= DELTA_THRESH]
    b_top = [(aid, bstart, kind, win_rs, ns) for aid, bstart, kind, win_rs, ns
             in pass_b_results]
    both  = {(aid, bstart, kind) for aid, bstart, kind, _ in a_top} & \
            {(aid, bstart, kind) for aid, bstart, kind, *_ in b_top}

    p(f"  Pass A candidates (|delta_r| >= {DELTA_THRESH}): {len(a_top)}")
    p(f"  Pass B candidates (2+ windows >= {WINDOW_THRESH}): {len(b_top)}")
    p(f"  Confirmed by both passes: {len(both)}")
    for aid, bstart, kind in sorted(both):
        a_r = next(r for a, bs, k, r, *_ in pass_a_results
                   if a == aid and bs == bstart and k == kind)
        p(f"    -> 0x{aid:03X} B{bstart} {enc_label(kind)}  delta_r={a_r:+.3f}")


# ---------- save output -------------------------------------------------------

p()
p("--- END ---")

OUT.write_text('\n'.join(lines), encoding='utf-8')
print(f"\nSaved: {OUT}")
