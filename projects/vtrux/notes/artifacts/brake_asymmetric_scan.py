#!/usr/bin/env python3
"""
Event-based brake booster pressure signal search.

Logic (sign-agnostic):
  1. Find brake PRESS events: pedal crosses UP through a threshold
  2. For each press event, sample the candidate signal just before and during peak press
  3. Find brake RELEASE events: pedal drops back to zero
  4. For each release, measure the recovery curve: does the signal return
     monotonically toward the pre-press baseline over the following ~5 seconds?

Scores each byte on:
  - press_consistency: fraction of press events where signal moves in the dominant direction
  - recovery_score:    fraction of release events with monotonic return to baseline
  - Both must be high to flag as a candidate

Also runs a lower-threshold Pearson sweep (|r| >= 0.25) for completeness.
"""
import sys, math
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from canre.parsers import parse_file

LOG    = "projects/vtrux/logs/movingaroundindriveway.log"
PT_BUS = 3
GM_BUS = 2

PEDAL_ID        = 0x592
PEDAL_BYTE      = 4          # brake pedal raw byte
PEDAL_PRESS_THR = 30         # raw counts above which = braking
PEDAL_MIN_PEAK  = 60         # minimum peak to count as real press event

MIN_FRAMES      = 40
RECOVERY_WINDOW = 5.0        # seconds after release to check recovery
RECOVERY_STEPS  = 5          # number of samples to check in recovery window

# ---- collect data ----
print(f"Parsing {LOG} ...")
bus_data = defaultdict(lambda: defaultdict(list))
for frame in parse_file(LOG):
    bus_data[frame.bus][frame.arbitration_id].append(
        (frame.timestamp, bytes(frame.data))
    )
print("Parse complete.")

def get_ts(bus, can_id, *byte_idx):
    entries = bus_data[bus].get(can_id, [])
    result = []
    for t, d in entries:
        if all(bi < len(d) for bi in byte_idx):
            vals = tuple(d[bi] for bi in byte_idx)
            result.append((t, vals[0] if len(vals)==1 else vals))
    return result

def nearest_before(ref_t, src, max_dt=0.3):
    """Nearest value in src at or before ref_t."""
    best = None
    for t, v in src:
        if t <= ref_t and (best is None or t > best[0]):
            best = (t, v)
        if t > ref_t + max_dt:
            break
    return best

def nearest_at(ref_t, src, max_dt=0.2):
    if not src:
        return None
    best = min(src, key=lambda x: abs(x[0]-ref_t))
    if abs(best[0]-ref_t) <= max_dt:
        return best[1]
    return None

def values_in_window(start_t, end_t, src):
    return [(t,v) for t,v in src if start_t <= t <= end_t]

# ---- find brake events ----
pedal_ts = get_ts(PT_BUS, PEDAL_ID, PEDAL_BYTE)
pedal_ts.sort()

press_events  = []  # (peak_time, pre_time, peak_val, pre_val)
release_events = [] # (release_time, pre_press_val)

i = 0
while i < len(pedal_ts):
    t, v = pedal_ts[i]
    # Look for rising edge through threshold
    if v >= PEDAL_PRESS_THR:
        # Find the peak of this press
        j = i
        while j < len(pedal_ts) and pedal_ts[j][1] >= PEDAL_PRESS_THR:
            j += 1
        # Window: i..j is the pressed window
        segment = pedal_ts[i:j]
        peak_t, peak_v = max(segment, key=lambda x: x[1])
        if peak_v >= PEDAL_MIN_PEAK:
            # pre-press: last sample before crossing threshold
            pre_idx = i - 1
            while pre_idx >= 0 and pedal_ts[pre_idx][1] >= PEDAL_PRESS_THR:
                pre_idx -= 1
            if pre_idx >= 0:
                pre_t, pre_v = pedal_ts[pre_idx]
                press_events.append((peak_t, pre_t, peak_v, pre_v))
            # release event: first sample after press window where pedal is near zero
            if j < len(pedal_ts):
                rel_t, rel_v = pedal_ts[j]
                # find where it actually settles to zero
                k = j
                while k < len(pedal_ts) and pedal_ts[k][1] > 5:
                    k += 1
                if k < len(pedal_ts):
                    release_events.append((pedal_ts[k][0],))  # time of return to zero
        i = j
    else:
        i += 1

print(f"Press events detected: {len(press_events)}")
for pe in press_events:
    print(f"  peak_t={pe[0]:.2f}s  peak_v={pe[2]}  pre_v={pe[3]}")
print(f"Release events detected: {len(release_events)}")
print()

# ---- event-based scoring ----
def score_byte(ts_list):
    """
    Score a (time, value) series for brake booster asymmetric behavior.
    Returns (press_score, press_dir, recovery_score, n_press, n_release)
    press_dir: +1 = rises on press, -1 = drops on press
    """
    if len(ts_list) < MIN_FRAMES:
        return 0, 0, 0, 0, 0

    # --- press scoring ---
    press_deltas = []
    for peak_t, pre_t, peak_v, pre_pv in press_events:
        pre_sig = nearest_at(pre_t, ts_list)
        at_sig  = nearest_at(peak_t, ts_list)
        if pre_sig is not None and at_sig is not None:
            press_deltas.append(at_sig - pre_sig)

    if not press_deltas:
        return 0, 0, 0, 0, 0

    pos = sum(1 for d in press_deltas if d > 0)
    neg = sum(1 for d in press_deltas if d < 0)
    n_press = len(press_deltas)
    dominant = pos if pos >= neg else neg
    press_dir = +1 if pos >= neg else -1
    press_consistency = dominant / n_press if n_press > 0 else 0

    # --- recovery scoring ---
    # After release, does signal return toward pre-press baseline?
    # "Return" = moves in direction opposite to press_dir
    recovery_scores = []
    for (rel_t,) in release_events:
        # find the pre-press baseline for this event
        # use median of signal values in 2s window BEFORE the nearest press event
        # approximate: use value just before the associated press
        assoc_press = None
        for pe in press_events:
            if pe[0] <= rel_t + 0.5:
                assoc_press = pe
        if assoc_press is None:
            continue
        pre_t_press = assoc_press[1]
        baseline_sig = nearest_at(pre_t_press, ts_list, max_dt=0.5)
        if baseline_sig is None:
            continue

        # Sample signal at RECOVERY_STEPS points in recovery window
        rec_pts = values_in_window(rel_t, rel_t + RECOVERY_WINDOW, ts_list)
        if len(rec_pts) < 2:
            continue

        # Check: is the last value closer to baseline than the first?
        first_v = rec_pts[0][1]
        last_v  = rec_pts[-1][1]
        # Toward baseline = (last-baseline) < (first-baseline) in absolute terms
        # but sign-agnostic: check if last is on the same side as baseline vs first
        d_first = first_v - baseline_sig
        d_last  = last_v  - baseline_sig
        # Recovery: signal moving toward baseline = |d_last| < |d_first|
        if abs(d_first) < 2:  # already at baseline, skip
            continue
        moved_toward = abs(d_last) < abs(d_first)
        # Also check monotonicity: sample at intermediate points
        step = max(1, len(rec_pts)//RECOVERY_STEPS)
        sampled = rec_pts[::step]
        dists = [abs(v - baseline_sig) for _, v in sampled]
        # monotonic decrease in distance = recovery curve
        monotone_count = sum(1 for a,b in zip(dists, dists[1:]) if b <= a + 2)
        monotone_frac = monotone_count / max(1, len(dists)-1)
        recovery_scores.append(1.0 if moved_toward and monotone_frac >= 0.6 else 0.0)

    n_release = len(recovery_scores)
    recovery_score = sum(recovery_scores) / n_release if n_release > 0 else 0

    return press_consistency, press_dir, recovery_score, n_press, n_release


# ---- Pearson helper (lower threshold) ----
def pearson_ref(ref_ts, ref_vals, cand_ts_vals):
    def nearest(rt, seq, max_dt=0.15):
        if not seq: return None
        ci = 0
        while ci < len(seq)-1 and abs(seq[ci+1][0]-rt) < abs(seq[ci][0]-rt): ci+=1
        return seq[ci][1] if abs(seq[ci][0]-rt) <= max_dt else None

    cx, cy = [], []
    for rt, rv in zip(ref_ts, ref_vals):
        cv = nearest(rt, cand_ts_vals)
        if cv is not None:
            cx.append(rv)
            cy.append(cv)
    if len(cx) < MIN_FRAMES: return 0.0
    n=len(cx); mx=sum(cx)/n; my=sum(cy)/n
    sxy=sum((a-mx)*(b-my) for a,b in zip(cx,cy))
    sx=math.sqrt(max(1e-12,sum((a-mx)**2 for a in cx)))
    sy=math.sqrt(max(1e-12,sum((b-my)**2 for b in cy)))
    return sxy/(sx*sy)

ref_pedal_ts = [(t,v) for t,v in pedal_ts]
ref_t_list  = [t for t,v in ref_pedal_ts]
ref_v_list  = [v for t,v in ref_pedal_ts]

# ---- scan all buses ----
all_results = []

for bus_num in [PT_BUS, GM_BUS]:
    for can_id, entries in sorted(bus_data[bus_num].items()):
        if len(entries) < MIN_FRAMES:
            continue
        dlc = max(len(d) for _,d in entries)
        for bi in range(dlc):
            ts_b = [(t, d[bi]) for t,d in entries if len(d)>bi]
            if len(set(v for _,v in ts_b)) < 3:
                continue  # constant
            pc, pdir, rc, np, nr = score_byte(ts_b)
            r = pearson_ref(ref_t_list, ref_v_list, ts_b)
            if pc >= 0.55 or rc >= 0.50 or abs(r) >= 0.25:
                all_results.append({
                    'bus': bus_num,
                    'id': can_id,
                    'byte': bi,
                    'label': f"Bus{bus_num} 0x{can_id:03X} B{bi}",
                    'press_cons': pc,
                    'press_dir': pdir,
                    'recovery': rc,
                    'pearson': r,
                    'n_press': np,
                    'n_rel': nr,
                    'range': f"{min(v for _,v in ts_b)}-{max(v for _,v in ts_b)}",
                })

# Sort by combined score
all_results.sort(key=lambda x: -(x['press_cons']*0.4 + x['recovery']*0.4 + abs(x['pearson'])*0.2))

print("=== Event-based + Pearson scan (sign-agnostic) ===")
print(f"{'Label':<28} {'PrCons':>7} {'Dir':>4} {'RecSc':>6} {'Pearson':>8} {'np':>4} {'nr':>4} {'Range'}")
print("-"*85)
for r in all_results[:60]:
    dir_s = '+' if r['press_dir'] > 0 else '-'
    print(f"{r['label']:<28} {r['press_cons']:7.3f} {dir_s:>4} {r['recovery']:6.3f} {r['pearson']:8.4f} "
          f"{r['n_press']:4} {r['n_rel']:4}  {r['range']}")
