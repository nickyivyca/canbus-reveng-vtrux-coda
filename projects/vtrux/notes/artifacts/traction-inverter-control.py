"""
Traction inverter control investigation scratchpad.
Run: py -3.12 projects/vtrux/notes/artifacts/traction-inverter-control.py <phase>

Phases:
  cross_validate          -- Pearson r: 0x442 B0-B1 vs 0x5A2 B4-B5 (Step 1)
  cmd_correlate           -- Pearson r: 0x041 B1-B2 vs 0x442 B0-B1 (Step 4)
  throttle_correlate      -- Pearson r: 0x041 B1-B2 vs 0x592 B2-B3 throttle (Step 4)
  climit_regen            -- Is 0x041 bidirectional? cmd vs brake+feedback in climit log
  climit_discharge_divergence -- cmd vs feedback during discharge limit event
  cruise_hyp_ab           -- Phase 2: Is 0x041 varying during cruise? Hyp A vs B test
  cruise_regen_scan       -- Phase 2 addendum: full cruise period + anotherevap P2 regen scan
"""

import sys
import csv
import math
import re
from collections import defaultdict
from pathlib import Path

ARTIFACTS = "projects/vtrux/notes/artifacts"


def load_ts(path):
    """Load a timeseries CSV -> list of (timestamp, value) floats."""
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((float(row["timestamp"]), float(row["value"])))
    return rows


def interpolate(ts_ref, ts_src):
    """Resample ts_src at each timestamp in ts_ref using linear interpolation."""
    out = []
    j = 0
    n = len(ts_src)
    for t, _ in ts_ref:
        # advance j to straddle t
        while j + 1 < n and ts_src[j + 1][0] <= t:
            j += 1
        if j + 1 >= n:
            out.append(ts_src[-1][1])
        elif j == 0 and t < ts_src[0][0]:
            out.append(ts_src[0][1])
        else:
            t0, v0 = ts_src[j]
            t1, v1 = ts_src[j + 1]
            frac = (t - t0) / (t1 - t0) if t1 != t0 else 0.0
            out.append(v0 + frac * (v1 - v0))
    return out


def pearson(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return float("nan")
    return num / (dx * dy)


def stats(vals, label):
    n = len(vals)
    mn = min(vals)
    mx = max(vals)
    mean = sum(vals) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in vals) / n)
    print(f"  {label}: n={n}, min={mn:.1f}, max={mx:.1f}, mean={mean:.1f}, std={std:.1f}")


def cross_validate():
    """Step 1: Cross-validate 0x442 B0-B1 vs 0x5A2 B4-B5."""
    print("=== Step 1: Cross-validate traction torque feedback signals ===")
    print("  0x442 B0-B1 (TRAC MCU direct, OBD bus) vs 0x5A2 B4-B5 (VCM rebroadcast, PT bus)")
    print()
    ts442 = load_ts(f"{ARTIFACTS}/trac-cmd-0x442-ts.csv")
    ts5a2 = load_ts(f"{ARTIFACTS}/trac-cmd-5a2b45-ts.csv")
    print(f"  0x442 samples: {len(ts442)}, span: {ts442[0][0]:.1f}s - {ts442[-1][0]:.1f}s")
    print(f"  0x5A2 samples: {len(ts5a2)}, span: {ts5a2[0][0]:.1f}s - {ts5a2[-1][0]:.1f}s")
    print()

    # Resample 0x5A2 onto 0x442 timestamps
    ref_t = [t for t, _ in ts442]
    ref_v = [v for _, v in ts442]
    src_v = interpolate(ts442, ts5a2)

    r = pearson(ref_v, src_v)
    print(f"  Full-log Pearson r (0x442 vs 0x5A2): {r:.4f}")
    stats(ref_v, "0x442 B0-B1 raw")
    stats(src_v, "0x5A2 B4-B5 raw (resampled)")

    # Compute residual after scaling 0x5A2 to 0x442 units
    # 0x442: centered at 32768 (like 0x471)
    # 0x5A2 B4-B5: also LE uint16 centered at 32768 per Vtrux.md
    residuals = [a - b for a, b in zip(ref_v, src_v)]
    mean_res = sum(residuals) / len(residuals)
    max_res = max(abs(r) for r in residuals)
    std_res = math.sqrt(sum(x ** 2 for x in residuals) / len(residuals))
    print(f"  Residual (0x442 - 0x5A2): mean={mean_res:.1f}, max_abs={max_res:.1f}, rms={std_res:.1f}")

    # Check for divergence windows (sliding 5s windows where residual > 500 counts)
    print()
    print("  Divergence windows (consecutive frames with |residual| > 500 counts):")
    THRESH = 500
    in_div = False
    start_t = 0.0
    count = 0
    divs = []
    for i, (t, res) in enumerate(zip(ref_t, residuals)):
        if abs(res) > THRESH:
            if not in_div:
                in_div = True
                start_t = t
                count = 1
            else:
                count += 1
        else:
            if in_div and count >= 5:
                divs.append((start_t, t, count))
            in_div = False
            count = 0
    if in_div and count >= 5:
        divs.append((start_t, ref_t[-1], count))
    if divs:
        for s, e, c in divs[:20]:
            print(f"    t={s:.1f}s-{e:.1f}s ({c} frames)")
        if len(divs) > 20:
            print(f"    ... and {len(divs)-20} more")
    else:
        print("    None found (signals track well)")


def cmd_correlate():
    """Step 4: Correlate 0x041 B1-B2 command vs 0x442 B0-B1 feedback."""
    print("=== Step 4: Correlate 0x041 B1-B2 (command candidate) vs 0x442 B0-B1 (feedback) ===")
    print()
    ts041 = load_ts(f"{ARTIFACTS}/trac-cmd-0x041-ts.csv")
    ts442 = load_ts(f"{ARTIFACTS}/trac-cmd-0x442-ts.csv")
    print(f"  0x041 samples: {len(ts041)}, span: {ts041[0][0]:.1f}s - {ts041[-1][0]:.1f}s")
    print(f"  0x442 samples: {len(ts442)}, span: {ts442[0][0]:.1f}s - {ts442[-1][0]:.1f}s")
    print()

    ref_v = [v for _, v in ts041]
    src_v = interpolate(ts041, ts442)

    r_full = pearson(ref_v, src_v)
    print(f"  Full-log Pearson r: {r_full:.4f}")
    stats(ref_v, "0x041 B1-B2 raw (cmd)")
    stats(src_v, "0x442 B0-B1 raw (feedback, resampled)")

    # Windowed correlation: 30s windows stepping by 15s, skip near-constant windows
    print()
    print("  Windowed Pearson r (30s windows, step 15s) -- only windows with cmd stdev > 500:")
    ts_arr = [t for t, _ in ts041]
    T_MAX = ts_arr[-1]
    W = 30.0
    STEP = 15.0
    t0 = ts_arr[0]
    windows = []
    while t0 + W <= T_MAX:
        # Select indices in window
        idxs = [i for i, t in enumerate(ts_arr) if t0 <= t < t0 + W]
        if len(idxs) > 100:
            cv = [ref_v[i] for i in idxs]
            fv = [src_v[i] for i in idxs]
            std_c = math.sqrt(sum((x - sum(cv)/len(cv))**2 for x in cv) / len(cv))
            if std_c > 500:
                r_w = pearson(cv, fv)
                windows.append((t0, r_w, std_c, len(idxs)))
        t0 += STEP

    if windows:
        for wt, wr, wstd, wn in windows:
            print(f"    t={wt:.0f}-{wt+W:.0f}s: r={wr:.4f}, cmd_std={wstd:.0f}, n={wn}")
    else:
        print("    No active windows found (command near-constant throughout?)")
        # Print overall cmd stats anyway
        std_all = math.sqrt(sum((x - sum(ref_v)/len(ref_v))**2 for x in ref_v) / len(ref_v))
        print(f"    Overall cmd stdev = {std_all:.1f} counts")


def throttle_correlate():
    """Step 4b/5: Correlate 0x041 B1-B2 vs throttle and brake pedals."""
    print("=== Step 4b: Correlate 0x041 B1-B2 (command) vs 0x592 B2-B3 (throttle) ===")
    ts041 = load_ts(f"{ARTIFACTS}/trac-cmd-0x041-ts.csv")
    ts_thr = load_ts(f"{ARTIFACTS}/trac-cmd-throttle-ts.csv")
    ts_brk = load_ts(f"{ARTIFACTS}/trac-cmd-brake-ts.csv")

    ref_t = [t for t, _ in ts041]
    ref_v = [v for _, v in ts041]
    thr_v = interpolate(ts041, ts_thr)
    brk_v = interpolate(ts041, ts_brk)

    r_thr = pearson(ref_v, thr_v)
    r_brk = pearson(ref_v, brk_v)
    print(f"  Full-log r (cmd vs throttle): {r_thr:.4f}")
    print(f"  Full-log r (cmd vs brake):    {r_brk:.4f}")
    stats([v for _, v in ts_thr], "0x592 B2-B3 throttle raw")
    stats([v for _, v in ts_brk], "0x592 B4-B5 brake raw")

    # Step 5: Regen window - frames where cmd < 32768 (regen torque)
    print()
    print("=== Step 5: Regen direction ===")
    regen_idxs = [i for i, v in enumerate(ref_v) if v < 32768]
    motor_idxs = [i for i, v in enumerate(ref_v) if v > 32768]
    print(f"  Frames with cmd < 32768 (regen): {len(regen_idxs)} ({100*len(regen_idxs)/len(ref_v):.1f}%)")
    print(f"  Frames with cmd > 32768 (motor):  {len(motor_idxs)} ({100*len(motor_idxs)/len(ref_v):.1f}%)")
    if regen_idxs:
        regen_cmd = [ref_v[i] for i in regen_idxs]
        regen_brk = [brk_v[i] for i in regen_idxs]
        r_regen = pearson(regen_cmd, regen_brk)
        print(f"  Pearson r (cmd vs brake) during regen frames: {r_regen:.4f}")
        stats(regen_cmd, "  cmd during regen")
        stats(regen_brk, "  brake during regen")
    if motor_idxs:
        motor_cmd = [ref_v[i] for i in motor_idxs]
        motor_thr = [thr_v[i] for i in motor_idxs]
        r_motor = pearson(motor_cmd, motor_thr)
        print(f"  Pearson r (cmd vs throttle) during motoring frames: {r_motor:.4f}")
        stats(motor_cmd, "  cmd during motoring")
        stats(motor_thr, "  throttle during motoring")


BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+'
    r'0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+'
    r'((?:[0-9A-Fa-f]{2}\s*)+)'
)

def parse_ts_str(ts_str):
    h, m, s, t = ts_str.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001

def parse_log_ids(log_path, ids):
    """Parse log, return dict of mid -> list of (t, data_bytes)."""
    result = defaultdict(list)
    t0 = None
    with open(log_path, 'r', errors='replace') as f:
        for line in f:
            m = BUSMASTER_RE.match(line.strip())
            if not m:
                continue
            ts_str, bus_str, id_str, dlc_str, data_str = m.groups()
            mid = int(id_str, 16)
            if mid not in ids:
                continue
            ts = parse_ts_str(ts_str)
            if t0 is None:
                t0 = ts
            dat = [int(b, 16) for b in data_str.strip().split()]
            result[mid].append((ts - t0, dat))
    return result

def u16_le(data, b):
    return data[b] | (data[b+1] << 8)

def nearest_val(ts_list, t, max_dt=0.15):
    if not ts_list:
        return None
    lo, hi = 0, len(ts_list) - 1
    while lo < hi:
        mid_i = (lo + hi) // 2
        if ts_list[mid_i][0] < t:
            lo = mid_i + 1
        else:
            hi = mid_i
    best_i, best_dt = lo, abs(ts_list[lo][0] - t)
    for i in (lo - 1, lo + 1):
        if 0 <= i < len(ts_list):
            dt = abs(ts_list[i][0] - t)
            if dt < best_dt:
                best_dt, best_i = dt, i
    return ts_list[best_i][1] if best_dt <= max_dt else None


def climit_regen():
    """Is 0x041 bidirectional? Check cmd vs brake + feedback in climit log."""
    print("=== climit_regen: Is 0x041 B1-B2 bidirectional in vtruxcurrentlimitingtest.log? ===")
    print()

    log = Path("projects/vtrux/logs/vtruxcurrentlimitingtest.log")
    ids = {0x041, 0x442, 0x592}
    print(f"  Parsing {log.name} for IDs: {[hex(x) for x in ids]} ...")
    frames = parse_log_ids(log, ids)
    for mid in ids:
        print(f"  0x{mid:03X}: {len(frames[mid])} frames")
    print()

    # Build signal timeseries (centered at 32768 for torque, raw for brake)
    cmd_ts  = [(t, u16_le(d, 1)) for t, d in frames[0x041] if len(d) >= 3]
    fbk_ts  = [(t, u16_le(d, 0)) for t, d in frames[0x442] if len(d) >= 2]
    brk_ts  = [(t, u16_le(d, 4)) for t, d in frames[0x592] if len(d) >= 6]

    cmd_v = [v for _, v in cmd_ts]
    print(f"  0x041 B1-B2 LE range: min={min(cmd_v)}, max={max(cmd_v)}  (neutral=32768)")
    print(f"  Regen frames (cmd < 32768): {sum(1 for v in cmd_v if v < 32768)} / {len(cmd_v)}")
    print(f"  Motor frames (cmd > 32768): {sum(1 for v in cmd_v if v > 32768)} / {len(cmd_v)}")
    print(f"  Max regen depth: {min(cmd_v) - 32768} counts  ({(min(cmd_v)-32768)*0.125:.1f} Nm)")
    print(f"  Max motor peak:  {max(cmd_v) - 32768} counts  ({(max(cmd_v)-32768)*0.125:.1f} Nm)")
    print()

    # Correlation: cmd vs brake during regen frames
    regen_ts = [(t, v) for t, v in cmd_ts if v < 32768]
    regen_t  = [t for t, _ in regen_ts]
    regen_cmd = [v - 32768 for _, v in regen_ts]  # negative = regen

    brk_at_regen = [nearest_val(brk_ts, t) for t in regen_t]
    fbk_at_regen = [nearest_val(fbk_ts, t) for t in regen_t]

    valid = [(c, b, f) for c, b, f in zip(regen_cmd, brk_at_regen, fbk_at_regen)
             if b is not None and f is not None]
    if valid:
        rc, rb, rf = zip(*valid)
        rb_c = [v - 32768 for v in rb]
        rf_c = [v - 32768 for v in rf]
        r_cmd_brk = pearson(list(rc), list(rb_c))
        r_cmd_fbk = pearson(list(rc), list(rf_c))
        print(f"  During regen frames (n={len(valid)}):")
        print(f"    r(cmd vs brake B4-B5):    {r_cmd_brk:+.4f}")
        print(f"    r(cmd vs fbk 0x442 B0-B1): {r_cmd_fbk:+.4f}")
        stats(list(rc),   "    cmd (centered)")
        stats(list(rb_c), "    brake B4-B5 (centered)")
        stats(list(rf_c), "    fbk 0x442 B0-B1 (centered)")
    print()

    # Sample table: 20 deepest regen frames
    regen_sorted = sorted(zip(regen_cmd, regen_t), key=lambda x: x[0])[:20]
    print("  20 deepest regen frames (cmd | brake_raw | fbk_centered):")
    print(f"  {'t':>8}  {'cmd_cen':>8}  {'Nm':>8}  {'brake_raw':>9}  {'fbk_cen':>8}")
    for cmd_c, t in regen_sorted:
        b = nearest_val(brk_ts, t)
        f = nearest_val(fbk_ts, t)
        b_s = str(b) if b is not None else '?'
        f_s = f'{f-32768:+d}' if f is not None else '?'
        print(f"  {t:8.1f}  {cmd_c:+8d}  {cmd_c*0.125:+8.1f}  {b_s:>9}  {f_s:>8}")


def climit_discharge_divergence():
    """During the climit discharge limit event (t=598s+), does cmd track feedback or diverge?
    If VCM tracks the limit: cmd and feedback move together (r stays high, residual small).
    If inverter limits unilaterally: cmd stays high while feedback drops (residual grows).
    Also checks flux-weakening region: at high motor speed, does cmd exceed feedback?
    """
    print("=== climit_discharge_divergence: cmd vs feedback during discharge limit event ===")
    print()

    log = Path("projects/vtrux/logs/vtruxcurrentlimitingtest.log")
    ids = {0x041, 0x442, 0x054}  # 0x054 = GENE RPM (PT bus anchor; proxy for motor speed via symmetry)
    # Actually need motor speed from OBD bus: 0x044 = TRAC_RotSpd
    ids = {0x041, 0x442, 0x044}
    print(f"  Parsing {log.name} ...")
    frames = parse_log_ids(log, ids)
    for mid in ids:
        print(f"  0x{mid:03X}: {len(frames[mid])} frames")
    print()

    cmd_ts  = [(t, u16_le(d, 1) - 32768) for t, d in frames[0x041] if len(d) >= 3]
    fbk_ts  = [(t, u16_le(d, 0) - 32768) for t, d in frames[0x442] if len(d) >= 2]
    rpm_ts  = [(t, u16_le(d, 0) - 32767) for t, d in frames[0x044] if len(d) >= 2]

    # Compute cmd-fbk residual at each cmd timestamp (motoring only: cmd > 0)
    motor_pairs = [(t, c, nearest_val(fbk_ts, t)) for t, c in cmd_ts if c > 50]
    motor_pairs = [(t, c, f) for t, c, f in motor_pairs if f is not None]

    print(f"  Motoring frames (cmd > 50 counts): {len(motor_pairs)}")

    # Windows: pre-limit (t=400-598), during limit (t=598-700), post-limit (t=700+)
    windows = [
        ("pre-limit   t=400-598s", 400, 598),
        ("during-lim  t=598-700s", 598, 700),
        ("post-limit  t=700-900s", 700, 900),
    ]
    print()
    print(f"  {'Window':<28}  {'n':>5}  {'cmd_mean':>9}  {'fbk_mean':>9}  {'residual_mean':>14}  {'residual_max':>12}  {'r':>7}")
    print("  " + "-" * 95)
    for label, t0, t1 in windows:
        pts = [(c, f) for t, c, f in motor_pairs if t0 <= t < t1]
        if len(pts) < 10:
            print(f"  {label:<28}  {len(pts):>5}  (insufficient data)")
            continue
        cs, fs = zip(*pts)
        res = [c - f for c, f in pts]
        r = pearson(list(cs), list(fs))
        print(f"  {label:<28}  {len(pts):>5}  {sum(cs)/len(cs):>9.0f}  {sum(fs)/len(fs):>9.0f}  "
              f"{sum(res)/len(res):>14.1f}  {max(abs(x) for x in res):>12.0f}  {r:>7.4f}")

    # Show peak divergence frames (cmd - fbk > threshold)
    print()
    DIVTHRESH = 500
    big_div = sorted([(t, c, f, c-f) for t, c, f in motor_pairs if abs(c-f) > DIVTHRESH],
                     key=lambda x: -abs(x[3]))[:20]
    if big_div:
        rpm_at = {t: nearest_val(rpm_ts, t) for t, *_ in big_div}
        print(f"  Largest cmd-fbk divergences (|residual| > {DIVTHRESH} counts, top 20):")
        print(f"  {'t':>7}  {'cmd':>7}  {'fbk':>7}  {'residual':>9}  {'cmd_Nm':>8}  {'rpm':>6}")
        for t, c, f, res in big_div:
            rpm = rpm_at[t]
            rpm_s = f'{rpm:+d}' if rpm is not None else '?'
            print(f"  {t:7.1f}  {c:>7}  {f:>7}  {res:>+9}  {c*0.125:>8.1f}  {rpm_s:>6}")
    else:
        print(f"  No frames with |cmd-fbk| > {DIVTHRESH} counts during motoring.")


def cruise_regen_scan():
    """Phase 2 addendum: scan both cruise-active logs for regen (cmd < 32768) during cruise.

    evaplog4 P1:      full cruise window t=431-1108s
    anotherevap P2:   full log (need to identify cruise window from 0x644 mode nibble)
    """
    LOGS = [
        ("evaplog4 P1",     Path("projects/vtrux/logs/vtruxevapdrivelog4.log")),
        ("anotherevap P2",  Path("projects/vtrux/logs/vtruxanotherevaplogpart2.log")),
    ]
    OBD_BUS = 1   # OBD bus is bus 1 in these logs (anchor: 0x041, 0x044, 0x442)
    PT_BUS  = 2   # PT bus is bus 2 (anchor: 0x051, 0x5A2, 0x644)

    for log_label, log_path in LOGS:
        print(f"=== {log_label}: {log_path.name} ===")
        ids_wanted = {0x041, 0x644}
        frames = parse_log_ids(log_path, ids_wanted)
        cmd_ts = [(t, u16_le(d, 1)) for t, d in frames[0x041] if len(d) >= 3]
        spt_ts = [(t, d[2]) for t, d in frames[0x644] if len(d) >= 4]  # B2 = mode nibble byte

        if not cmd_ts:
            print("  No 0x041 frames found.")
            print()
            continue

        t_span = cmd_ts[-1][0] - cmd_ts[0][0]
        print(f"  0x041 frames: {len(cmd_ts)}, span {cmd_ts[0][0]:.1f}-{cmd_ts[-1][0]:.1f}s ({t_span:.0f}s)")

        # Identify cruise-active windows from 0x644 B2 mode nibble
        # Mode nibble: upper 4 bits of B2; 0xA = cruise active
        cruise_windows = []
        in_cruise = False
        c_start = 0.0
        for t, b2 in spt_ts:
            mode = (b2 >> 4) & 0xF
            if mode == 0xA and not in_cruise:
                in_cruise = True
                c_start = t
            elif mode != 0xA and in_cruise:
                in_cruise = False
                cruise_windows.append((c_start, t))
        if in_cruise:
            cruise_windows.append((c_start, spt_ts[-1][0]))

        print(f"  Cruise-active windows from 0x644 B2 mode nibble (0xA):")
        for i, (t0, t1) in enumerate(cruise_windows):
            dur = t1 - t0
            print(f"    [{i}] t={t0:.1f}-{t1:.1f}s ({dur:.0f}s)")

        # Stats within each cruise window
        for i, (t0, t1) in enumerate(cruise_windows):
            seg = [(t, v) for t, v in cmd_ts if t0 <= t <= t1]
            if not seg:
                continue
            vals = [v for _, v in seg]
            mean = sum(vals) / len(vals)
            std = math.sqrt(sum((x - mean)**2 for x in vals) / len(vals))
            regen = [(t, v) for t, v in seg if v < 32768]
            print(f"    Window [{i}] t={t0:.0f}-{t1:.0f}s: n={len(seg)}, "
                  f"mean_cen={mean-32768:+.0f}, std={std:.1f}, "
                  f"min_cen={min(vals)-32768:+d}, max_cen={max(vals)-32768:+d}, "
                  f"regen_frames={len(regen)}")
            if regen:
                rvals = [v - 32768 for _, v in regen]
                t_regen = [t for t, _ in regen]
                print(f"      Regen: n={len(regen)}, min_cen={min(rvals):+d} ({min(rvals)*0.125:.1f} Nm), "
                      f"t_range={min(t_regen):.1f}-{max(t_regen):.1f}s")
                # Show deepest regen moments (consecutive blocks)
                blocks, blk_start, blk_last = [], regen[0][0], regen[0][0]
                for t, v in regen[1:]:
                    if t - blk_last < 2.0:
                        blk_last = t
                    else:
                        blocks.append((blk_start, blk_last))
                        blk_start = blk_last = t
                blocks.append((blk_start, blk_last))
                print(f"      Regen blocks ({len(blocks)} total, showing up to 10):")
                for bs, be in blocks[:10]:
                    blk = [(v-32768) for t, v in regen if bs <= t <= be]
                    print(f"        t={bs:.1f}-{be:.1f}s: n={len(blk)}, "
                          f"min={min(blk):+d} ({min(blk)*0.125:.1f} Nm)")
        print()


def cruise_hyp_ab():
    """Phase 2: Test Hypothesis A vs B.

    Hypothesis A (VCM closes speed loop): 0x041 varies continuously during cruise,
    inversely correlating with motor speed.
    Hypothesis B (inverter closes speed loop): 0x041 near-constant during cruise.

    Tests:
    1. Stats for 0x041 in three segments (pre_hybrid, cruise, post_hybrid)
    2. Pearson r: 0x041 vs motor speed (0x5A2 B2-B3, parsed from P1 log) during cruise
    3. Pearson r: 0x041 vs generator cmd (0x051) during cruise (both should vary)
    4. Visual: 10-second slice output during cruise showing cmd values
    """
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
    from canre.parsers import parse_file

    print("=== Phase 2: Cruise Hypothesis A vs B ===")
    print()

    P1_LOG = Path("projects/vtrux/logs/vtruxevapdrivelog4.log")
    ARTIFACTS = "projects/vtrux/notes/artifacts"

    # Load pre-computed timeseries
    cmd_ts  = load_ts(f"{ARTIFACTS}/cruise_traction_cmd_ts.csv")   # 0x041 B1-B2
    gen_ts  = load_ts(f"{ARTIFACTS}/cruise_gen_cmd_ts.csv")        # 0x051 B1-B2

    # Extract motor speed (0x5A2 B2-B3) from P1 log on PT bus (bus 2)
    print(f"Parsing {P1_LOG.name} for 0x5A2 B2-B3 (motor speed, PT bus 2)...")
    SPD_ID  = 0x5A2
    SPD_BUS = 2
    SPD_BYTE = 2

    BUSMASTER_RE_LOC = re.compile(
        r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+'
        r'0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+'
        r'((?:[0-9A-Fa-f]{2}\s*)+)'
    )
    spd_ts = []
    t0_ref = None
    with open(P1_LOG, 'r', errors='replace') as f:
        for line in f:
            m = BUSMASTER_RE_LOC.match(line.strip())
            if not m:
                continue
            ts_str, bus_str, id_str, dlc_str, data_str = m.groups()
            if int(id_str, 16) != SPD_ID or int(bus_str) != SPD_BUS:
                continue
            ts = parse_ts_str(ts_str)
            if t0_ref is None:
                t0_ref = ts
            dat = [int(b, 16) for b in data_str.strip().split()]
            if len(dat) < SPD_BYTE + 2:
                continue
            raw = dat[SPD_BYTE] | (dat[SPD_BYTE + 1] << 8)
            spd_ts.append((ts - t0_ref, raw))

    print(f"  Motor speed samples: {len(spd_ts)}")
    print()

    SEGMENTS = [
        ('pre_hybrid',  431,  720),
        ('cruise',      720, 1080),
        ('post_hybrid', 1122, 1462),
    ]

    # ---- Step 1: per-segment stats for cmd, gen, and motor speed ----
    print("Step 1 -- Per-segment statistics")
    print(f"{'Segment':<15} {'Signal':<18} {'n':>6}  {'mean':>8}  {'std':>8}  {'min':>6}  {'max':>6}")
    print("-" * 75)
    for seg_name, t0, t1 in SEGMENTS:
        for label, ts_data, center in [
            ('trac_cmd 0x041', cmd_ts, 32768),
            ('gen_cmd  0x051', gen_ts, 32768),
            ('motor_spd 0x5A2', spd_ts, 32768),
        ]:
            seg_vals = [v - center for t, v in ts_data if t0 <= t < t1]
            if not seg_vals:
                print(f"  {seg_name:<13} {label:<18} {'N/A':>6}")
                continue
            n = len(seg_vals)
            mn = min(seg_vals)
            mx = max(seg_vals)
            mean = sum(seg_vals) / n
            std = math.sqrt(sum((x - mean) ** 2 for x in seg_vals) / n)
            print(f"  {seg_name:<13} {label:<18} {n:>6}  {mean:>8.1f}  {std:>8.1f}  {mn:>6}  {mx:>6}")

    # ---- Step 2: Pearson r: trac_cmd vs motor speed during cruise ----
    print()
    print("Step 2 -- Pearson r: trac_cmd vs motor speed, by segment")
    for seg_name, t0, t1 in SEGMENTS:
        cmd_seg  = [(t, v - 32768) for t, v in cmd_ts  if t0 <= t < t1]
        if not cmd_seg:
            continue
        spd_at_cmd = interpolate(cmd_seg, [(t, v - 32768) for t, v in spd_ts])
        cmd_v = [v for _, v in cmd_seg]
        r = pearson(cmd_v, spd_at_cmd)
        print(f"  {seg_name:<15} r(cmd vs speed): {r:+.4f}  (n={len(cmd_v)})")

    # ---- Step 3: Pearson r: trac_cmd vs gen_cmd during cruise ----
    print()
    print("Step 3 -- Pearson r: trac_cmd vs gen_cmd, by segment")
    for seg_name, t0, t1 in SEGMENTS:
        cmd_seg = [(t, v - 32768) for t, v in cmd_ts if t0 <= t < t1]
        if not cmd_seg:
            continue
        gen_at_cmd = interpolate(cmd_seg, [(t, v - 32768) for t, v in gen_ts])
        cmd_v = [v for _, v in cmd_seg]
        r = pearson(cmd_v, gen_at_cmd)
        print(f"  {seg_name:<15} r(trac_cmd vs gen_cmd): {r:+.4f}  (n={len(cmd_v)})")

    # ---- Step 4: 10-second cruise sample ----
    print()
    print("Step 4 -- 10-second sample during cruise (t=850-860s)")
    t_start, t_end = 850.0, 860.0
    sample = [(t, v) for t, v in cmd_ts if t_start <= t < t_end]
    if sample:
        spd_sample = interpolate(sample, spd_ts)
        print(f"  {'t':>8}  {'cmd_raw':>8}  {'cmd_cen':>8}  {'cmd_Nm':>8}  {'spd_raw':>8}  {'spd_cen':>8}")
        # Show every 10th row
        for i, ((t, v), spd) in enumerate(zip(sample, spd_sample)):
            if i % 10 == 0:
                print(f"  {t:8.2f}  {v:>8.0f}  {v-32768:>+8.0f}  {(v-32768)*0.125:>+8.1f}  "
                      f"{spd:>8.0f}  {spd-32768:>+8.0f}")
    else:
        print("  No frames in t=850-860s range")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py -3.12 traction-inverter-control.py <phase>")
        print("Phases: cross_validate, cmd_correlate, throttle_correlate, climit_regen")
        sys.exit(1)
    phase = sys.argv[1]
    if phase == "cross_validate":
        cross_validate()
    elif phase == "cmd_correlate":
        cmd_correlate()
    elif phase == "throttle_correlate":
        throttle_correlate()
    elif phase == "climit_regen":
        climit_regen()
    elif phase == "climit_discharge_divergence":
        climit_discharge_divergence()
    elif phase == "cruise_hyp_ab":
        cruise_hyp_ab()
    elif phase == "cruise_regen_scan":
        cruise_regen_scan()
    else:
        print(f"Unknown phase: {phase}")
        sys.exit(1)
