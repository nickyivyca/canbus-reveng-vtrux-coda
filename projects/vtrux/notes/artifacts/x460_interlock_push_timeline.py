"""Correlate 0x460 fault-record pushes with hvil blips in the 2026-06-17 evening drive.

InfluxDB found 11 isolated bcm_hvil_mon=0 single points scattered through
vtrux_20260617_193900 (a ~70 min drive, no EPO), and the 0x460 census shows the
record stack transitioning DURING that session: count=0 -> FB B6 E4 -> FC 16 F2 on
top. If the push instants line up with the hvil blips, that directly confirms
FC 16 F2 (and possibly FB B6 E4) as interlock-open records -- upgrading both from
hypothesis, and confirming momentary interlock opens are recorded without tripping.

Also dumps the 2026-06-18_002023 trip (EPO at ~t=66s, pushed AC 10 01 -- the only
AC-record with param != 00 in the corpus) with drive-state context.

Times are header-anchored absolute (Android chunks reset line timestamps).

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/x460_interlock_push_timeline.py
"""
import sys
sys.path.insert(0, ".")

import glob
import re
from datetime import datetime

BM_RE = re.compile(
    r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
HDR_RE = re.compile(r"START DATE AND TIME\s+(\d+):(\d+):(\d+)\s+(\d+):(\d+):(\d+):(\d+)")
WATCH = {0x410, 0x440, 0x460, 0x625, 0x391}


def load_abs(pattern):
    frames = []
    for p in sorted(glob.glob(pattern)):
        anchor = None
        first_tod = None
        day_shift = 0.0
        prev_tod = None
        with open(p, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line[:1] == "*":
                    m = HDR_RE.search(line)
                    if m and anchor is None:
                        d, mo, y, hh, mm, ss, ms = (int(x) for x in m.groups())
                        anchor = datetime(y, mo, d, hh, mm, ss, ms * 1000).timestamp()
                    continue
                m = BM_RE.match(line)
                if not m:
                    continue
                hh, mm, ss, tk, idh, _dlc, rest = m.groups()
                aid = int(idh, 16)
                if aid not in WATCH:
                    continue
                tod = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(tk) / 10000.0
                if prev_tod is not None and tod < prev_tod - 72000:
                    day_shift += 86400.0
                prev_tod = tod
                if first_tod is None:
                    first_tod = tod
                if anchor is None:
                    anchor = 0.0
                try:
                    data = bytes(int(b, 16) for b in rest.split())
                except ValueError:
                    continue
                frames.append((anchor + (tod - first_tod) + day_shift, aid, data))
    frames.sort(key=lambda f: f[0])
    return frames


def hms(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]


def timeline(name, pattern):
    print("=" * 100)
    print(name)
    frames = load_abs(pattern)
    print("  %d watched frames, %s .. %s" % (len(frames), hms(frames[0][0]), hms(frames[-1][0])))

    saw_391 = any(aid == 0x391 for _, aid, _ in frames)
    odo = None
    for _, aid, d in frames:
        if aid == 0x625 and len(d) >= 4:
            odo = (d[1] << 16) | (d[2] << 8) | d[3]
            break
    print("  truck ID: 0x391 present=%s (main-truck exclusive); odometer=%s km" % (saw_391, odo))

    # hvil blips: 0x410 B0 bit3 falling edges (with duration)
    prev_hvil = None
    hvil_fall = None
    print("  --- hvil (0x410 B0 bit3) transitions ---")
    nshown = 0
    for t, aid, d in frames:
        if aid != 0x410 or len(d) < 2:
            continue
        hv = (d[0] >> 3) & 1
        if prev_hvil == 1 and hv == 0:
            hvil_fall = t
        if prev_hvil == 0 and hv == 1 and hvil_fall is not None:
            print("    %s  hvil LOW for %6.0f ms" % (hms(hvil_fall), (t - hvil_fall) * 1e3))
            hvil_fall = None
            nshown += 1
            if nshown > 40:
                print("    ... (truncated)")
                break
        prev_hvil = hv
    if hvil_fall is not None:
        print("    %s  hvil LOW until log end" % hms(hvil_fall))

    # 0x460 page-1 content changes (dedupe channel copies by ignoring repeats)
    print("  --- 0x460 page-01 distinct-content changes ---")
    prev = None
    for t, aid, d in frames:
        if aid != 0x460 or len(d) != 8 or d[0] != 0x01:
            continue
        key = d.hex(" ").upper()
        if key != prev:
            print("    %s  %s" % (hms(t), key))
            prev = key

    # EPO edges + drive state
    print("  --- 0x410 epo / alarm changes, with 0x440 contactor state ---")
    mainc = None
    prev_state = None
    for t, aid, d in frames:
        if aid == 0x440 and len(d) >= 1:
            mainc = (d[0] >> 2) & 0xF
        if aid != 0x410 or len(d) < 2:
            continue
        state = ((d[0] >> 1) & 1, (d[1] >> 6) & 3)
        if state != prev_state:
            print("    %s  epo=%d alarm=%d  mainc=%s" % (hms(t), state[0], state[1], mainc))
            prev_state = state


timeline("DRIVE vtrux_20260617_193900", "../../CANLogs/VtruxLogs/vtrux_20260617_193900_T*.log")
timeline("TRIP vtrux_20260618_002023", "../../CANLogs/VtruxLogs/vtrux_20260618_002023_T*.log")
timeline("SESSION vtrux_20260617_215641", "../../CANLogs/VtruxLogs/vtrux_20260617_215641_T*.log")
