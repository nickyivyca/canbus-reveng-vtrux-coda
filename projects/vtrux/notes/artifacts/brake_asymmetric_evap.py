#!/usr/bin/env python3
"""
Event-based brake booster pressure signal search -- evap drive log variant.
vtruxanotherevaplogpart1.log:
  Bus 3 = PT bus  (0x592, 0x051, 0x390)
  Bus 1 = Vehicle bus  (0x1E5, 0x500, 0x2F9)
  Bus 2 = OBD bus  (0x040)

Uses bisect for O(log n) nearest-timestamp lookups instead of O(n) min().
"""
import sys, math, bisect
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from canre.parsers import parse_file

LOG     = "projects/vtrux/logs/vtruxanotherevaplogpart1.log"
PT_BUS  = 3
GM_BUS1 = 1   # Vehicle / unfiltered
GM_BUS2 = 2   # OBD

PEDAL_ID        = 0x592
PEDAL_PRESS_THR = 200    # 16-bit raw; idle floor is ~0-156, genuine presses well above this
PEDAL_MIN_PEAK  = 500    # 16-bit raw; catches both light driveway presses (~250) and hard braking (~4700)

MIN_FRAMES      = 40
RECOVERY_WINDOW = 5.0
RECOVERY_STEPS  = 5

# ---- collect data ----
print("Parsing ...", flush=True)
bus_data = defaultdict(lambda: defaultdict(list))
for frame in parse_file(LOG):
    bus_data[frame.bus][frame.arbitration_id].append(
        (frame.timestamp, bytes(frame.data))
    )
print("Parse complete.", flush=True)

# ---- fast nearest lookup using bisect ----
def nearest_at(ref_t, times, vals, max_dt=0.2):
    """O(log n) nearest value in a sorted (times, vals) pair."""
    if not times:
        return None
    i = bisect.bisect_left(times, ref_t)
    best_i = None
    best_d = max_dt + 1
    for j in [i - 1, i]:
        if 0 <= j < len(times):
            d = abs(times[j] - ref_t)
            if d < best_d:
                best_d = d
                best_i = j
    return vals[best_i] if best_i is not None and best_d <= max_dt else None

def values_in_window(start_t, end_t, times, vals):
    lo = bisect.bisect_left(times, start_t)
    hi = bisect.bisect_right(times, end_t)
    return list(zip(times[lo:hi], vals[lo:hi]))

# ---- build pedal timeseries (16-bit B4-B5 LE to avoid B4 overflow) ----
raw_pedal = sorted(
    (t, d[4] | d[5] << 8)
    for t, d in bus_data[PT_BUS].get(PEDAL_ID, [])
    if len(d) > 5
)
ped_times = [x[0] for x in raw_pedal]
ped_vals  = [x[1] for x in raw_pedal]

# ---- find brake press/release events ----
press_events   = []   # (peak_t, pre_t, peak_v, pre_v)
release_events = []   # (release_t,)

i = 0
while i < len(ped_times):
    v = ped_vals[i]
    if v >= PEDAL_PRESS_THR:
        j = i
        while j < len(ped_times) and ped_vals[j] >= PEDAL_PRESS_THR:
            j += 1
        segment_v = ped_vals[i:j]
        pi = segment_v.index(max(segment_v))
        peak_t, peak_v = ped_times[i + pi], segment_v[pi]
        if peak_v >= PEDAL_MIN_PEAK:
            pre_idx = i - 1
            while pre_idx >= 0 and ped_vals[pre_idx] >= PEDAL_PRESS_THR:
                pre_idx -= 1
            if pre_idx >= 0:
                press_events.append((peak_t, ped_times[pre_idx], peak_v, ped_vals[pre_idx]))
            # find release (pedal settles to ~0)
            k = j
            while k < len(ped_times) and ped_vals[k] > PEDAL_PRESS_THR:
                k += 1
            if k < len(ped_times):
                release_events.append((ped_times[k],))
        i = j
    else:
        i += 1

print(f"Press events: {len(press_events)}", flush=True)
print(f"Release events: {len(release_events)}", flush=True)

# ---- scoring ----
def score_byte(times, vals):
    if len(times) < MIN_FRAMES:
        return 0, 0, 0, 0, 0

    press_deltas = []
    for peak_t, pre_t, peak_v, pre_pv in press_events:
        pre_sig = nearest_at(pre_t, times, vals)
        at_sig  = nearest_at(peak_t, times, vals)
        if pre_sig is not None and at_sig is not None:
            press_deltas.append(at_sig - pre_sig)

    if not press_deltas:
        return 0, 0, 0, 0, 0

    pos = sum(1 for d in press_deltas if d > 0)
    neg = sum(1 for d in press_deltas if d < 0)
    n_press = len(press_deltas)
    dominant = max(pos, neg)
    press_dir = +1 if pos >= neg else -1
    press_consistency = dominant / n_press

    recovery_scores = []
    for (rel_t,) in release_events:
        # find associated press (last press before release)
        assoc_press = None
        for pe in press_events:
            if pe[0] <= rel_t + 0.5:
                assoc_press = pe
        if assoc_press is None:
            continue
        baseline_sig = nearest_at(assoc_press[1], times, vals, max_dt=0.5)
        if baseline_sig is None:
            continue

        rec_pts = values_in_window(rel_t, rel_t + RECOVERY_WINDOW, times, vals)
        if len(rec_pts) < 2:
            continue

        first_v = rec_pts[0][1]
        last_v  = rec_pts[-1][1]
        d_first = first_v - baseline_sig
        d_last  = last_v  - baseline_sig
        if abs(d_first) < 2:
            continue

        moved_toward = abs(d_last) < abs(d_first)
        step = max(1, len(rec_pts) // RECOVERY_STEPS)
        sampled = rec_pts[::step]
        dists = [abs(v - baseline_sig) for _, v in sampled]
        monotone_count = sum(1 for a, b in zip(dists, dists[1:]) if b <= a + 2)
        monotone_frac = monotone_count / max(1, len(dists) - 1)
        recovery_scores.append(1.0 if moved_toward and monotone_frac >= 0.6 else 0.0)

    n_release = len(recovery_scores)
    recovery_score = sum(recovery_scores) / n_release if n_release > 0 else 0
    return press_consistency, press_dir, recovery_score, n_press, n_release


def pearson(ref_times, ref_vals, cand_times, cand_vals):
    cx, cy = [], []
    for rt, rv in zip(ref_times, ref_vals):
        cv = nearest_at(rt, cand_times, cand_vals, max_dt=0.15)
        if cv is not None:
            cx.append(rv)
            cy.append(cv)
    n = len(cx)
    if n < MIN_FRAMES:
        return 0.0
    mx = sum(cx) / n
    my = sum(cy) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(cx, cy))
    sx = math.sqrt(max(1e-12, sum((a - mx) ** 2 for a in cx)))
    sy = math.sqrt(max(1e-12, sum((b - my) ** 2 for b in cy)))
    return sxy / (sx * sy)


# ---- EBCM pressure reference ----
raw_ebcm = sorted(
    (t, d[5])
    for t, d in bus_data[GM_BUS1].get(0x2F9, [])
    if len(d) > 5
)
ebcm_times = [x[0] for x in raw_ebcm]
ebcm_vals  = [x[1] for x in raw_ebcm]

# ---- scan all buses ----
all_results = []
print("Scoring ...", flush=True)

for bus_num in [PT_BUS, GM_BUS1, GM_BUS2]:
    for can_id, entries in sorted(bus_data[bus_num].items()):
        if len(entries) < MIN_FRAMES:
            continue
        dlc = max(len(d) for _, d in entries)
        for bi in range(dlc):
            raw = sorted((t, d[bi]) for t, d in entries if len(d) > bi)
            if len(raw) < MIN_FRAMES:
                continue
            if len(set(v for _, v in raw)) < 3:
                continue  # constant
            times = [x[0] for x in raw]
            vals  = [x[1] for x in raw]

            pc, pdir, rc, np_, nr = score_byte(times, vals)
            r_ped  = pearson(ped_times, ped_vals, times, vals)
            r_ebcm = pearson(ebcm_times, ebcm_vals, times, vals) if len(ebcm_times) >= MIN_FRAMES else 0.0

            if pc >= 0.55 or rc >= 0.50 or abs(r_ped) >= 0.25 or abs(r_ebcm) >= 0.30:
                all_results.append({
                    'bus': bus_num,
                    'id': can_id,
                    'byte': bi,
                    'label': f"Bus{bus_num} 0x{can_id:03X} B{bi}",
                    'press_cons': pc,
                    'press_dir': pdir,
                    'recovery': rc,
                    'pearson_ped': r_ped,
                    'pearson_ebcm': r_ebcm,
                    'n_press': np_,
                    'n_rel': nr,
                    'vmin': min(vals),
                    'vmax': max(vals),
                })

all_results.sort(key=lambda x: -(
    x['press_cons'] * 0.4 + x['recovery'] * 0.4
    + abs(x['pearson_ped']) * 0.1 + abs(x['pearson_ebcm']) * 0.1
))

print()
print("=== Event-based + Pearson scan (sign-agnostic) ===")
print(f"{'Label':<28} {'PrCons':>7} {'Dir':>4} {'RecSc':>6} {'Pr_ped':>8} {'Pr_ebcm':>8} {'np':>4} {'nr':>4} Range")
print("-" * 95)
for r in all_results[:70]:
    dir_s = '+' if r['press_dir'] > 0 else '-'
    print(f"{r['label']:<28} {r['press_cons']:7.3f} {dir_s:>4} {r['recovery']:6.3f} "
          f"{r['pearson_ped']:8.4f} {r['pearson_ebcm']:8.4f} "
          f"{r['n_press']:4} {r['n_rel']:4}  {r['vmin']}-{r['vmax']}")
