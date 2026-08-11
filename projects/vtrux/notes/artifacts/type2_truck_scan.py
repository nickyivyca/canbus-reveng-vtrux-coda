"""
type2_truck_scan.py

Scan all Vtrux log files (primary + Android backup) for bcm_alarm=TYPE2
and HCU software version. Groups results by:
  - Pre/post battery swap (2025-12-09)
  - Truck identity derived from odometer (0x0625 B0:B1:B2 big-endian raw count)

Goal: determine whether TYPE2 alarm follows the battery pack (battery issue)
or follows the truck chassis (truck-level issue).

bcm_alarm is B1[7:6] of 0x0410: 0=NONE, 1=TYPE1, 2=TYPE2, 3=TYPE3
Odometer: 0x0625 B0:B1:B2 big-endian (K2XX variant if B3 < 0x20)
HCU version: 0x062F MajorVersion=B1[6:0], MinorVersion=B2

Expected odometer ranges (raw counts, scale unconfirmed but 1 km/count likely):
  Main truck:  ~95000+ (odometer read 0x017556=95574 on 2025-10-25)
  Parts truck: lower (unknown, but clearly distinct from main)
Threshold for truck ID: ODO_MAIN_THRESHOLD (tunable below)

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/type2_truck_scan.py
"""

import os
import sys
import re
from datetime import date, datetime

SWAP_DATE = date(2025, 12, 9)
ODO_MAIN_THRESHOLD = 50000

PRIMARY_LOG_ROOT = "projects/vtrux/logs"
ANDROID_LOG_DIR = "../../CANLogs/VtruxLogs"

ALARM_NAMES = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3", None: "---"}


def busmaster_parse_target_line(line, hex_mode=True):
    """
    Parse a single BUSMASTER data line for target IDs (0x0410, 0x062F, 0x0625).
    Returns (rel_timestamp_s, arb_id, data_bytes) or None if not a target line.
    """
    parts = line.split()
    if len(parts) < 6:
        return None
    ts_tok = parts[0]
    if ':' not in ts_tok:
        return None
    try:
        arb_id = int(parts[3], 16)
    except (ValueError, IndexError):
        return None
    if arb_id not in (0x0410, 0x062F, 0x0625):
        return None
    try:
        ts_parts = ts_tok.split(':')
        if len(ts_parts) != 4:
            return None
        ts = int(ts_parts[0]) * 3600 + int(ts_parts[1]) * 60 + int(ts_parts[2]) + int(ts_parts[3]) * 0.0001
        dlc = int(parts[5])
        base = 16 if hex_mode else 10
        data = bytes(int(x, base) for x in parts[6:6 + dlc])
        return (ts, arb_id, data)
    except Exception:
        return None


def get_log_date(filepath, filename):
    """Extract date from filename YYYYMMDD pattern, fall back to mtime."""
    m = re.search(r'(\d{8})', filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            pass
    try:
        return date.fromtimestamp(os.path.getmtime(filepath))
    except OSError:
        return None


def scan_file(filepath):
    """
    Fast scan: read file line by line, only parse lines with target IDs.
    Returns dict with: has_pt_bus, hcu_version, odo, type2_count,
                       alarm_transitions, first_ts, last_ts, error
    """
    result = {
        "has_pt_bus": False,
        "hcu_version": None,
        "odo": None,
        "type2_count": 0,
        "alarm_transitions": [],
        "first_ts": None,
        "last_ts": None,
        "error": None,
    }
    hex_mode = True
    first_ts_abs = None
    prev_alarm = None

    try:
        with open(filepath, "r", errors="replace") as f:
            for line in f:
                if "***HEX***" in line:
                    hex_mode = True
                    continue
                if "***DEC***" in line:
                    hex_mode = False
                    continue

                parsed = busmaster_parse_target_line(line, hex_mode)
                if parsed is None:
                    continue

                ts_abs, arb_id, data = parsed

                if first_ts_abs is None:
                    first_ts_abs = ts_abs
                result["last_ts"] = ts_abs - first_ts_abs

                ts_rel = ts_abs - first_ts_abs

                if arb_id == 0x062F and result["hcu_version"] is None:
                    if len(data) >= 3:
                        major = data[1] & 0x7F
                        minor = data[2]
                        result["hcu_version"] = (major, minor)

                elif arb_id == 0x0625 and result["odo"] is None:
                    if len(data) >= 3:
                        result["odo"] = (data[0] << 16) | (data[1] << 8) | data[2]

                elif arb_id == 0x0410:
                    result["has_pt_bus"] = True
                    if len(data) >= 2:
                        alarm = (data[1] >> 6) & 3
                        if alarm == 2:
                            result["type2_count"] += 1
                        if alarm != prev_alarm:
                            result["alarm_transitions"].append((ts_rel, prev_alarm, alarm))
                            prev_alarm = alarm

                if result["first_ts"] is None and result["has_pt_bus"]:
                    result["first_ts"] = 0.0

    except Exception as e:
        result["error"] = str(e)

    return result


def truck_label(odo):
    """Return truck identity string based on odometer raw value."""
    if odo is None:
        return "TRUCK?  (no odo)"
    if odo >= ODO_MAIN_THRESHOLD:
        return "MAIN    (high-odo ~%dk)" % (odo // 1000)
    else:
        return "PARTS   (low-odo  ~%dk)" % (odo // 1000)


def collect_log_files(root, recursive=True):
    """Yield (filepath, filename) for all .log files under root."""
    if not os.path.isdir(root):
        return
    if recursive:
        for dirpath, _, filenames in os.walk(root):
            for fn in sorted(filenames):
                if fn.lower().endswith(".log"):
                    yield os.path.join(dirpath, fn), fn
    else:
        for fn in sorted(os.listdir(root)):
            if fn.lower().endswith(".log"):
                yield os.path.join(root, fn), fn


def format_transitions(transitions):
    """Compact summary of alarm state transitions."""
    if not transitions:
        return "(no 0x0410 frames)"
    parts = []
    for ts, frm, to in transitions:
        frm_s = ALARM_NAMES.get(frm, str(frm))
        to_s = ALARM_NAMES.get(to, str(to))
        parts.append("%s->%s @%.0fs" % (frm_s, to_s, ts))
    return "  ".join(parts)


def main():
    all_logs = []

    print("Collecting log files...", file=sys.stderr)

    for filepath, filename in collect_log_files(PRIMARY_LOG_ROOT, recursive=True):
        log_date = get_log_date(filepath, filename)
        all_logs.append((filepath, filename, log_date, "primary"))

    android_count = 0
    for filepath, filename in collect_log_files(ANDROID_LOG_DIR, recursive=False):
        log_date = get_log_date(filepath, filename)
        all_logs.append((filepath, filename, log_date, "android"))
        android_count += 1

    print("Found %d primary + %d Android logs. Scanning..." % (
        len(all_logs) - android_count, android_count), file=sys.stderr)

    results = []
    for i, (filepath, filename, log_date, source) in enumerate(all_logs):
        if i % 50 == 0:
            print("  %d/%d..." % (i, len(all_logs)), file=sys.stderr)
        stats = scan_file(filepath)
        results.append({
            "filepath": filepath,
            "filename": filename,
            "date": log_date,
            "source": source,
            **stats,
        })

    print("Scan complete. Building report...\n", file=sys.stderr)

    pt_results = [r for r in results if r["has_pt_bus"]]
    skipped = len(results) - len(pt_results)

    print("=" * 90)
    print("TYPE2 ALARM + HCU SOFTWARE VERSION SURVEY")
    print("Battery swap date: %s" % SWAP_DATE)
    print("Truck ID threshold: odo raw > %d = MAIN truck" % ODO_MAIN_THRESHOLD)
    print("bcm_alarm B1[7:6] of 0x0410  |  HCU version: 0x062F B1[6:0].B2")
    print("Skipped %d files with no PT bus (0x0410 absent)" % skipped)
    print("=" * 90)

    pt_results.sort(key=lambda r: (r["date"] or date.min))

    pre_swap = [r for r in pt_results if r["date"] and r["date"] < SWAP_DATE]
    post_swap = [r for r in pt_results if r["date"] and r["date"] >= SWAP_DATE]
    unknown_date = [r for r in pt_results if not r["date"]]

    def print_section(section_name, rows):
        if not rows:
            print("\n  (none)\n")
            return
        print()
        header = "%-12s  %-20s  %-8s  %-8s  %-8s  %-28s  %s" % (
            "DATE", "TRUCK", "ODO_RAW", "HCU_VER", "TYPE2", "ALARM TRANSITIONS", "FILE")
        print("  " + header)
        print("  " + "-" * 130)
        for r in rows:
            date_s = str(r["date"]) if r["date"] else "??-??-??"
            truck_s = truck_label(r["odo"])
            odo_s = str(r["odo"]) if r["odo"] is not None else "none"
            ver_s = "v%d.%d" % r["hcu_version"] if r["hcu_version"] else "none"
            type2_s = "YES (%d)" % r["type2_count"] if r["type2_count"] > 0 else "no"
            transitions_s = format_transitions(r["alarm_transitions"][:6])
            if len(r["alarm_transitions"]) > 6:
                transitions_s += "  [+%d more]" % (len(r["alarm_transitions"]) - 6)
            short_name = os.path.relpath(r["filepath"], PRIMARY_LOG_ROOT)
            if r["source"] == "android":
                short_name = "android/" + r["filename"]
            print("  %-12s  %-20s  %-8s  %-8s  %-8s  %-28s  %s" % (
                date_s, truck_s, odo_s, ver_s, type2_s, transitions_s, short_name))

    print("\n\n### PRE-SWAP (before %s) ###" % SWAP_DATE)
    print_section("pre-swap", pre_swap)

    print("\n\n### POST-SWAP (on or after %s) ###" % SWAP_DATE)
    print_section("post-swap", post_swap)

    if unknown_date:
        print("\n\n### UNKNOWN DATE ###")
        print_section("unknown", unknown_date)

    print("\n\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)

    def summarize(rows, label):
        if not rows:
            print("  %s: 0 logs" % label)
            return
        main_rows = [r for r in rows if r["odo"] and r["odo"] >= ODO_MAIN_THRESHOLD]
        parts_rows = [r for r in rows if r["odo"] and r["odo"] < ODO_MAIN_THRESHOLD]
        noodo_rows = [r for r in rows if r["odo"] is None]
        for subset, sublabel in [(main_rows, "MAIN truck"), (parts_rows, "PARTS truck"), (noodo_rows, "no-odo")]:
            if not subset:
                continue
            with_t2 = [r for r in subset if r["type2_count"] > 0]
            hcu_vers = sorted(set(r["hcu_version"] for r in subset if r["hcu_version"]))
            ver_str = ", ".join("v%d.%d" % v for v in hcu_vers) if hcu_vers else "none"
            print("  %s | %-12s: %3d logs, TYPE2 in %2d/%d  HCU versions: %s" % (
                label, sublabel, len(subset), len(with_t2), len(subset), ver_str))

    summarize(pre_swap, "PRE-SWAP ")
    summarize(post_swap, "POST-SWAP")
    summarize(unknown_date, "UNK-DATE ")

    print()


if __name__ == "__main__":
    main()
