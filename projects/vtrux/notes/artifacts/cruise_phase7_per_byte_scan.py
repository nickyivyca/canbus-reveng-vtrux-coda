"""
cruise_phase7_per_byte_scan.py

Phase 7: per-byte AND BE uint16 pair scan for cruise control command signal.

Previous scans (Phases 5 and 6) only tested LE uint16 pairs. Phase 7 adds:
  - Individual byte (uint8) tests  -- catches zone+fine or single-byte signals
  - BE uint16 pair tests           -- catches big-endian 16-bit signals

Scans all PT bus frames from vtruxevapdrivelog4.log across three time segments:
  pre_hybrid   t=431-720s    (hybrid, manual driving)
  cruise       t=720-1080s   (zero-throttle cruise, confirmed)
  post_hybrid  t=1122-1462s  (hybrid, manual driving)

Tests each candidate against TWO references collected inline from 0x5A2:
  - Traction torque feedback (0x5A2 B4-B5 LE, centered 32768)  -> Hyp A torque cmd
  - Motor speed              (0x5A2 B2-B3 LE, centered 32768)  -> Hyp B setpoint

Output sections:
  A: Single bytes   sorted by |delta_r vs torque_feedback| desc   (Hyp A)
  B: Single bytes   sorted by sd_cruise asc  (setpoint candidates, Hyp B)
  C: BE uint16 pairs sorted by |delta_r vs torque_feedback| desc  (Hyp A)
  D: BE uint16 pairs sorted by sd_cruise asc (setpoint candidates, Hyp B)
  E: Plateau detail for top Section B+D candidates
     (unique value distribution within cruise window)

Output: cruise_phase7_per_byte_scan.txt
"""

import sys
import os
import math
import bisect
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG    = 'projects/vtrux/logs/vtruxevapdrivelog4.log'
PT_BUS = 2
OUTPUT = 'projects/vtrux/notes/artifacts/cruise_phase7_per_byte_scan.txt'

SPEED_ID    = 0x5A2
SPEED_B     = 2   # B2-B3 LE = motor speed
TORQUE_B    = 4   # B4-B5 LE = traction torque feedback

SEGMENTS = {
    'pre_hybrid':  (431,  720),
    'cruise':      (720,  1080),
    'post_hybrid': (1122, 1462),
}

TOP_N             = 80
MIN_PAIRS         = 50
SETPOINT_STDEV_MAX = 20.0   # counts; sd_cruise below this = setpoint candidate
PLATEAU_TOP_N     = 30      # how many to show in Section E


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def pearson_r(xs, ys, min_n=MIN_PAIRS):
    n = len(xs)
    if n < min_n:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / n
    sx  = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy  = math.sqrt(sum((y - my) ** 2 for y in ys) / n)
    if sx < 1e-9 or sy < 1e-9:
        return None
    return cov / (sx * sy)


def stdev(xs):
    n = len(xs)
    if n < 2:
        return float('nan')
    mx = sum(xs) / n
    return math.sqrt(sum((x - mx) ** 2 for x in xs) / n)


def nearest_value(sorted_ts, sorted_vs, t, tol=0.06):
    """Return value from sorted list nearest to t, within tol seconds."""
    idx = bisect.bisect_left(sorted_ts, t)
    best_v   = None
    best_dt  = tol + 1
    for i in (idx - 1, idx):
        if 0 <= i < len(sorted_ts):
            dt = abs(sorted_ts[i] - t)
            if dt < best_dt:
                best_dt = dt
                best_v  = sorted_vs[i]
    if best_dt <= tol:
        return best_v
    return None


# -----------------------------------------------------------------------
# Pass 1: collect reference signals and all PT frames
# -----------------------------------------------------------------------
print("Pass 1: collecting frames and reference signals...")

# Reference data per segment: {seg: ([t], [v])}
speed_t   = {s: [] for s in SEGMENTS}
speed_v   = {s: [] for s in SEGMENTS}
torque_t  = {s: [] for s in SEGMENTS}
torque_v  = {s: [] for s in SEGMENTS}

# All frames on PT bus, grouped by (id, dlc), then by segment
# stored as (timestamp, bytes_data)
frames = defaultdict(lambda: defaultdict(list))

frame_count = 0
ref_count   = 0

for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue

    t = frame.timestamp

    # Which segment?
    seg = None
    for s, (t0, t1) in SEGMENTS.items():
        if t0 <= t < t1:
            seg = s
            break
    if seg is None:
        continue

    # Collect reference signals from 0x5A2
    if frame.arbitration_id == SPEED_ID and len(frame.data) >= 6:
        spd_raw = (frame.data[SPEED_B + 1] << 8) | frame.data[SPEED_B]
        spd_val = spd_raw - 32768
        speed_t[seg].append(t)
        speed_v[seg].append(spd_val)

        trq_raw = (frame.data[TORQUE_B + 1] << 8) | frame.data[TORQUE_B]
        trq_val = trq_raw - 32768
        torque_t[seg].append(t)
        torque_v[seg].append(trq_val)
        ref_count += 1

    frames[(frame.arbitration_id, frame.dlc)][seg].append((t, bytes(frame.data)))
    frame_count += 1
    if frame_count % 300000 == 0:
        print(f"  {frame_count:,} frames...")

print(f"Total PT bus frames in segments: {frame_count:,}")
print(f"Unique (ID, DLC): {len(frames)}")
for seg in SEGMENTS:
    print(f"  Speed/torque samples in {seg}: {len(speed_t[seg])}")


# -----------------------------------------------------------------------
# Pass 2: correlation computation
#   byte_results  -- single bytes
#   be16_results  -- BE uint16 pairs
# -----------------------------------------------------------------------
print("\nPass 2: computing correlations...")

byte_results = []
be16_results = []


def compute_candidate(sig_values_per_seg, ref_t_per_seg, ref_v_per_seg):
    """
    sig_values_per_seg: {seg: [(t, sig_val), ...]}
    Returns dict with r_cruise, r_pre, r_post, sd_cruise, sd_pre, sd_post
    or None if cruise segment has insufficient data.
    """
    r_per_seg  = {}
    sd_per_seg = {}

    for seg in SEGMENTS:
        sv = sig_values_per_seg.get(seg, [])
        if not sv:
            continue

        ref_ts = ref_t_per_seg[seg]
        ref_vs = ref_v_per_seg[seg]

        paired_sig = []
        paired_ref = []
        all_sig    = []

        for t, v in sv:
            all_sig.append(v)
            rv = nearest_value(ref_ts, ref_vs, t)
            if rv is not None:
                paired_sig.append(v)
                paired_ref.append(rv)

        r = pearson_r(paired_sig, paired_ref)
        if r is not None:
            r_per_seg[seg] = r
        if len(all_sig) >= 2:
            sd_per_seg[seg] = stdev(all_sig)

    if 'cruise' not in r_per_seg:
        return None
    if 'pre_hybrid' not in r_per_seg and 'post_hybrid' not in r_per_seg:
        return None

    r_manual_vals = [r_per_seg[s] for s in ('pre_hybrid', 'post_hybrid')
                     if s in r_per_seg]
    r_manual_mean = sum(r_manual_vals) / len(r_manual_vals)
    delta_r = r_per_seg['cruise'] - r_manual_mean

    return {
        'r_cruise':      r_per_seg['cruise'],
        'r_pre':         r_per_seg.get('pre_hybrid',  float('nan')),
        'r_post':        r_per_seg.get('post_hybrid', float('nan')),
        'r_manual_mean': r_manual_mean,
        'delta_r':       delta_r,
        'sd_cruise':     sd_per_seg.get('cruise',     float('nan')),
        'sd_pre':        sd_per_seg.get('pre_hybrid', float('nan')),
        'sd_post':       sd_per_seg.get('post_hybrid', float('nan')),
    }


for (aid, dlc), seg_data in frames.items():
    if dlc < 1:
        continue

    # -- Single bytes --
    for b in range(dlc):
        # Build {seg: [(t, raw_byte), ...]}
        sig_by_seg = {}
        for seg, seg_frames in seg_data.items():
            sv = []
            for t, data in seg_frames:
                if b < len(data):
                    sv.append((t, data[b]))  # raw uint8, no centering needed for Pearson
            if sv:
                sig_by_seg[seg] = sv

        # vs torque feedback
        res = compute_candidate(sig_by_seg, torque_t, torque_v)
        if res is not None:
            res.update({'id': aid, 'byte_start': b, 'kind': 'byte'})
            byte_results.append(res)

    # -- BE uint16 pairs --
    if dlc < 2:
        continue
    for b in range(dlc - 1):
        sig_by_seg = {}
        for seg, seg_frames in seg_data.items():
            sv = []
            for t, data in seg_frames:
                if b + 1 < len(data):
                    raw = (data[b] << 8) | data[b + 1]
                    sv.append((t, raw - 32768))
            if sv:
                sig_by_seg[seg] = sv

        res = compute_candidate(sig_by_seg, torque_t, torque_v)
        if res is not None:
            res.update({'id': aid, 'byte_start': b, 'kind': 'be16'})
            be16_results.append(res)

print(f"Single-byte candidates: {len(byte_results)}")
print(f"BE16 pair candidates:   {len(be16_results)}")

# Sort for Section A / B (single bytes) and C / D (BE16)
byte_by_delta  = sorted(byte_results, key=lambda x: abs(x['delta_r']), reverse=True)
byte_setpoints = [r for r in byte_results
                  if not math.isnan(r['sd_cruise'])
                  and 0.01 < r['sd_cruise'] < SETPOINT_STDEV_MAX]
byte_setpoints.sort(key=lambda x: x['sd_cruise'])

be16_by_delta  = sorted(be16_results, key=lambda x: abs(x['delta_r']), reverse=True)
be16_setpoints = [r for r in be16_results
                  if not math.isnan(r['sd_cruise'])
                  and 0.01 < r['sd_cruise'] < SETPOINT_STDEV_MAX]
be16_setpoints.sort(key=lambda x: x['sd_cruise'])


# -----------------------------------------------------------------------
# Section E: plateau detail for top setpoint candidates
# Collect unique values in cruise window for top N from byte + BE16 setpoints
# -----------------------------------------------------------------------
print("\nBuilding Section E plateau detail...")

plateau_candidates = []

# Top N from byte setpoints
for row in byte_setpoints[:PLATEAU_TOP_N]:
    plateau_candidates.append(('byte', row['id'], row['byte_start'], row.get('dlc_hint', None)))
# Top N from be16 setpoints
for row in be16_setpoints[:PLATEAU_TOP_N]:
    plateau_candidates.append(('be16', row['id'], row['byte_start'], None))

# For each candidate, get the cruise-window timeseries and find unique values
plateau_details = []

for (kind, aid, b, _) in plateau_candidates:
    if (aid, None) in frames or True:
        # find matching DLC
        cruise_vals = []
        for (fid, dlc), seg_data in frames.items():
            if fid != aid:
                continue
            if kind == 'byte' and b >= dlc:
                continue
            if kind == 'be16' and b + 1 >= dlc:
                continue
            cruise_frames = seg_data.get('cruise', [])
            for t, data in cruise_frames:
                if kind == 'byte' and b < len(data):
                    cruise_vals.append((t, data[b]))
                elif kind == 'be16' and b + 1 < len(data):
                    raw = (data[b] << 8) | data[b + 1]
                    cruise_vals.append((t, raw - 32768))

        if len(cruise_vals) < 10:
            continue

        cruise_vals.sort()
        vals = [v for _, v in cruise_vals]
        uniq = sorted(set(vals))
        # Find first/last timestamps and value change events
        changes = [(cruise_vals[0][0], cruise_vals[0][1])]
        for i in range(1, len(cruise_vals)):
            if cruise_vals[i][1] != cruise_vals[i-1][1]:
                changes.append((cruise_vals[i][0], cruise_vals[i][1]))

        plateau_details.append({
            'kind': kind,
            'id': aid,
            'b': b,
            'n': len(vals),
            'unique_count': len(uniq),
            'uniq': uniq[:20],  # first 20 unique values
            'min': min(vals),
            'max': max(vals),
            'sd': stdev(vals),
            'changes': changes[:30],   # first 30 value-change events
        })


# -----------------------------------------------------------------------
# Write output
# -----------------------------------------------------------------------
def fmt_r(v):
    return f"{v:+8.4f}" if not math.isnan(v) else "      --"

def fmt_sd(v):
    return f"{v:8.2f}" if not math.isnan(v) else "      --"


HEADER = (
    "Phase 7 -- Per-byte + BE uint16 pair cruise command scan\n"
    "Log:       vtruxevapdrivelog4.log  Bus: 2 (PT)\n"
    "Reference: traction torque feedback = 0x5A2 B4-B5 LE (centered 32768)\n"
    "Segments:  pre_hybrid=t431-720s   cruise=t720-1080s   post_hybrid=t1122-1462s\n"
    f"Min pairs: {MIN_PAIRS}   Setpoint sd_cruise threshold: {SETPOINT_STDEV_MAX}\n\n"
)

COL_HDR_BYTE = (
    f"{'ID':>12s} {'B':>4s} {'r_crs':>9s} {'r_pre':>9s} {'r_pst':>9s} "
    f"{'r_man':>9s} {'|dr|':>9s} {'sd_crs':>8s} {'sd_pre':>8s} {'sd_pst':>8s}\n"
    + '-' * 96 + '\n'
)
COL_HDR_BE16 = (
    f"{'ID':>12s} {'B':>4s}{'  BE16':6s} {'r_crs':>9s} {'r_pre':>9s} {'r_pst':>9s} "
    f"{'r_man':>9s} {'|dr|':>9s} {'sd_crs':>8s} {'sd_pre':>8s} {'sd_pst':>8s}\n"
    + '-' * 102 + '\n'
)


def write_byte_row(f, row):
    f.write(
        f"0x{row['id']:08X} {row['byte_start']:4d} "
        f"{fmt_r(row['r_cruise'])} "
        f"{fmt_r(row['r_pre'])} "
        f"{fmt_r(row['r_post'])} "
        f"{fmt_r(row['r_manual_mean'])} "
        f"{fmt_r(abs(row['delta_r']))} "
        f"{fmt_sd(row['sd_cruise'])} "
        f"{fmt_sd(row['sd_pre'])} "
        f"{fmt_sd(row['sd_post'])}\n"
    )


def write_be16_row(f, row):
    f.write(
        f"0x{row['id']:08X} {row['byte_start']:4d}{'  BE16':6s} "
        f"{fmt_r(row['r_cruise'])} "
        f"{fmt_r(row['r_pre'])} "
        f"{fmt_r(row['r_post'])} "
        f"{fmt_r(row['r_manual_mean'])} "
        f"{fmt_r(abs(row['delta_r']))} "
        f"{fmt_sd(row['sd_cruise'])} "
        f"{fmt_sd(row['sd_pre'])} "
        f"{fmt_sd(row['sd_post'])}\n"
    )


with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write(HEADER)

    # ---- Section A: single bytes, torque cmd search ----
    f.write("=" * 96 + "\n")
    f.write(f"SECTION A: Single bytes, |delta_r vs traction torque feedback| descending (top {TOP_N})\n")
    f.write("Hypothesis A: VCU torque command -- should show high |r_cruise| vs feedback,\n")
    f.write("              low |r_manual|, and high sd_cruise (rapidly varying).\n\n")
    f.write(COL_HDR_BYTE)
    for row in byte_by_delta[:TOP_N]:
        write_byte_row(f, row)

    # ---- Section B: single bytes, setpoint search ----
    f.write("\n" + "=" * 96 + "\n")
    f.write(f"SECTION B: Single bytes, sd_cruise ascending -- setpoint candidates (top {TOP_N})\n")
    f.write(f"Hypothesis B: Inverter setpoint -- near-constant during cruise (sd_cruise < {SETPOINT_STDEV_MAX}),\n")
    f.write("              higher variance outside cruise, discrete steps at t=1103-1108s.\n\n")
    f.write(COL_HDR_BYTE)
    for row in byte_setpoints[:TOP_N]:
        write_byte_row(f, row)

    # ---- Section C: BE16, torque cmd search ----
    f.write("\n" + "=" * 102 + "\n")
    f.write(f"SECTION C: BE uint16 pairs, |delta_r vs traction torque feedback| descending (top {TOP_N})\n")
    f.write("Hypothesis A: VCU torque command in big-endian encoding.\n\n")
    f.write(COL_HDR_BE16)
    for row in be16_by_delta[:TOP_N]:
        write_be16_row(f, row)

    # ---- Section D: BE16, setpoint search ----
    f.write("\n" + "=" * 102 + "\n")
    f.write(f"SECTION D: BE uint16 pairs, sd_cruise ascending -- setpoint candidates (top {TOP_N})\n")
    f.write("Hypothesis B: Inverter speed setpoint in big-endian encoding.\n\n")
    f.write(COL_HDR_BE16)
    for row in be16_setpoints[:TOP_N]:
        write_be16_row(f, row)

    # ---- Section E: plateau detail ----
    f.write("\n" + "=" * 96 + "\n")
    f.write("SECTION E: Plateau detail for top setpoint candidates\n")
    f.write("Shows unique value distribution within cruise window (t=720-1080s).\n")
    f.write("A true setpoint: 1-2 unique values, step at t~1103s (in gap between segments).\n\n")

    for detail in plateau_details:
        kind_tag = "byte " if detail['kind'] == 'byte' else "BE16 "
        f.write(f"  0x{detail['id']:08X}  B{detail['b']}  {kind_tag} "
                f"n={detail['n']:5d}  unique={detail['unique_count']:3d}  "
                f"sd={detail['sd']:.2f}  "
                f"range=[{detail['min']}, {detail['max']}]\n")
        f.write(f"    Unique values: {detail['uniq']}\n")
        if len(detail['changes']) <= 8:
            f.write("    Value changes during cruise:\n")
            for ct, cv in detail['changes']:
                f.write(f"      t={ct:8.3f}s  val={cv}\n")
        else:
            f.write(f"    Value changes (first 8 of {len(detail['changes'])}):\n")
            for ct, cv in detail['changes'][:8]:
                f.write(f"      t={ct:8.3f}s  val={cv}\n")
            f.write(f"      ... ({len(detail['changes'])} total changes)\n")
        f.write("\n")

    f.write("\n--- END ---\n")

print(f"\nOutput: {OUTPUT}")
print(f"Section A: {min(len(byte_by_delta), TOP_N)} single-byte torque-cmd candidates")
print(f"Section B: {min(len(byte_setpoints), TOP_N)} single-byte setpoint candidates")
print(f"Section C: {min(len(be16_by_delta), TOP_N)} BE16 torque-cmd candidates")
print(f"Section D: {min(len(be16_setpoints), TOP_N)} BE16 setpoint candidates")
print(f"Section E: {len(plateau_details)} plateau details")

# Console preview: top 15 from Section B (most actionable)
print("\n--- Section B top 15 (single-byte setpoint candidates, sd_cruise asc) ---")
print(COL_HDR_BYTE, end='')
for row in byte_setpoints[:15]:
    print(
        f"0x{row['id']:08X} {row['byte_start']:4d} "
        f"{fmt_r(row['r_cruise'])} "
        f"{fmt_r(row['r_pre'])} "
        f"{fmt_r(row['r_post'])} "
        f"{fmt_r(row['r_manual_mean'])} "
        f"{fmt_r(abs(row['delta_r']))} "
        f"{fmt_sd(row['sd_cruise'])} "
        f"{fmt_sd(row['sd_pre'])} "
        f"{fmt_sd(row['sd_post'])}"
    )

print("\n--- Section D top 15 (BE16 setpoint candidates, sd_cruise asc) ---")
print(COL_HDR_BE16, end='')
for row in be16_setpoints[:15]:
    print(
        f"0x{row['id']:08X} {row['byte_start']:4d}{'  BE16':6s} "
        f"{fmt_r(row['r_cruise'])} "
        f"{fmt_r(row['r_pre'])} "
        f"{fmt_r(row['r_post'])} "
        f"{fmt_r(row['r_manual_mean'])} "
        f"{fmt_r(abs(row['delta_r']))} "
        f"{fmt_sd(row['sd_cruise'])} "
        f"{fmt_sd(row['sd_pre'])} "
        f"{fmt_sd(row['sd_post'])}"
    )

print("\n--- Section E plateau detail (top entries) ---")
for detail in plateau_details[:10]:
    kind_tag = "byte" if detail['kind'] == 'byte' else "BE16"
    print(
        f"  0x{detail['id']:08X} B{detail['b']} {kind_tag:4s}  "
        f"unique={detail['unique_count']:3d}  sd={detail['sd']:.2f}  "
        f"range=[{detail['min']}, {detail['max']}]  "
        f"values={detail['uniq']}"
    )
