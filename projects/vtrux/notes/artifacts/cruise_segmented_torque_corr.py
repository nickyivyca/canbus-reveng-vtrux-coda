"""
cruise_segmented_torque_corr.py

For every LE uint16 byte pair on the PT bus (Bus 2, vtruxevapdrivelog4.log),
compute Pearson r vs traction motor torque feedback (0x5A2 B4-B5) in three
time segments:
  pre_hybrid:  t=431-720   (generator running, driver on throttle, no cruise)
  cruise:      t=720-1080  (zero-throttle cruise window)
  post_hybrid: t=1122-1462 (generator running, driver on throttle, no cruise)

Sorted by |r_cruise - r_manual_mean| descending.
Signals that score high here correlate with torque feedback specifically during
cruise but not (or differently) during manual hybrid driving.

Output: cruise_segmented_torque_corr.txt
"""

import csv
import sys
import os
import math
import bisect
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

LOG       = 'projects/vtrux/logs/vtruxevapdrivelog4.log'
PT_BUS    = 2
FB_CSV    = 'projects/vtrux/notes/artifacts/cruise_torque_feedback_ts.csv'
OUTPUT    = 'projects/vtrux/notes/artifacts/cruise_segmented_torque_corr.txt'
TOP_N     = 120   # rows to write to file
MIN_PAIRS = 50    # minimum aligned pairs required to report a correlation

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


def nearest_value(sorted_ts, sorted_vs, t, tol=0.06):
    """Return value from sorted feedback list nearest to t, within tol seconds."""
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
# Load torque feedback
# ------------------------------------------------------------------
print("Loading torque feedback...")
fb_all_t, fb_all_v = [], []
with open(FB_CSV) as f:
    for row in csv.DictReader(f):
        fb_all_t.append(float(row['timestamp']))
        fb_all_v.append(int(row['value']) - 32768)

# Split feedback by segment
fb_seg_t = {s: [] for s in SEGMENTS}
fb_seg_v = {s: [] for s in SEGMENTS}
for t, v in zip(fb_all_t, fb_all_v):
    for seg, (t0, t1) in SEGMENTS.items():
        if t0 <= t < t1:
            fb_seg_t[seg].append(t)
            fb_seg_v[seg].append(v)

for seg in SEGMENTS:
    print(f"  Feedback samples in {seg}: {len(fb_seg_t[seg])}")

# ------------------------------------------------------------------
# Parse PT bus frames in segment windows only
# ------------------------------------------------------------------
print(f"\nParsing {LOG} (Bus {PT_BUS} only, segment windows)...")

from canre.parsers import parse_file

# (id, dlc) -> seg -> list of (t, data)
frames = defaultdict(lambda: defaultdict(list))

seg_ranges = list(SEGMENTS.values())
frame_count = 0

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
    frames[(frame.arbitration_id, frame.dlc)][seg].append((t, bytes(frame.data)))
    frame_count += 1
    if frame_count % 200000 == 0:
        print(f"  {frame_count:,} frames collected...")

print(f"Total frames in segments: {frame_count:,}")
print(f"Unique (ID, DLC) pairs: {len(frames)}")

# ------------------------------------------------------------------
# Compute correlations
# ------------------------------------------------------------------
print("\nComputing correlations...")

results = []

for (aid, dlc), seg_data in frames.items():
    if dlc < 2:
        continue

    for b in range(dlc - 1):
        r_per_seg = {}

        for seg in SEGMENTS:
            seg_frames = seg_data.get(seg, [])
            if not seg_frames:
                continue

            paired_sig = []
            paired_fb  = []

            for t, data in seg_frames:
                if b + 1 >= len(data):
                    continue
                sig_val = ((data[b + 1] << 8) | data[b]) - 32768  # LE signed
                fb_val = nearest_value(fb_seg_t[seg], fb_seg_v[seg], t)
                if fb_val is not None:
                    paired_sig.append(sig_val)
                    paired_fb.append(fb_val)

            r = pearson_r(paired_sig, paired_fb)
            if r is not None:
                r_per_seg[seg] = r

        if 'cruise' not in r_per_seg:
            continue
        if 'pre_hybrid' not in r_per_seg and 'post_hybrid' not in r_per_seg:
            continue

        r_manual_vals = [r_per_seg[s] for s in ('pre_hybrid', 'post_hybrid') if s in r_per_seg]
        r_manual_mean = sum(r_manual_vals) / len(r_manual_vals)
        delta = r_per_seg['cruise'] - r_manual_mean

        results.append({
            'id':            aid,
            'byte_start':    b,
            'r_cruise':      r_per_seg['cruise'],
            'r_pre':         r_per_seg.get('pre_hybrid',  float('nan')),
            'r_post':        r_per_seg.get('post_hybrid', float('nan')),
            'r_manual_mean': r_manual_mean,
            'delta':         delta,
        })

# Sort by |delta| descending
results.sort(key=lambda x: abs(x['delta']), reverse=True)

# ------------------------------------------------------------------
# Write output
# ------------------------------------------------------------------
header = (
    "Segmented Pearson r vs traction motor torque feedback (0x5A2 B4-B5)\n"
    "Log: vtruxevapdrivelog4.log  Bus: 2 (PT)  Encoding: LE uint16 - 32768\n"
    "Segments: pre_hybrid=t431-720s, cruise=t720-1080s, post_hybrid=t1122-1462s\n"
    f"Sorted by |r_cruise - r_manual_mean| descending  (top {TOP_N} shown)\n"
    f"Min pairs for inclusion: {MIN_PAIRS}\n\n"
    f"{'ID':10s} {'B_lo':5s} {'r_cruise':9s} {'r_pre':9s} {'r_post':9s} {'r_manual':9s} {'delta':9s}\n"
    + '-' * 67 + '\n'
)

with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write(header)
    for row in results[:TOP_N]:
        pre_str  = f"{row['r_pre']:9.4f}"  if not math.isnan(row['r_pre'])  else "       --"
        post_str = f"{row['r_post']:9.4f}" if not math.isnan(row['r_post']) else "       --"
        f.write(
            f"0x{row['id']:03X}      "
            f"{row['byte_start']:5d} "
            f"{row['r_cruise']:9.4f} "
            f"{pre_str} "
            f"{post_str} "
            f"{row['r_manual_mean']:9.4f} "
            f"{row['delta']:9.4f}\n"
        )

print(f"\nTop 25 by |delta|:")
print(f"{'ID':10s} {'B':5s} {'r_cruise':9s} {'r_pre':9s} {'r_post':9s} {'r_manual':9s} {'delta':9s}")
print('-' * 67)
for row in results[:25]:
    pre_s  = f"{row['r_pre']:9.4f}"  if not math.isnan(row['r_pre'])  else "       --"
    post_s = f"{row['r_post']:9.4f}" if not math.isnan(row['r_post']) else "       --"
    print(
        f"0x{row['id']:03X}      "
        f"{row['byte_start']:5d} "
        f"{row['r_cruise']:9.4f} "
        f"{pre_s} "
        f"{post_s} "
        f"{row['r_manual_mean']:9.4f} "
        f"{row['delta']:9.4f}"
    )

print(f"\nTotal candidates evaluated: {len(results)}")
print(f"Output written to {OUTPUT}")
