"""
cruise_segmented_speed_corr.py

For every LE uint16 byte pair on the PT bus (Bus 2, vtruxevapdrivelog4.log),
compute in three time segments:
  - Pearson r vs motor speed (0x5A2 B2-B3, collected inline)
  - Standard deviation of the candidate signal itself

Segments: pre_hybrid (t=431-720), cruise (t=720-1080), post_hybrid (t=1122-1462)

Output sorted two ways:
  Section A: top 80 by |r_cruise - r_manual_mean| descending (speed-tracking signals)
  Section B: top 80 by stdev_cruise ascending (near-constant during cruise = setpoint candidates)
             filtered: stdev_cruise < 20 counts (exclude trivially-constant zero-only signals)

Signals with stdev_cruise near 0 but stdev_manual >> 0 are cruise setpoint candidates.

Output: cruise_segmented_speed_corr.txt
"""

import sys
import os
import math
import bisect
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

LOG       = 'projects/vtrux/logs/vtruxevapdrivelog4.log'
PT_BUS    = 2
SPEED_ID  = 0x5A2
SPEED_B   = 2   # B2-B3 LE = motor speed
OUTPUT    = 'projects/vtrux/notes/artifacts/cruise_segmented_speed_corr.txt'
TOP_N     = 80
MIN_PAIRS = 50
SETPOINT_STDEV_MAX = 20   # counts; below this = "near-constant during cruise"

SEGMENTS = {
    'pre_hybrid':  (431,  720),
    'cruise':      (720,  1080),
    'post_hybrid': (1122, 1462),
}


def pearson_r(xs, ys):
    n = len(xs)
    if n < MIN_PAIRS:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov  = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / n
    sx   = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy   = math.sqrt(sum((y - my) ** 2 for y in ys) / n)
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
    best_v = None
    best_dt = tol + 1
    for i in (idx - 1, idx):
        if 0 <= i < len(sorted_ts):
            dt = abs(sorted_ts[i] - t)
            if dt < best_dt:
                best_dt = dt
                best_v = sorted_vs[i]
    if best_dt <= tol:
        return best_v
    return None


# ------------------------------------------------------------------
# Parse PT bus frames -- collect motor speed reference inline
# ------------------------------------------------------------------
print("Parsing frames (collecting motor speed reference inline)...")

from canre.parsers import parse_file

# motor speed per segment: {seg: ([t], [v])}
speed_seg_t = {s: [] for s in SEGMENTS}
speed_seg_v = {s: [] for s in SEGMENTS}

# all frames per (id, dlc) per segment
frames = defaultdict(lambda: defaultdict(list))

frame_count = 0
speed_count = 0

for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t = frame.timestamp
    seg = None
    for s, (t0, t1) in SEGMENTS.items():
        if t0 <= t < t1:
            seg = s
            break
    if seg is None:
        continue

    # Collect motor speed reference
    if frame.arbitration_id == SPEED_ID and len(frame.data) >= SPEED_B + 2:
        raw = (frame.data[SPEED_B + 1] << 8) | frame.data[SPEED_B]
        spd = raw - 32768
        speed_seg_t[seg].append(t)
        speed_seg_v[seg].append(spd)
        speed_count += 1

    frames[(frame.arbitration_id, frame.dlc)][seg].append((t, bytes(frame.data)))
    frame_count += 1
    if frame_count % 200000 == 0:
        print(f"  {frame_count:,} frames...")

print(f"Total frames in segments: {frame_count:,}")
print(f"Unique (ID, DLC) pairs:   {len(frames)}")
for seg in SEGMENTS:
    print(f"  Speed samples in {seg}: {len(speed_seg_t[seg])}")

# ------------------------------------------------------------------
# Compute correlations and stdev
# ------------------------------------------------------------------
print("\nComputing correlations and stdev...")

results = []

for (aid, dlc), seg_data in frames.items():
    if dlc < 2:
        continue

    for b in range(dlc - 1):
        r_per_seg   = {}
        sd_per_seg  = {}

        for seg in SEGMENTS:
            seg_frames = seg_data.get(seg, [])
            if not seg_frames:
                continue

            paired_sig   = []
            paired_spd   = []
            sig_all      = []  # all signal values (for stdev, no pairing needed)

            for t, data in seg_frames:
                if b + 1 >= len(data):
                    continue
                sig_val = ((data[b + 1] << 8) | data[b]) - 32768
                sig_all.append(sig_val)
                spd_val = nearest_value(speed_seg_t[seg], speed_seg_v[seg], t)
                if spd_val is not None:
                    paired_sig.append(sig_val)
                    paired_spd.append(spd_val)

            r = pearson_r(paired_sig, paired_spd)
            if r is not None:
                r_per_seg[seg] = r
            if len(sig_all) >= 2:
                sd_per_seg[seg] = stdev(sig_all)

        if 'cruise' not in r_per_seg:
            continue
        if 'pre_hybrid' not in r_per_seg and 'post_hybrid' not in r_per_seg:
            continue

        r_manual_vals = [r_per_seg[s] for s in ('pre_hybrid', 'post_hybrid') if s in r_per_seg]
        r_manual_mean = sum(r_manual_vals) / len(r_manual_vals)
        delta_r = r_per_seg['cruise'] - r_manual_mean

        results.append({
            'id':            aid,
            'byte_start':    b,
            'r_cruise':      r_per_seg['cruise'],
            'r_pre':         r_per_seg.get('pre_hybrid',  float('nan')),
            'r_post':        r_per_seg.get('post_hybrid', float('nan')),
            'r_manual_mean': r_manual_mean,
            'delta_r':       delta_r,
            'sd_cruise':     sd_per_seg.get('cruise',      float('nan')),
            'sd_pre':        sd_per_seg.get('pre_hybrid',  float('nan')),
            'sd_post':       sd_per_seg.get('post_hybrid', float('nan')),
        })

print(f"Total candidates: {len(results)}")

# Section A: sorted by |delta_r| descending
by_delta = sorted(results, key=lambda x: abs(x['delta_r']), reverse=True)

# Section B: sorted by sd_cruise ascending, filtered for near-constant signals
# Exclude perfectly-flat (sd_cruise=0) zero-only trivial signals: require at least some range
setpoint_candidates = [
    r for r in results
    if not math.isnan(r['sd_cruise'])
    and r['sd_cruise'] < SETPOINT_STDEV_MAX
    and r['sd_cruise'] > 0.01   # exclude exactly-constant signals
]
by_stdev = sorted(setpoint_candidates, key=lambda x: x['sd_cruise'])

# ------------------------------------------------------------------
# Write output
# ------------------------------------------------------------------
def fmt_r(v):
    return f"{v:9.4f}" if not math.isnan(v) else "       --"

def fmt_sd(v):
    return f"{v:9.2f}" if not math.isnan(v) else "       --"


header_common = (
    "Log: vtruxevapdrivelog4.log  Bus: 2 (PT)  Encoding: LE uint16 - 32768\n"
    "Reference: motor speed (0x5A2 B2-B3, collected inline)\n"
    "Segments: pre_hybrid=t431-720s, cruise=t720-1080s, post_hybrid=t1122-1462s\n"
    f"Min pairs for inclusion: {MIN_PAIRS}\n\n"
)

col_hdr = (
    f"{'ID':12s} {'B':4s} {'r_crs':9s} {'r_pre':9s} {'r_pst':9s} "
    f"{'r_man':9s} {'dr':9s} {'sd_crs':9s} {'sd_pre':9s} {'sd_pst':9s}\n"
    + '-' * 96 + '\n'
)

with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write("Segmented Pearson r vs motor speed (0x5A2 B2-B3) + candidate signal stdev\n")
    f.write(header_common)

    f.write(f"=== SECTION A: top {TOP_N} by |delta_r = r_cruise - r_manual_mean| descending ===\n")
    f.write("(Speed-tracking signals; motor speed echoes dominate top rows)\n\n")
    f.write(col_hdr)
    for row in by_delta[:TOP_N]:
        f.write(
            f"0x{row['id']:06X}     "
            f"{row['byte_start']:4d} "
            f"{fmt_r(row['r_cruise'])} "
            f"{fmt_r(row['r_pre'])} "
            f"{fmt_r(row['r_post'])} "
            f"{fmt_r(row['r_manual_mean'])} "
            f"{fmt_r(row['delta_r'])} "
            f"{fmt_sd(row['sd_cruise'])} "
            f"{fmt_sd(row['sd_pre'])} "
            f"{fmt_sd(row['sd_post'])}\n"
        )

    f.write(f"\n\n=== SECTION B: top {TOP_N} by sd_cruise ascending (setpoint candidates) ===\n")
    f.write(f"(Near-constant during cruise; sd_cruise < {SETPOINT_STDEV_MAX}; excludes perfectly-constant)\n")
    f.write("Setpoint candidates show: low sd_cruise, high sd_pre / sd_post, step at t=1103-1108\n\n")
    f.write(col_hdr)
    for row in by_stdev[:TOP_N]:
        f.write(
            f"0x{row['id']:06X}     "
            f"{row['byte_start']:4d} "
            f"{fmt_r(row['r_cruise'])} "
            f"{fmt_r(row['r_pre'])} "
            f"{fmt_r(row['r_post'])} "
            f"{fmt_r(row['r_manual_mean'])} "
            f"{fmt_r(row['delta_r'])} "
            f"{fmt_sd(row['sd_cruise'])} "
            f"{fmt_sd(row['sd_pre'])} "
            f"{fmt_sd(row['sd_post'])}\n"
        )

print(f"\nOutput written to {OUTPUT}")
print(f"Section A: {min(len(by_delta), TOP_N)} rows  |  Section B (setpoint candidates): {min(len(by_stdev), TOP_N)} rows")

# Print Section B top 20 to console
print(f"\nSection B -- top 20 setpoint candidates (sd_cruise ascending):")
print(col_hdr, end='')
for row in by_stdev[:20]:
    print(
        f"0x{row['id']:06X}     "
        f"{row['byte_start']:4d} "
        f"{fmt_r(row['r_cruise'])} "
        f"{fmt_r(row['r_pre'])} "
        f"{fmt_r(row['r_post'])} "
        f"{fmt_r(row['r_manual_mean'])} "
        f"{fmt_r(row['delta_r'])} "
        f"{fmt_sd(row['sd_cruise'])} "
        f"{fmt_sd(row['sd_pre'])} "
        f"{fmt_sd(row['sd_post'])}"
    )

print(f"\nTotal candidates evaluated: {len(results)}")
