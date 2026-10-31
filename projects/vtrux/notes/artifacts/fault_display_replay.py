"""Fault-scenario replay harness for the Vtrux live-display app.

Purpose: find the fault instant in a long CAN capture, then cut a short slice
around it that can be replayed into the Android display app via
`tools/can_display_server.py` in near-real-time.

Phases
------
scan   : walk a log and print every transition of the BMS fault-relevant
         signals (0x410 epo / hvil / alarm / gfd, 0x440 contactor state).
         Used to pick the slice window.
slice  : copy a time window out of a log at the *raw line* level, preserving
         the original format exactly (BUSMASTER headers are carried over).
         Line-level slicing avoids any re-encoding of timestamps or data.

Signal bit layouts are taken from the DBC the app itself bundles
(`android-app/CanLoggerApps/vtrux/src/main/assets/live-display/dbcs/powertrain.dbc`)
so the scan sees exactly what the display sees:

    0x410 bcm_epo       1|1@1+     -> B0 bit 1
    0x410 bcm_hvil_mon  3|1@1+     -> B0 bit 3
    0x410 bcm_alarm     14|2@1+    -> B1 bits 6-7
    0x410 bcm_gfd       11|12@0+   -> B1[3:0]:B2, scale 0.25
    0x440 bcm_mainc_stat 2|4@1+    -> B0 bits 2-5

Usage:
    py -3.11 projects/vtrux/notes/artifacts/fault_display_replay.py scan \
        --log projects/vtrux/logs/vtruxisolationtest.log

    py -3.11 projects/vtrux/notes/artifacts/fault_display_replay.py slice \
        --log projects/vtrux/logs/vtruxisolationtest.log \
        --out projects/vtrux/notes/artifacts/fault-slices/isolation.log \
        --start 20 --end 80
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import argparse
import re
from pathlib import Path

from canre.parsers import parse_file

MAINC_NAMES = {
    0: "ALL_OPEN",
    1: "FAILED_MAINP_OR_R_WELD",
    2: "CLOSE_MAINR",
    3: "FAILED_MAINR_OPEN",
    4: "FAILED_MAINN_WELD",
    5: "CLOSE_MAINN",
    6: "FAILED_MAINN_OPEN",
    7: "WAIT_PRECHARGE",
    8: "CLOSE_MAINP",
    9: "OPEN_MAINR",
    10: "FAILED_MAINP_OPEN",
    11: "MAIN_PN_CLOSED_DRIVE",
    12: "MAIN_P_CLOSED_CHARGE",
    13: "SHUTDOWN_REQUEST",
    14: "ALL_OPEN_SHUTDOWN",
}
ALARM_NAMES = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}

BUSMASTER_DATA_RE = re.compile(
    r"^(\d{1,2}):(\d{2}):(\d{2}):(\d{4})\s+(Tx|Rx)\s+\d+\s+0x[0-9A-Fa-f]+\s+[sx]\s+\d+",
    re.IGNORECASE,
)
CANDUMP_DATA_RE = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+[0-9A-Fa-f]+#")


# --------------------------------------------------------------------------
# Phase: scan
# --------------------------------------------------------------------------


def decode_410(d: bytes) -> dict | None:
    if len(d) < 3:
        return None
    b0, b1, b2 = d[0], d[1], d[2]
    return {
        "epo": (b0 >> 1) & 1,
        "hvil": (b0 >> 3) & 1,
        "alarm": (b1 >> 6) & 3,
        "gfd": (((b1 & 0x0F) << 8) | b2) * 0.25,
    }


def decode_440(d: bytes) -> int | None:
    if len(d) < 1:
        return None
    return (d[0] >> 2) & 0x0F


def scan(path: Path, quiet_gfd: bool) -> None:
    prev410: dict | None = None
    prev_mainc: int | None = None
    n = 0
    print(f"# scan {path}")
    print(f"{'t(s)':>10}  event")
    for frame in parse_file(path):
        aid = frame.arbitration_id
        if aid == 0x410:
            cur = decode_410(frame.data)
            if cur is None:
                continue
            n += 1
            if prev410 is None:
                print(f"{frame.timestamp:10.3f}  START 0x410 epo={cur['epo']} "
                      f"hvil={cur['hvil']} alarm={ALARM_NAMES[cur['alarm']]} "
                      f"gfd={cur['gfd']:.1f}")
            else:
                for key in ("epo", "hvil", "alarm"):
                    if cur[key] != prev410[key]:
                        old, new = prev410[key], cur[key]
                        if key == "alarm":
                            old, new = ALARM_NAMES[old], ALARM_NAMES[new]
                        print(f"{frame.timestamp:10.3f}  {key}: {old} -> {new}")
                # gfd is noisy; report only crossings of the 500 ohm/V app
                # threshold unless full detail was asked for.
                was_bad = prev410["gfd"] < 500.0
                is_bad = cur["gfd"] < 500.0
                if was_bad != is_bad or (not quiet_gfd and cur["gfd"] != prev410["gfd"]):
                    print(f"{frame.timestamp:10.3f}  gfd: {prev410['gfd']:.1f} "
                          f"-> {cur['gfd']:.1f}")
            prev410 = cur
        elif aid == 0x440:
            cur_m = decode_440(frame.data)
            if cur_m is None:
                continue
            if cur_m != prev_mainc:
                old = MAINC_NAMES.get(prev_mainc, str(prev_mainc))
                new = MAINC_NAMES.get(cur_m, str(cur_m))
                print(f"{frame.timestamp:10.3f}  contactor: {old} -> {new}")
                prev_mainc = cur_m
    print(f"# 0x410 frames seen: {n}")


# --------------------------------------------------------------------------
# Phase: slice
# --------------------------------------------------------------------------


def slice_log(path: Path, out: Path, start: float, end: float) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    t0: float | None = None
    kept = 0
    total = 0
    fmt = None
    with open(path, "r", encoding="utf-8", errors="replace") as fh, \
         open(out, "w", encoding="utf-8", newline="") as fo:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if line.startswith("***") or line.startswith("#"):
                fo.write(line + "\n")
                continue
            m = BUSMASTER_DATA_RE.match(line)
            if m:
                fmt = "busmaster"
                h, mi, s, ticks = (int(m.group(i)) for i in range(1, 5))
                t = h * 3600.0 + mi * 60.0 + s + ticks * 0.0001
            else:
                m2 = CANDUMP_DATA_RE.match(line)
                if not m2:
                    continue
                fmt = "candump"
                t = float(m2.group(1))
            total += 1
            if t0 is None:
                t0 = t
            rel = t - t0
            if rel < start:
                continue
            if rel > end:
                break
            fo.write(line + "\n")
            kept += 1
    size_mb = out.stat().st_size / 1_048_576.0
    print(f"{out}  format={fmt}  kept={kept}/{total} lines  "
          f"window={start}-{end}s  {size_mb:.1f} MB")


# --------------------------------------------------------------------------
# Phase: faultrec
# --------------------------------------------------------------------------


def faultrec(path: Path) -> None:
    """Walk the 0x460 BMS fault-record annunciator and report set changes.

    Structure per `notes/battery-fault-codes.md`: ~20 Hz, DLC=8, multiplexed
    on B0 = page index. Page 0x00 is the header (B2 = record count, B5/B6 =
    push event counters); pages 0x01.. carry up to two 3-byte records each,
    newest first, unused slots zero.

    The OBD bus carries an unrelated 0x460 at DLC=5 -- filtered out here by
    requiring 8 data bytes, the same filter the notes recommend.
    """
    pages: dict[int, tuple] = {}
    prev_records: list[str] | None = None
    prev_count: int | None = None
    prev_ticks: tuple | None = None
    print(f"# 0x460 fault records {path}")
    print(f"{'t(s)':>10}  event")
    for frame in parse_file(path):
        if frame.arbitration_id != 0x460 or len(frame.data) != 8:
            continue
        d = frame.data
        page = d[0]
        if page == 0x00:
            count, ticks = d[2], (d[5], d[6])
            if count != prev_count:
                print(f"{frame.timestamp:10.3f}  record count: {prev_count} -> {count}")
                prev_count = count
            if prev_ticks is not None and ticks != prev_ticks:
                print(f"{frame.timestamp:10.3f}  push counters tick "
                      f"{prev_ticks} -> {ticks}")
            prev_ticks = ticks
            continue
        pages[page] = (d[2], d[3], d[4], d[5], d[6], d[7])
        records: list[str] = []
        for p in sorted(pages):
            b = pages[p]
            for rec in (b[0:3], b[3:6]):
                if any(rec):
                    records.append(" ".join(f"{x:02X}" for x in rec))
        if records != prev_records:
            if prev_records is None:
                print(f"{frame.timestamp:10.3f}  initial records: "
                      f"{records or '(none)'}")
            else:
                added = [r for r in records if r not in prev_records]
                removed = [r for r in prev_records if r not in records]
                if added:
                    print(f"{frame.timestamp:10.3f}  PUSH {added}   "
                          f"(list now {records})")
                if removed:
                    print(f"{frame.timestamp:10.3f}  cleared {removed}   "
                          f"(list now {records})")
            prev_records = records


# --------------------------------------------------------------------------
# Phase: thermal
# --------------------------------------------------------------------------

# The four signals the display's temperature sliders read, decoded with
# cantools against the DBCs the app bundles, so the peak we pick for a
# thermal-excursion slice is the peak the display would actually draw.
THERMAL_SIGNALS = {
    "GENE_ThermInd_pct": 0x479,
    "GENE_DrvCoolFlowReq_pct": 0x479,
    "TRAC_ThermInd_pct": 0x44A,
    "TRAC_DrvCoolFlowReq_pct": 0x44A,
    "DCDC_Temperature": 0x18FFD6B3,
    "Engine_Coolant_Temperature": 0x4C1,
}

APP_DBC_DIR = Path(
    "android-app/CanLoggerApps/vtrux/src/main/assets/live-display/dbcs"
)


def thermal(path: Path, bucket: float) -> None:
    import cantools

    dbs = [cantools.database.load_file(APP_DBC_DIR / f"{n}.dbc")
           for n in ("powertrain", "obd")]
    by_id: dict[int, list] = {}
    for db in dbs:
        for msg in db.messages:
            by_id.setdefault(msg.frame_id, []).append(msg)

    wanted_ids = set(THERMAL_SIGNALS.values())
    peaks: dict[str, tuple[float, float]] = {}
    buckets: dict[int, dict[str, float]] = {}

    for frame in parse_file(path):
        if frame.arbitration_id not in wanted_ids:
            continue
        for msg in by_id.get(frame.arbitration_id, ()):
            try:
                decoded = msg.decode(frame.data, allow_truncated=True)
            except Exception:
                continue
            for name, value in decoded.items():
                if name not in THERMAL_SIGNALS:
                    continue
                value = float(value)
                if name not in peaks or value > peaks[name][0]:
                    peaks[name] = (value, frame.timestamp)
                slot = int(frame.timestamp // bucket)
                cell = buckets.setdefault(slot, {})
                if value > cell.get(name, float("-inf")):
                    cell[name] = value

    names = sorted(peaks)
    print(f"# thermal {path}")
    print("peaks:")
    for name in names:
        value, when = peaks[name]
        print(f"  {name:30s} max={value:8.1f}  at t={when:.1f}s")
    print(f"\nper-{bucket:.0f}s maxima:")
    header = "    t  " + "  ".join(f"{n[:14]:>14s}" for n in names)
    print(header)
    for slot in sorted(buckets):
        row = buckets[slot]
        cells = "  ".join(
            f"{row[n]:14.1f}" if n in row else " " * 14 for n in names
        )
        print(f"{slot * bucket:6.0f}  {cells}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("faultrec")
    p_rec.add_argument("--log", required=True, type=Path)

    p_therm = sub.add_parser("thermal")
    p_therm.add_argument("--log", required=True, type=Path)
    p_therm.add_argument("--bucket", type=float, default=30.0)

    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--log", required=True, type=Path)
    p_scan.add_argument("--all-gfd", action="store_true",
                        help="print every gfd change, not just 500 crossings")

    p_slice = sub.add_parser("slice")
    p_slice.add_argument("--log", required=True, type=Path)
    p_slice.add_argument("--out", required=True, type=Path)
    p_slice.add_argument("--start", required=True, type=float)
    p_slice.add_argument("--end", required=True, type=float)

    args = ap.parse_args()
    if args.cmd == "scan":
        scan(args.log, quiet_gfd=not args.all_gfd)
    elif args.cmd == "faultrec":
        faultrec(args.log)
    elif args.cmd == "thermal":
        thermal(args.log, args.bucket)
    else:
        slice_log(args.log, args.out, args.start, args.end)


if __name__ == "__main__":
    main()
