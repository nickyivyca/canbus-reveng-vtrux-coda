"""
rpm_correlation_scan.py

Correlates every PT bus byte and 16-bit word against OBD engine RPM.

Log: vtruxgeneratoroverheattest.log (Bus1=OBD, Bus2=Vehicle, Bus3=PT)

Reference: OBD bus, ID 0x0C9, Motorola B1-B2: (B1<<8 | B2) * 0.25 RPM

Context: 0x63C B6 is the known generator RPM signal (16 RPM/count, zero at B6=6),
but it overflows above ~4000 RPM (B6 wraps 255->0, no carry). This scan looks for
any other PT bus signals that track generator/engine RPM, especially through the
high-RPM region only reachable during this abnormal-thermal test.

Two correlation modes per signal:
  1. Full-log Pearson r (engine-running frames only: OBD RPM > 200)
  2. High-RPM-only r (frames where OBD RPM > 3500 -- above normal operating range,
     only these frames distinguish an overflow-immune signal from 0x63C B6)

For 16-bit words, test both LE uint16 raw and LE uint16 centered at 32768.

Strategy for speed: pre-compute interpolated OBD RPM at every PT bus frame
timestamp during the single parse pass. All correlation work then operates
only on pre-built arrays -- no repeated log scans.

Usage: run from project root
    py -3.12 projects/vtrux/notes/artifacts/rpm_correlation_scan.py
"""

import math
import sys
from bisect import bisect_left
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from canre.parsers import parse_file

LOG = "projects/vtrux/logs/vtruxgeneratoroverheattest.log"
OUT = "projects/vtrux/notes/artifacts/rpm_correlation_scan.txt"

# Bus anchor IDs
PT_ANCHORS     = {0x051}
GM_OBD_ANCHORS = {0x040, 0x041, 0x042, 0x043, 0x044}
GM_UNF_ANCHORS = {0x1E5, 0x500}

# Known-attributed PT bus IDs (flagged in output, not excluded)
KNOWN_IDS = {
    0x051, 0x052, 0x308,
    0x395, 0x390,
    0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460,
    0x470, 0x471, 0x472, 0x479, 0x480, 0x481, 0x482, 0x483, 0x484,
    0x505, 0x506, 0x507, 0x55C, 0x580,
    0x592, 0x594, 0x595, 0x596, 0x597, 0x598, 0x599, 0x5A0, 0x5A2,
    0x600, 0x601, 0x617, 0x619, 0x61F, 0x625, 0x626, 0x62F,
    0x63C,  # the overflowing RPM signal itself
    0x639, 0x63A, 0x63D, 0x63F,
    0x640, 0x644, 0x645, 0x646, 0x647, 0x648, 0x649, 0x64A, 0x64B, 0x651,
    0x370, 0x371, 0x372, 0x373, 0x374, 0x375,
    0x6A0, 0x681,
    0x08C,
}


def detect_buses(log_path, max_scan=200_000):
    found = {}
    for frame in parse_file(log_path):
        cid = frame.arbitration_id
        b = frame.bus
        if cid in PT_ANCHORS and "PT" not in found:
            found["PT"] = b
        if cid in GM_OBD_ANCHORS and "GM_OBD" not in found:
            found["GM_OBD"] = b
        if cid in GM_UNF_ANCHORS and "GM_UNF" not in found:
            found["GM_UNF"] = b
        if len(found) == 3:
            break
        max_scan -= 1
        if max_scan <= 0:
            break
    return found


def interp_sorted(xs, ys, x):
    """Fast interpolation assuming xs is sorted. Returns None if out of range."""
    if x < xs[0] or x > xs[-1]:
        return None
    i = bisect_left(xs, x)
    if i == 0:
        return ys[0]
    if i >= len(xs):
        return ys[-1]
    x0, x1 = xs[i - 1], xs[i]
    y0, y1 = ys[i - 1], ys[i]
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def pearson(xs, ys):
    """Pearson r. Returns (r, n) or (None, n) if degenerate."""
    n = len(xs)
    if n < 10:
        return None, n
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx < 1e-9 or dy < 1e-9:
        return None, n
    return num / (dx * dy), n


def main():
    print("Detecting buses...", file=sys.stderr)
    buses = detect_buses(LOG)
    print(f"  Buses: {buses}", file=sys.stderr)
    if "PT" not in buses or "GM_OBD" not in buses:
        print("ERROR: could not identify PT or GM_OBD bus", file=sys.stderr)
        sys.exit(1)

    pt_bus  = buses["PT"]
    obd_bus = buses["GM_OBD"]

    # First pass: collect OBD RPM timestamps and values
    print("Pass 1: collecting OBD RPM...", file=sys.stderr)
    obd_rpm_ts   = []
    obd_rpm_vals = []
    for frame in parse_file(LOG):
        if frame.bus == obd_bus and frame.arbitration_id == 0x0C9 and len(frame.data) >= 3:
            d = frame.data
            rpm = ((d[1] << 8) | d[2]) * 0.25
            obd_rpm_ts.append(frame.timestamp)
            obd_rpm_vals.append(rpm)
    print(f"  OBD RPM frames: {len(obd_rpm_ts)}", file=sys.stderr)

    # Second pass: collect PT bus frames, pre-interpolate RPM at each PT timestamp
    # Storage per (arb_id, byte_pos): list of (byte_val, interp_rpm)
    # Only standard-frame IDs; only frames where engine is running (rpm > 200)
    print("Pass 2: collecting PT bus frames + interpolating RPM...", file=sys.stderr)

    # pt_byte_data[(cid, bi)] = [(byte_val, rpm), ...]  -- engine running only
    # pt_byte_hi[(cid, bi)]   = [(byte_val, rpm), ...]  -- rpm > 3500 only
    pt_byte_data = defaultdict(list)
    pt_byte_hi   = defaultdict(list)

    # For 16-bit word construction: track (cid, frame_t) -> data bytes
    # We'll build word data in a third pass from the byte data
    # But we need paired samples from the same frame.
    # Strategy: buffer each frame's all-byte values + pre-computed rpm.
    # Keep a ring-buffer of last frame per (cid) to pair bytes.
    # Actually: just store (t, rpm, data[]) for each PT frame when rpm>200.
    pt_frames_running = defaultdict(list)  # cid -> [(rpm, data_bytes)]
    pt_frames_hi      = defaultdict(list)  # cid -> [(rpm, data_bytes)]

    pt_id_dlc = {}
    frame_count = 0
    for frame in parse_file(LOG):
        if frame.bus == pt_bus and not frame.is_extended:
            cid = frame.arbitration_id
            d = frame.data
            t = frame.timestamp
            dlc = len(d)
            pt_id_dlc[cid] = max(pt_id_dlc.get(cid, 0), dlc)

            rpm = interp_sorted(obd_rpm_ts, obd_rpm_vals, t)
            if rpm is None:
                continue

            if rpm > 200:
                pt_frames_running[cid].append((rpm, bytes(d)))
            if rpm > 3500:
                pt_frames_hi[cid].append((rpm, bytes(d)))

            frame_count += 1

    print(f"  PT standard frames parsed: {frame_count}", file=sys.stderr)
    print(f"  PT IDs: {len(pt_id_dlc)}", file=sys.stderr)
    print(f"  IDs with any engine-running frames: "
          f"{sum(1 for cid in pt_frames_running if pt_frames_running[cid])}", file=sys.stderr)

    # Build correlations
    print("Computing correlations...", file=sys.stderr)

    # (cid, label, r_full, n_full, r_hi, n_hi)
    results = []

    all_cids = set(pt_frames_running.keys()) | set(pt_frames_hi.keys())
    for cid in sorted(all_cids):
        dlc = pt_id_dlc.get(cid, 0)

        frames_run = pt_frames_running.get(cid, [])
        frames_hi  = pt_frames_hi.get(cid, [])

        # Per-byte correlations
        for bi in range(dlc):
            # Full-log (engine running)
            sig_run = [d[bi] for rpm, d in frames_run if bi < len(d)]
            rpm_run = [rpm   for rpm, d in frames_run if bi < len(d)]
            r_full, n_full = pearson(sig_run, rpm_run)

            # High-RPM only
            sig_hi = [d[bi] for rpm, d in frames_hi if bi < len(d)]
            rpm_hi = [rpm   for rpm, d in frames_hi if bi < len(d)]
            r_hi, n_hi = pearson(sig_hi, rpm_hi)

            results.append((cid, f"B{bi}", r_full, n_full, r_hi, n_hi))

        # LE uint16 word correlations (adjacent byte pairs)
        for bi in range(dlc - 1):
            bj = bi + 1

            # Raw LE uint16
            sig_run_le = [(d[bj] << 8) | d[bi] for rpm, d in frames_run
                          if bi < len(d) and bj < len(d)]
            rpm_run_le = [rpm for rpm, d in frames_run if bi < len(d) and bj < len(d)]
            r_le_full, n_le_full = pearson(sig_run_le, rpm_run_le)

            sig_hi_le = [(d[bj] << 8) | d[bi] for rpm, d in frames_hi
                         if bi < len(d) and bj < len(d)]
            rpm_hi_le = [rpm for rpm, d in frames_hi if bi < len(d) and bj < len(d)]
            r_le_hi, n_le_hi = pearson(sig_hi_le, rpm_hi_le)

            results.append((cid, f"le16_B{bi}B{bj}", r_le_full, n_le_full, r_le_hi, n_le_hi))

            # Centered LE uint16 (common offset-binary encoding)
            sig_run_c = [v - 32768 for v in sig_run_le]
            sig_hi_c  = [v - 32768 for v in sig_hi_le]
            r_c_full, n_c_full = pearson(sig_run_c, rpm_run_le)
            r_c_hi,   n_c_hi   = pearson(sig_hi_c,  rpm_hi_le)

            results.append((cid, f"le16cent_B{bi}B{bj}", r_c_full, n_c_full, r_c_hi, n_c_hi))

    # Sort by best |r| across all modes
    def sort_key(row):
        _, _, r_full, _, r_hi, _ = row
        vals = [abs(v) for v in [r_full, r_hi] if v is not None]
        return max(vals) if vals else 0.0

    results.sort(key=sort_key, reverse=True)

    # Write output
    with open(OUT, "w", encoding="ascii") as f:
        f.write("RPM Correlation Scan -- vtruxgeneratoroverheattest.log\n")
        f.write("Reference: OBD 0x0C9 (B1-B2 Motorola) * 0.25 RPM\n")
        f.write(f"OBD RPM frames: {len(obd_rpm_ts)}\n")
        f.write(f"PT standard-frame IDs: {len(pt_id_dlc)}\n")
        f.write("\n")
        f.write(f"{'ID':>8}  {'Signal':<22}  {'r_full(>200)':>13}  {'n_full':>7}  "
                f"{'r_hi(>3500)':>12}  {'n_hi':>6}  {'known':>5}\n")
        f.write("-" * 90 + "\n")
        for row in results:
            cid, label, r_full, n_full, r_hi, n_hi = row
            r_full_s = f"{r_full:+.4f}" if r_full is not None else "    N/A "
            r_hi_s   = f"{r_hi:+.4f}"   if r_hi   is not None else "    N/A "
            n_full_s = f"{n_full:7d}"    if n_full  else "      0"
            n_hi_s   = f"{n_hi:6d}"      if n_hi    else "     0"
            known_s  = "  yes" if cid in KNOWN_IDS else "   no"
            f.write(f"  0x{cid:04X}  {label:<22}  {r_full_s:>13}  {n_full_s}  "
                    f"{r_hi_s:>12}  {n_hi_s}  {known_s}\n")

    print(f"Done. Output -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
