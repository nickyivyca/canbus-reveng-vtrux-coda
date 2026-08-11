"""
cruise_phase7_byte_scan.py  --  Phase 7 cruise control command search

Scans all PT bus signals using two encodings:
  - uint8  (every individual byte)
  - BE uint16 (big-endian pair: B[n]<<8 | B[n+1])

Two references (collected inline from PT bus):
  - Motor speed:          0x5A2 B2-B3 LE uint16 - 32768
  - Traction torque fdbk: 0x5A2 B4-B5 LE uint16 - 32768

Three segments:
  pre_hybrid  t=431-720s
  cruise      t=720-1080s
  post_hybrid t=1122-1462s

Four output sections:
  A: per-byte  vs motor speed,   sorted by |delta_r| (tracking)
  B: per-byte  vs motor speed,   sorted by sd_cruise asc (setpoint candidates)
  C: per-byte  vs torque fdbk,   sorted by |delta_r| (tracking)
  D: per-byte  vs torque fdbk,   sorted by sd_cruise asc (setpoint/cmd candidates)
  E: BE16 pair vs motor speed,   sorted by |delta_r|
  F: BE16 pair vs torque fdbk,   sorted by |delta_r|

Output: cruise_phase7_byte_scan.txt
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
SPEED_B_LO = 2   # B2-B3 LE = motor speed
TORQ_B_LO  = 4   # B4-B5 LE = traction torque feedback
OUTPUT    = 'projects/vtrux/notes/artifacts/cruise_phase7_byte_scan.txt'
TOP_N     = 80
MIN_PAIRS = 50
SETPOINT_STDEV_MAX = 20   # counts; below this = near-constant during cruise

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
    idx = bisect.bisect_left(sorted_ts, t)
    best_v, best_dt = None, tol + 1
    for i in (idx - 1, idx):
        if 0 <= i < len(sorted_ts):
            dt = abs(sorted_ts[i] - t)
            if dt < best_dt:
                best_dt, best_v = dt, sorted_vs[i]
    return best_v if best_dt <= tol else None


# ------------------------------------------------------------------
# Parse PT bus frames
# ------------------------------------------------------------------
print("Parsing frames...")

from canre.parsers import parse_file

# Reference signals per segment
speed_seg_t  = {s: [] for s in SEGMENTS}
speed_seg_v  = {s: [] for s in SEGMENTS}
torq_seg_t   = {s: [] for s in SEGMENTS}
torq_seg_v   = {s: [] for s in SEGMENTS}

# Raw frames: {(aid, dlc): {seg: [(t, data_bytes)]}}
frames = defaultdict(lambda: defaultdict(list))

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

    if frame.arbitration_id == SPEED_ID and len(frame.data) >= TORQ_B_LO + 2:
        spd = ((frame.data[SPEED_B_LO + 1] << 8) | frame.data[SPEED_B_LO]) - 32768
        trq = ((frame.data[TORQ_B_LO  + 1] << 8) | frame.data[TORQ_B_LO ]) - 32768
        speed_seg_t[seg].append(t);  speed_seg_v[seg].append(spd)
        torq_seg_t[seg].append(t);   torq_seg_v[seg].append(trq)

    frames[(frame.arbitration_id, frame.dlc)][seg].append((t, bytes(frame.data)))
    frame_count += 1
    if frame_count % 200000 == 0:
        print(f"  {frame_count:,} frames...")

print(f"Total frames in segments: {frame_count:,}")
print(f"Unique (ID, DLC) pairs:   {len(frames)}")
for seg in SEGMENTS:
    print(f"  Speed/torq samples in {seg}: {len(speed_seg_t[seg])}")


# ------------------------------------------------------------------
# Compute correlations for one encoding type
# ------------------------------------------------------------------
def compute_results(encoding):
    """
    encoding: 'uint8' or 'be16'
    Returns list of result dicts with speed and torque r values.
    """
    results = []

    for (aid, dlc), seg_data in frames.items():
        if encoding == 'uint8':
            byte_range = range(dlc)
            n_bytes = 1
        else:  # be16
            if dlc < 2:
                continue
            byte_range = range(dlc - 1)
            n_bytes = 2

        for b in byte_range:
            # Per-segment accumulators
            r_spd = {}; r_trq = {}
            sd_seg = {}

            for seg in SEGMENTS:
                seg_frames = seg_data.get(seg, [])
                if not seg_frames:
                    continue

                paired_spd_sig = []; paired_spd_ref = []
                paired_trq_sig = []; paired_trq_ref = []
                sig_all = []

                for t, data in seg_frames:
                    if encoding == 'uint8':
                        if b >= len(data):
                            continue
                        sig_val = data[b]
                    else:  # be16: high byte first
                        if b + 1 >= len(data):
                            continue
                        sig_val = (data[b] << 8) | data[b + 1]
                        sig_val -= 32768

                    sig_all.append(sig_val)

                    sv = nearest_value(speed_seg_t[seg], speed_seg_v[seg], t)
                    if sv is not None:
                        paired_spd_sig.append(sig_val)
                        paired_spd_ref.append(sv)

                    tv = nearest_value(torq_seg_t[seg], torq_seg_v[seg], t)
                    if tv is not None:
                        paired_trq_sig.append(sig_val)
                        paired_trq_ref.append(tv)

                r = pearson_r(paired_spd_sig, paired_spd_ref)
                if r is not None:
                    r_spd[seg] = r

                r = pearson_r(paired_trq_sig, paired_trq_ref)
                if r is not None:
                    r_trq[seg] = r

                if len(sig_all) >= 2:
                    sd_seg[seg] = stdev(sig_all)

            # Require cruise + at least one manual segment for both refs
            if 'cruise' not in r_spd and 'cruise' not in r_trq:
                continue

            def delta_and_manual(r_dict):
                if 'cruise' not in r_dict:
                    return float('nan'), float('nan')
                manual_vals = [r_dict[s] for s in ('pre_hybrid', 'post_hybrid') if s in r_dict]
                if not manual_vals:
                    return float('nan'), float('nan')
                r_man = sum(manual_vals) / len(manual_vals)
                return r_dict['cruise'] - r_man, r_man

            delta_spd, r_man_spd = delta_and_manual(r_spd)
            delta_trq, r_man_trq = delta_and_manual(r_trq)

            results.append({
                'id':        aid,
                'byte':      b,
                'enc':       encoding,
                # speed
                'rs_crs':    r_spd.get('cruise',      float('nan')),
                'rs_pre':    r_spd.get('pre_hybrid',  float('nan')),
                'rs_pst':    r_spd.get('post_hybrid', float('nan')),
                'rs_man':    r_man_spd,
                'ds':        delta_spd,
                # torque
                'rt_crs':    r_trq.get('cruise',      float('nan')),
                'rt_pre':    r_trq.get('pre_hybrid',  float('nan')),
                'rt_pst':    r_trq.get('post_hybrid', float('nan')),
                'rt_man':    r_man_trq,
                'dt':        delta_trq,
                # stdev
                'sd_crs':    sd_seg.get('cruise',      float('nan')),
                'sd_pre':    sd_seg.get('pre_hybrid',  float('nan')),
                'sd_pst':    sd_seg.get('post_hybrid', float('nan')),
            })

    return results


print("\nComputing per-byte correlations...")
byte_results = compute_results('uint8')
print(f"  Byte candidates: {len(byte_results)}")

print("Computing BE16 correlations...")
be16_results = compute_results('be16')
print(f"  BE16 candidates: {len(be16_results)}")


# ------------------------------------------------------------------
# Write output
# ------------------------------------------------------------------
def fmt_r(v):
    return f"{v:8.4f}" if not math.isnan(v) else "      --"

def fmt_sd(v):
    return f"{v:8.2f}" if not math.isnan(v) else "      --"

def write_section_speed(f, rows, title, subtitle, by_stdev=False):
    f.write(f"\n=== {title} ===\n{subtitle}\n\n")
    hdr = (f"{'ID':10s} {'B':3s} {'rs_crs':>8s} {'rs_pre':>8s} {'rs_pst':>8s} "
           f"{'rs_man':>8s} {'ds':>8s} {'sd_crs':>8s} {'sd_pre':>8s} {'sd_pst':>8s}\n"
           + '-' * 84 + '\n')
    f.write(hdr)
    for row in rows[:TOP_N]:
        f.write(
            f"0x{row['id']:06X}  {row['byte']:3d} "
            f"{fmt_r(row['rs_crs'])} {fmt_r(row['rs_pre'])} {fmt_r(row['rs_pst'])} "
            f"{fmt_r(row['rs_man'])} {fmt_r(row['ds'])} "
            f"{fmt_sd(row['sd_crs'])} {fmt_sd(row['sd_pre'])} {fmt_sd(row['sd_pst'])}\n"
        )

def write_section_torque(f, rows, title, subtitle):
    f.write(f"\n=== {title} ===\n{subtitle}\n\n")
    hdr = (f"{'ID':10s} {'B':3s} {'rt_crs':>8s} {'rt_pre':>8s} {'rt_pst':>8s} "
           f"{'rt_man':>8s} {'dt':>8s} {'sd_crs':>8s} {'sd_pre':>8s} {'sd_pst':>8s}\n"
           + '-' * 84 + '\n')
    f.write(hdr)
    for row in rows[:TOP_N]:
        f.write(
            f"0x{row['id']:06X}  {row['byte']:3d} "
            f"{fmt_r(row['rt_crs'])} {fmt_r(row['rt_pre'])} {fmt_r(row['rt_pst'])} "
            f"{fmt_r(row['rt_man'])} {fmt_r(row['dt'])} "
            f"{fmt_sd(row['sd_crs'])} {fmt_sd(row['sd_pre'])} {fmt_sd(row['sd_pst'])}\n"
        )

def has_val(v):
    return not math.isnan(v)

with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write("cruise_phase7_byte_scan.py  --  Phase 7 cruise command search\n")
    f.write("Log: vtruxevapdrivelog4.log  Bus: 2 (PT)\n")
    f.write("Encodings: uint8 (individual bytes) and BE uint16 (big-endian pairs)\n")
    f.write("References: motor speed (0x5A2 B2-B3 LE), traction torque fdbk (0x5A2 B4-B5 LE)\n")
    f.write("Segments: pre_hybrid=t431-720s, cruise=t720-1080s, post_hybrid=t1122-1462s\n")
    f.write(f"Top {TOP_N} rows per section.  Min pairs: {MIN_PAIRS}\n")

    # --- Sections A/B: uint8 vs motor speed ---
    sec_a = sorted(byte_results,
                   key=lambda x: abs(x['ds']) if has_val(x['ds']) else 0,
                   reverse=True)
    sec_b = sorted(
        [r for r in byte_results
         if has_val(r['sd_crs']) and 0.01 < r['sd_crs'] < SETPOINT_STDEV_MAX],
        key=lambda x: x['sd_crs']
    )
    write_section_speed(f, sec_a,
        "SECTION A: uint8 vs MOTOR SPEED -- sorted by |delta_r| descending",
        "Speed-tracking bytes; motor-speed echoes dominate top rows")
    write_section_speed(f, sec_b,
        "SECTION B: uint8 vs MOTOR SPEED -- sorted by sd_cruise ascending (setpoint candidates)",
        f"Near-constant during cruise (sd_crs < {SETPOINT_STDEV_MAX}); setpoints show low sd_crs, high sd_pre/pst")

    # --- Sections C/D: uint8 vs torque feedback ---
    sec_c = sorted(byte_results,
                   key=lambda x: abs(x['dt']) if has_val(x['dt']) else 0,
                   reverse=True)
    sec_d = sorted(
        [r for r in byte_results
         if has_val(r['sd_crs']) and 0.01 < r['sd_crs'] < SETPOINT_STDEV_MAX],
        key=lambda x: x['sd_crs']
    )
    write_section_torque(f, sec_c,
        "SECTION C: uint8 vs TORQUE FEEDBACK -- sorted by |delta_r| descending",
        "Torque-tracking bytes; high |rt_crs| with low |rt_man| = cruise-specific torque command candidate")
    write_section_torque(f, sec_d,
        "SECTION D: uint8 vs TORQUE FEEDBACK -- near-constant during cruise (setpoint/cmd candidates)",
        f"Same filter as B: sd_crs < {SETPOINT_STDEV_MAX}")

    # --- Sections E/F: BE16 vs speed and torque ---
    sec_e = sorted(be16_results,
                   key=lambda x: abs(x['ds']) if has_val(x['ds']) else 0,
                   reverse=True)
    sec_f = sorted(be16_results,
                   key=lambda x: abs(x['dt']) if has_val(x['dt']) else 0,
                   reverse=True)
    write_section_speed(f, sec_e,
        "SECTION E: BE16 vs MOTOR SPEED -- sorted by |delta_r| descending",
        "Big-endian uint16 - 32768 pairs; B[n]<<8 | B[n+1]")
    write_section_torque(f, sec_f,
        "SECTION F: BE16 vs TORQUE FEEDBACK -- sorted by |delta_r| descending",
        "Big-endian uint16 - 32768 pairs; B[n]<<8 | B[n+1]")

print(f"\nOutput written to {OUTPUT}")
print(f"Sections: A={min(len(sec_a),TOP_N)} B={min(len(sec_b),TOP_N)} C={min(len(sec_c),TOP_N)} "
      f"D={min(len(sec_d),TOP_N)} E={min(len(sec_e),TOP_N)} F={min(len(sec_f),TOP_N)}")

# Quick console preview of Section C top 20 (cruise-specific torque command candidates)
def fmt_r_short(v):
    return f"{v:7.4f}" if not math.isnan(v) else "     --"

print("\n--- Section C top 20 (uint8 vs torque feedback, |delta_r| desc) ---")
hdr = (f"{'ID':10s} {'B':3s} {'rt_crs':>7s} {'rt_pre':>7s} {'rt_pst':>7s} "
       f"{'rt_man':>7s} {'dt':>7s} {'sd_crs':>7s}")
print(hdr)
print('-' * 70)
for row in sec_c[:20]:
    print(f"0x{row['id']:06X}  {row['byte']:3d} "
          f"{fmt_r_short(row['rt_crs'])} {fmt_r_short(row['rt_pre'])} {fmt_r_short(row['rt_pst'])} "
          f"{fmt_r_short(row['rt_man'])} {fmt_r_short(row['dt'])} {fmt_sd(row['sd_crs'])}")

print("\n--- Section B top 20 (uint8 vs motor speed, sd_cruise asc) ---")
hdr2 = (f"{'ID':10s} {'B':3s} {'rs_crs':>7s} {'rs_pre':>7s} {'rs_pst':>7s} "
        f"{'rs_man':>7s} {'ds':>7s} {'sd_crs':>7s}")
print(hdr2)
print('-' * 70)
for row in sec_b[:20]:
    print(f"0x{row['id']:06X}  {row['byte']:3d} "
          f"{fmt_r_short(row['rs_crs'])} {fmt_r_short(row['rs_pre'])} {fmt_r_short(row['rs_pst'])} "
          f"{fmt_r_short(row['rs_man'])} {fmt_r_short(row['ds'])} {fmt_sd(row['sd_crs'])}")
