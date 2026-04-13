"""
seasonal_batt_temp.py  --  V3 seasonal temperature check

Auto-discovers charge sessions from specified log directories.
For each session, uses only the first T-chunk (T0) to get the starting temperature.

Steps per session:
  1. Quick-scan first 500 frames: if none of the target BMS IDs appear AND extended
     frames do appear, flag as "extended-only filtered" and skip.
  2. Skip startup artifact (first STARTUP_SKIP frames per ID).
  3. Record first stable value and last value for each signal.
  4. Parse BUSMASTER header for session date.

Temperature candidates:
  0x373 B3  -- battery internal temp  (raw - 40 = degC)
  0x507 B0  -- sensor candidate 1     (raw - 40 = degC, filter 0x7F)
  0x507 B1  -- sensor candidate 2     (raw - 40 = degC, filter 0x7F)
  0x430 B4  -- candidate alt. scale   (raw - 100 = degC, provisional)
  0x430 B5  -- candidate alt. scale   (raw - 100 = degC, provisional)

Usage:
  py -3.12 seasonal_batt_temp.py [--out seasonal_batt_temp.txt]
"""
import sys
import re
import argparse
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from canre.parsers.autodetect import parse_file

ARTIFACTS = Path(__file__).parent
VTRUX     = ROOT / "projects/vtrux"
ANCHOR_ID = 0x051   # PT bus marker

SIGNALS = [
    # (can_id, byte_idx, label, display_offset, invalid_sentinels)
    (0x373, 3, "B3_0x373", 40,  set()),
    (0x507, 0, "B0_0x507", 40,  {127}),
    (0x507, 1, "B1_0x507", 40,  {127}),
    (0x430, 4, "B4_0x430", 100, {254}),
    (0x430, 5, "B5_0x430", 100, {254}),
]
BMS_IDS    = {s[0] for s in SIGNALS}   # standard frame IDs to look for
STARTUP_SKIP = 6                        # frames to discard per ID (boot artifact)
QUICK_SCAN   = 1000                     # frames to check for BMS presence

# ---- Directories to scan ----
# Each entry: (directory path, glob pattern for charge-like filenames)
SCAN_DIRS = [
    # Bel Inverter other-logs -- exclude truklog and belre (drive logs)
    (VTRUX / "Bel-Inverter/other-logs",
     lambda name: (
         name.endswith(".log") and
         not name.lower().startswith("truklog") and
         not name.lower().startswith("belre") and
         not name.lower().startswith("truk") and
         not name.lower().startswith("trunk")
     )),
    # After battery swap charges
    (VTRUX / "logs/after-battery-swap-charges",
     lambda name: name.endswith(".log")),
    # Main logs: specific named charge files
    (VTRUX / "logs",
     lambda name: name in {
         "chargedown.log",
         "full charge then fail.log",
         "rainychargedebug.log",
         "rainychargedebug2.log",
         "rainychargedebug3.log",
         "rainychargedebug4.log",
         "chargingafterturningaroundandnotusingextension.log",
         "vtruxchargeafterevaplog-failed.log",
         "vtruxchargeafterevaplogattempt2.log",
     }),
    # After fix charges
    (VTRUX / "logs/after fix charge",
     lambda name: name.endswith(".log")),
]


def session_key(path):
    """
    Strip _T<digits> suffix to get session group key.
    E.g. chargelog_M1.log -> chargelog_M1
         charge_M0_T5.log -> charge_M0
         212charge_M1_T3.log -> 212charge_M1
    """
    stem = path.stem
    # Remove trailing _T<digits>
    stem = re.sub(r'_[Tt]\d+$', '', stem)
    return (str(path.parent), stem)


def chunk_number(path):
    """Return T-chunk number, or -1 if not chunked."""
    m = re.search(r'_[Tt](\d+)$', path.stem)
    return int(m.group(1)) if m else -1


def busmaster_date(path):
    """Parse date from BUSMASTER header. Returns datetime or None."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                m = re.search(
                    r'START DATE AND TIME\s+(\d+):(\d+):(\d+)\s+(\d+):(\d+):(\d+)',
                    line)
                if m:
                    d, mo, yr, h, mi, s = map(int, m.groups())
                    try:
                        return datetime(yr, mo, d, h, mi, s)
                    except ValueError:
                        return None
    except Exception:
        pass
    return None


def quick_check_bms(path):
    """
    Scan first QUICK_SCAN frames.
    Returns (has_bms, has_extended_only).
      has_bms: at least one of BMS_IDS seen as standard frame
      has_extended_only: no standard BMS IDs, but 29-bit frames present
    """
    bms_seen = False
    extended_seen = False
    n = 0
    try:
        for frame in parse_file(path):
            if frame.is_extended:
                extended_seen = True
            elif frame.arbitration_id in BMS_IDS:
                bms_seen = True
            n += 1
            if n >= QUICK_SCAN and bms_seen:
                break
    except Exception:
        pass
    extended_only = (not bms_seen) and extended_seen
    return bms_seen, extended_only


def find_pt_bus(path, max_frames=5000):
    """Find PT bus by scanning for ANCHOR_ID."""
    n = 0
    try:
        for frame in parse_file(path):
            if frame.arbitration_id == ANCHOR_ID:
                return frame.bus
            n += 1
            if n >= max_frames:
                break
    except Exception:
        pass
    return None


def extract_first_last(path, pt_bus):
    """
    Stream path, return dict:
      label -> (first_stable_raw, last_raw, n_samples)
    """
    counts   = {(c, b): 0    for c, b, *_ in SIGNALS}
    first_v  = {(c, b): None for c, b, *_ in SIGNALS}
    last_v   = {(c, b): None for c, b, *_ in SIGNALS}
    n_samp   = {(c, b): 0    for c, b, *_ in SIGNALS}
    sentinel = {(c, b): inv  for c, b, _, _, inv in SIGNALS}

    try:
        for frame in parse_file(path):
            if frame.bus != pt_bus:
                continue
            for c, b, *_ in SIGNALS:
                if frame.arbitration_id == c and len(frame.data) > b:
                    val = frame.data[b]
                    if val in sentinel[(c, b)]:
                        continue
                    counts[(c, b)] += 1
                    if counts[(c, b)] > STARTUP_SKIP:
                        if first_v[(c, b)] is None:
                            first_v[(c, b)] = val
                        last_v[(c, b)] = val
                        n_samp[(c, b)] += 1
    except Exception as e:
        print("    parse error: {}".format(e))

    result = {}
    for c, b, label, offset, _ in SIGNALS:
        fv = first_v[(c, b)]
        lv = last_v[(c, b)]
        n  = n_samp[(c, b)]
        if fv is not None:
            result[label] = (fv, lv, n, fv - offset, lv - offset)
    return result


def discover_sessions(scan_dirs):
    """
    Returns list of (session_key, [path, ...]) sorted by session_key.
    Groups T-chunks together. Each group's paths are sorted by chunk number.
    """
    groups = {}
    for dirpath, name_filter in scan_dirs:
        if not dirpath.exists():
            print("  Directory not found, skipping: {}".format(dirpath))
            continue
        for p in sorted(dirpath.iterdir()):
            if p.is_file() and name_filter(p.name):
                key = session_key(p)
                groups.setdefault(key, []).append(p)

    # Sort paths within each group by chunk number
    for key in groups:
        groups[key].sort(key=chunk_number)

    return sorted(groups.items(), key=lambda x: x[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ARTIFACTS / "seasonal_batt_temp.txt"))
    args = ap.parse_args()

    sessions = discover_sessions(SCAN_DIRS)
    print("Found {} sessions across all scan directories.".format(len(sessions)))
    print()

    rows = []

    for (dir_str, sess_name), paths in sessions:
        # Use T0 (first chunk) for starting temperature
        t0_path = paths[0]
        last_path = paths[-1]  # last chunk for final temperature

        print("Session: {}  ({} chunks)".format(sess_name, len(paths)))

        # Date from first chunk header
        dt = busmaster_date(t0_path)

        # BMS presence check on T0
        has_bms, ext_only = quick_check_bms(t0_path)
        if ext_only:
            print("  SKIP: extended-ID-only log (BMS standard frames absent)")
            rows.append((dt, sess_name, None, "ext-only"))
            continue
        if not has_bms:
            print("  SKIP: no BMS IDs found in first {} frames".format(QUICK_SCAN))
            rows.append((dt, sess_name, None, "no-bms"))
            continue

        # Find PT bus
        pt_bus = find_pt_bus(t0_path)
        if pt_bus is None:
            print("  SKIP: PT bus not found")
            rows.append((dt, sess_name, None, "no-pt-bus"))
            continue

        # Extract first stable values from T0
        first_sigs = extract_first_last(t0_path, pt_bus)

        # Extract last values from final chunk (may be same as T0 if single file)
        if last_path != t0_path:
            pt_bus_last = find_pt_bus(last_path) or pt_bus
            last_sigs = extract_first_last(last_path, pt_bus_last)
        else:
            last_sigs = first_sigs

        rows.append((dt, sess_name, (first_sigs, last_sigs), "ok"))
        date_str = dt.strftime("%Y-%m-%d") if dt else "???"
        if first_sigs:
            b3 = first_sigs.get("B3_0x373")
            b3_str = "B3={} ({:+.0f}degC)".format(b3[0], b3[3]) if b3 else "B3=---"
            print("  {} -- {}".format(date_str, b3_str))
        else:
            print("  {} -- no signal data".format(date_str))

    # ---- Report ----
    labels = [s[2] for s in SIGNALS]
    col_w  = 14

    header_1 = "{:<26} {:<13}  {}  {}".format(
        "Session", "Date",
        "  ".join("{:>{}}".format(lb[:col_w], col_w) for lb in labels),
        "  ".join("{:>{}}".format(lb[:col_w]+"_last", col_w) for lb in labels),
    )
    sep = "-" * len(header_1)

    output_lines = [
        "Seasonal Battery Temperature Survey",
        "Signals: 0x373B3/0x507B0/B1 use raw-40=degC; 0x430B4/B5 use raw-100=degC (provisional)",
        "Values shown: first_stable_raw(degC) from T0 | last_raw(degC) from final chunk",
        "",
        header_1,
        sep,
    ]

    # Sort by date, unknown date at end
    rows_sorted = sorted(rows,
                         key=lambda x: x[0] if x[0] else datetime(2099, 1, 1))

    for dt, name, data, status in rows_sorted:
        date_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "UNKNOWN"
        if status != "ok" or data is None:
            note = "[{}]".format(status)
            line = "{:<26} {:<13}  {}".format(name[:26], date_str, note)
        else:
            first_sigs, last_sigs = data
            first_cells = []
            last_cells  = []
            for label in labels:
                if label in first_sigs:
                    fv, lv, n, f_degC, l_degC = first_sigs[label]
                    first_cells.append("{:>4}({:>+3.0f}degC)".format(fv, f_degC))
                else:
                    first_cells.append("{:>{}}".format("---", col_w))
                if label in last_sigs:
                    fv2, lv2, n2, f2, l2 = last_sigs[label]
                    last_cells.append("{:>4}({:>+3.0f}degC)".format(lv2, l2))
                else:
                    last_cells.append("{:>{}}".format("---", col_w))
            line = "{:<26} {:<13}  {}  {}".format(
                name[:26], date_str,
                "  ".join(first_cells),
                "  ".join(last_cells),
            )
        output_lines.append(line)

    output_lines.append(sep)
    output = "\n".join(output_lines)

    print()
    print(output)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(output + "\n")
    print()
    print("Saved: {}".format(Path(args.out).name))


if __name__ == "__main__":
    main()
