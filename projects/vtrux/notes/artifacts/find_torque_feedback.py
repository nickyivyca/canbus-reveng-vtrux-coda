"""
find_torque_feedback.py

Search for generator and drivetrain motor torque feedback signals on the PT bus.

Strategy: compute T = P / omega = I * V_HV / (RPM * 2*pi/60) from confirmed signals,
then correlate this reference against every byte/word on the PT bus.

Generator reference (from evap drive log part 2 — clean hybrid mode):
  T_gen  prop.  (0x598 B2-B3 LE - 32768) * V_HV / max(RPM_gen, RPM_MIN)
  RPM_gen: 16 * 0x63C B6 - 96  (confirmed, r=0.9975 vs OBD PID 0x0C)
  I_gen:   0x598 B2-B3 LE - 32768  (confirmed role)
  Only rows where RPM_gen > RPM_GEN_MIN (gen clearly spinning).

Drivetrain reference (from current-limiting log — widest dynamic range):
  T_drive prop.  (0x598 B4-B5 LE - 32768) * V_HV / max(|RPM_mtr|, RPM_MIN)
  RPM_mtr: 0x5A2 B2-B3 LE - 32768  (high confidence, r=0.9976 vs proxy)
  I_drv:   0x598 B4-B5 LE - 32768  (confirmed role)
  Only rows where |RPM_mtr| > RPM_MTR_MIN.

HV voltage: prefer 0x482 B1-B2 LE (integer V, 20 Hz);
            fallback 0x18FFD6B3 B4-B5 LE signed x0.05 V (~10 Hz).

PT bus auto-detected: whichever bus has 0x051 frames.

Outputs to stdout and find_torque_feedback_output.txt in the artifacts folder.

Usage:
    python find_torque_feedback.py
"""

import re
import math
import sys
from pathlib import Path
from collections import defaultdict

# ── paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]
LOGS_DIR     = PROJECT_ROOT / "projects" / "vtrux" / "logs"

LOG_GEN      = LOGS_DIR / "vtruxevapdrivelog4part2.log"   # generator active (hybrid mode)
LOG_DRIVE    = LOGS_DIR / "vtruxcurrentlimitingtest.log"  # widest drivetrain dynamic range

OUTPUT_FILE  = SCRIPT_DIR / "find_torque_feedback_output.txt"

# ── thresholds ─────────────────────────────────────────────────────────────────
RPM_GEN_MIN  = 300    # RPM — generator must be clearly spinning (avoids div/0 & noise)
RPM_MTR_MIN  = 200    # RPM — traction motor must be moving
MAX_DT_HV    = 3.0    # s — max age for HV voltage lookup
MAX_DT_RPM   = 0.12   # s — max age for RPM lookup (0x63C is 50 Hz, 0x5A2 is 20 Hz)
MAX_DT_CUR   = 0.08   # s — max age for current lookup (0x598 is 20 Hz)

TOP_N        = 35     # results per table

# ── BUSMASTER parser ────────────────────────────────────────────────────────────
BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+'
    r'0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+'
    r'((?:[0-9A-Fa-f]{2}\s*)+)'
)


def parse_ts(ts_str):
    h, m, s, t = ts_str.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(t) * 0.0001


def parse_log(log_path):
    """Parse BUSMASTER log, returning {bus -> {msg_id -> [(t, [bytes])]}}."""
    buses = defaultdict(lambda: defaultdict(list))
    t0 = None
    with open(log_path, 'r', errors='replace') as f:
        for line in f:
            m = BUSMASTER_RE.match(line.strip())
            if not m:
                continue
            ts_str, bus_str, id_str, dlc_str, data_str = m.groups()
            ts  = parse_ts(ts_str)
            if t0 is None:
                t0 = ts
            t   = ts - t0
            bus = int(bus_str)
            mid = int(id_str, 16)
            dat = [int(b, 16) for b in data_str.strip().split()]
            buses[bus][mid].append((t, dat))
    return buses


def find_pt_bus(buses):
    """Return the bus number that contains 0x051 (PT bus anchor ID)."""
    for bus, ids in buses.items():
        if 0x051 in ids and len(ids[0x051]) > 10:
            return bus
    return None


# ── helpers ─────────────────────────────────────────────────────────────────────
def u16_le(data, b):
    if len(data) < b + 2:
        return None
    return data[b] | (data[b + 1] << 8)


def s16_le(data, b):
    v = u16_le(data, b)
    return None if v is None else (v - 0x10000 if v >= 0x8000 else v)


def nearest(ts_vals, t, max_dt):
    """Binary-search nearest value within max_dt. Returns value or None."""
    if not ts_vals:
        return None
    lo, hi = 0, len(ts_vals) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if ts_vals[mid][0] < t:
            lo = mid + 1
        else:
            hi = mid
    best_i, best_dt = lo, abs(ts_vals[lo][0] - t)
    for i in (lo - 1, lo + 1):
        if 0 <= i < len(ts_vals):
            dt = abs(ts_vals[i][0] - t)
            if dt < best_dt:
                best_dt, best_i = dt, i
    return ts_vals[best_i][1] if best_dt <= max_dt else None


def pearson(xs, ys):
    n = len(xs)
    if n < 20:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n)
    if sx < 1e-9 or sy < 1e-9:
        return None
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / n / (sx * sy)


def interp_signal(ts_list, t_grid, max_dt=0.5):
    """Nearest-neighbour interpolate ts_list onto t_grid."""
    if len(ts_list) < 5:
        return None
    result = []
    for t in t_grid:
        v = nearest(ts_list, t, max_dt)
        if v is None:
            return None   # gap too large — skip this signal
        result.append(v)
    return result


# ── torque reference builder ────────────────────────────────────────────────────
def build_gen_reference(pt_ids):
    """
    Build (t_grid, T_gen_ref, RPM_gen_list) from PT bus data.

    Returns:
        t_grid      : list of timestamps (one per 0x598 frame with valid gen)
        T_gen_ref   : list of computed torque proxy values (I*V/RPM)
        RPM_gen     : list of generator RPM at same timestamps (for comparison)
        I_gen       : list of raw generator current counts
    """
    # Extract raw time-series for each signal
    hv_482   = []
    hv_dcdc  = []
    gen_cur  = []   # (t, I_gen) — 0x598 B2-B3 centered
    gen_rpm  = []   # (t, RPM)   — from 0x63C B6

    for t, dat in pt_ids.get(0x482, []):
        v = u16_le(dat, 1)
        if v is not None and v > 100:
            hv_482.append((t, float(v)))

    for t, dat in pt_ids.get(0x18FFD6B3, []):
        v = s16_le(dat, 4)
        if v is not None and v > 100:
            hv_dcdc.append((t, v * 0.05))

    for t, dat in pt_ids.get(0x598, []):
        b = u16_le(dat, 2)
        if b is not None:
            gen_cur.append((t, b - 32768))

    for t, dat in pt_ids.get(0x63C, []):
        if dat and len(dat) >= 7:
            b6 = dat[6]
            rpm = 16 * b6 - 96
            gen_rpm.append((t, rpm))

    if not gen_cur or not gen_rpm:
        return None, None, None, None

    # HV preference: 0x482, fallback to 0x18FFD6B3
    def get_hv(t):
        v = nearest(hv_482, t, MAX_DT_HV)
        if v is not None and v > 100:
            return v
        return nearest(hv_dcdc, t, MAX_DT_HV)

    # Build reference grid anchored on 0x598 timestamps
    t_grid, T_ref, RPM_out, I_out = [], [], [], []
    for t, i_gen in gen_cur:
        rpm = nearest(gen_rpm, t, MAX_DT_RPM)
        if rpm is None or rpm < RPM_GEN_MIN:
            continue
        v_hv = get_hv(t)
        if v_hv is None:
            continue
        # Torque proxy: proportional to I*V/omega (omit 2*pi/60 constant)
        T = i_gen * v_hv / rpm
        t_grid.append(t)
        T_ref.append(T)
        RPM_out.append(rpm)
        I_out.append(i_gen)

    return t_grid, T_ref, RPM_out, I_out


def build_drive_reference(pt_ids):
    """
    Build (t_grid, T_drive_ref, RPM_mtr_list, I_drv_list) from PT bus data.
    """
    hv_482  = []
    hv_dcdc = []
    drv_cur = []   # (t, I_drv) — 0x598 B4-B5 centered
    mtr_rpm = []   # (t, RPM)   — 0x5A2 B2-B3 centered

    for t, dat in pt_ids.get(0x482, []):
        v = u16_le(dat, 1)
        if v is not None and v > 100:
            hv_482.append((t, float(v)))

    for t, dat in pt_ids.get(0x18FFD6B3, []):
        v = s16_le(dat, 4)
        if v is not None and v > 100:
            hv_dcdc.append((t, v * 0.05))

    for t, dat in pt_ids.get(0x598, []):
        c = u16_le(dat, 4)
        if c is not None:
            drv_cur.append((t, c - 32768))

    for t, dat in pt_ids.get(0x5A2, []):
        r = u16_le(dat, 2)
        if r is not None:
            mtr_rpm.append((t, r - 32768))

    if not drv_cur or not mtr_rpm:
        return None, None, None, None

    def get_hv(t):
        v = nearest(hv_482, t, MAX_DT_HV)
        if v is not None and v > 100:
            return v
        return nearest(hv_dcdc, t, MAX_DT_HV)

    t_grid, T_ref, RPM_out, I_out = [], [], [], []
    for t, i_drv in drv_cur:
        rpm = nearest(mtr_rpm, t, MAX_DT_RPM)
        if rpm is None or abs(rpm) < RPM_MTR_MIN:
            continue
        v_hv = get_hv(t)
        if v_hv is None:
            continue
        # Torque proxy: proportional to I*V/omega (sign preserved)
        T = i_drv * v_hv / rpm
        t_grid.append(t)
        T_ref.append(T)
        RPM_out.append(rpm)
        I_out.append(i_drv)

    return t_grid, T_ref, RPM_out, I_out


# ── correlation scan ────────────────────────────────────────────────────────────
def scan_pt_bus(pt_ids, t_grid, T_ref, RPM_ref, label, out):
    """
    Correlate T_ref (and RPM_ref for comparison) against every byte/word on PT bus.
    Reports top candidates sorted by |r vs T_ref|.
    """
    def w(s):
        print(s)
        out.write(s + '\n')

    T_arr   = T_ref
    RPM_arr = RPM_ref

    results = []

    for mid, frame_list in pt_ids.items():
        if len(frame_list) < 30:
            continue
        max_dlc = max(len(d) for _, d in frame_list)

        # Per-byte
        for i in range(min(max_dlc, 8)):
            ts_list = [(t, d[i]) for t, d in frame_list if len(d) > i]
            sig = interp_signal(ts_list, t_grid)
            if sig is None:
                continue
            r_t   = pearson(T_arr, sig)
            r_rpm = pearson(RPM_arr, sig)
            # centered
            sig_c = [v - 128 for v in sig]
            r_tc  = pearson(T_arr, sig_c)
            r_rc  = pearson(RPM_arr, sig_c)
            best_rt  = max(r_t,  r_tc,  key=abs) if (r_t is not None and r_tc is not None) else (r_t or r_tc)
            best_rrpm = max(r_rpm, r_rc, key=abs) if (r_rpm is not None and r_rc is not None) else (r_rpm or r_rc)
            if best_rt is None:
                continue
            results.append((abs(best_rt), best_rt, best_rrpm, mid, f'B{i}'))

        # 2-byte LE and BE, centered at 32768
        for i in range(min(max_dlc, 8) - 1):
            j = i + 1
            for endian, blabel in [('LE', f'B{i}-B{j} LE'), ('BE', f'B{i}-B{j} BE')]:
                if endian == 'LE':
                    ts_raw = [(t, (d[j] << 8) | d[i]) for t, d in frame_list if len(d) > j]
                else:
                    ts_raw = [(t, (d[i] << 8) | d[j]) for t, d in frame_list if len(d) > j]
                sig_raw = interp_signal(ts_raw, t_grid)
                if sig_raw is None:
                    continue
                sig_cen = [v - 32768 for v in sig_raw]
                for slabel, sig in [(blabel, sig_raw), (blabel + '-32768', sig_cen)]:
                    r_t   = pearson(T_arr, sig)
                    r_rpm = pearson(RPM_arr, sig)
                    if r_t is None:
                        continue
                    results.append((abs(r_t), r_t, r_rpm, mid, slabel))

    results.sort(reverse=True)

    w(f"\n{'=' * 80}")
    w(f"TORQUE FEEDBACK SEARCH — {label}")
    w(f"  Reference grid: {len(t_grid)} samples  "
      f"(T_ref range: {min(T_ref):.1f} to {max(T_ref):.1f})")
    w(f"  RPM range: {min(RPM_ref):.0f} to {max(RPM_ref):.0f}  "
      f"  I range: (see T_ref)")
    w(f"  Scanning {len(pt_ids)} IDs on PT bus.")
    w(f"{'=' * 80}")
    w(f"  {'Msg':>8}  {'Signal':<30}  {'|r| vs T':>9}  {'r vs T':>9}  {'r vs RPM':>9}")
    w("-" * 74)

    seen  = set()
    shown = 0
    for best_r, r_t, r_rpm, mid, sig_label in results:
        # Deduplicate by (mid, byte-position root)
        root = sig_label.split('-32768')[0].split(' LE')[0].split(' BE')[0]
        key  = (mid, root)
        if key in seen:
            continue
        seen.add(key)
        r_rpm_s = f"{r_rpm:+.4f}" if r_rpm is not None else "    N/A"
        w(f"  0x{mid:06X}  {sig_label:<30}  {best_r:9.4f}  {r_t:+9.4f}  {r_rpm_s}")
        shown += 1
        if shown >= TOP_N:
            break


# ── main ───────────────────────────────────────────────────────────────────────
def run(log_path, build_ref_fn, ref_label, out):
    def w(s):
        print(s)
        out.write(s + '\n')

    w(f"\n{'#' * 80}")
    w(f"# LOG: {log_path.name}")
    w(f"# REF: {ref_label}")
    w(f"{'#' * 80}")

    if not log_path.exists():
        w(f"  ERROR: log file not found: {log_path}")
        return

    w(f"  Parsing log ...")
    buses = parse_log(log_path)
    pt_bus = find_pt_bus(buses)
    if pt_bus is None:
        w(f"  ERROR: could not identify PT bus (no 0x051 found).")
        return
    w(f"  PT bus: {pt_bus}  ({len(buses[pt_bus])} unique IDs)")

    pt_ids = buses[pt_bus]
    t_grid, T_ref, RPM_ref, I_ref = build_ref_fn(pt_ids)
    if t_grid is None or len(t_grid) < 50:
        w(f"  ERROR: insufficient reference data (n={len(t_grid) if t_grid else 0}).")
        w(f"  Check that the log contains generator/motor activity above RPM threshold.")
        return

    w(f"  Reference built: {len(t_grid)} valid frames")
    w(f"  T_ref range : {min(T_ref):.2f} to {max(T_ref):.2f}")
    w(f"  RPM range   : {min(RPM_ref):.0f} to {max(RPM_ref):.0f} RPM")
    w(f"  I range     : {min(I_ref):.0f} to {max(I_ref):.0f} counts")

    scan_pt_bus(pt_ids, t_grid, T_ref, RPM_ref, ref_label, out)


def main():
    out = open(OUTPUT_FILE, 'w')
    out.write("find_torque_feedback.py — torque feedback search via T = P/omega\n")
    out.write(f"Logs: {LOG_GEN.name}, {LOG_DRIVE.name}\n\n")

    # ---- Generator torque search ----
    run(LOG_GEN, build_gen_reference,
        "GENERATOR TORQUE  (0x598 B2-B3 * V_HV / 0x63C RPM)", out)

    # ---- Drivetrain torque search ----
    run(LOG_DRIVE, build_drive_reference,
        "DRIVETRAIN TORQUE  (0x598 B4-B5 * V_HV / 0x5A2 RPM)", out)

    out.close()
    print(f"\nResults written to: {OUTPUT_FILE.name}")


if __name__ == "__main__":
    main()
