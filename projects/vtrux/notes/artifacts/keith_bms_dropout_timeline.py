"""BMS message presence / dropout timeline for Truck 3's 2026-07-24 logs (3, 4, 6).

For each log:
  Part A -- wall-clock placement (candump epoch timestamps) so the three logs
            can be put on one common timeline.
  Part B -- per-BMS-ID presence: first frame, last frame, nominal period,
            and every gap longer than GAP_FACTOR x nominal period.
  Part C -- interleaved functional timeline: BMS master alive/dead, contactor
            state, HV bus, ignition/export, engine RPM.

Groups follow can-disconnect.md T2 test + the log-3/4 split:
  MASTER  -- A123 BMS master controller status/control block
  SECTION -- pack section / monitor boards (survive when master is down)

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/truck3-bms_dropout_timeline.py
"""
import sys
sys.path.insert(0, ".")

import datetime
from canre.parsers import parse_file

LOGS = [
    ("keithlog2      (named 'log 2')",     "projects/vtrux/logs/truck3-logs/keithlog2.log"),
    ("truck3-truck-3 (named 'log 3')",     "projects/vtrux/logs/truck3-logs/truck3-truck-3.log"),
    ("truck3-truck-4 (drive attempt)",     "projects/vtrux/logs/truck3-logs/truck3-truck4-keyoff-on-off-on.log"),
    ("truck3-6       (key + export)",      "projects/vtrux/logs/truck3-logs/truck3-6_key_and_export.txt"),
]

# 0x400 is the HSC/VCM -> BMS command message (enable / mainc_close / epo), NOT a
# BMS report. It is only published when a BMS is on the bus, so it tracks BMS
# presence, but it is driven by the controller -- keep it separate from the
# master's own measurement/status reports.
HSC_CMD = [0x400]
MASTER = [0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460]
SECTION = [0x370, 0x371, 0x372, 0x373, 0x374, 0x375, 0x506, 0x50F]

GAP_FACTOR = 5.0    # flag gaps longer than this x the median inter-frame interval
MIN_GAP = 0.30      # ...and at least this many seconds

MAINC_STAT_16 = [
    "ALL_OPEN", "FAILED_MAINP_OR_R_WELD", "CLOSE_MAINR", "FAILED_MAINR_OPEN",
    "FAILED_MAINN_WELD", "CLOSE_MAINN", "FAILED_MAINN_OPEN", "WAIT_PRECHARGE",
    "CLOSE_MAINP", "OPEN_MAINR", "FAILED_MAINP_OPEN", "MAIN_PN_CLOSED_DRIVE",
    "MAIN_P_CLOSED_CHARGE", "SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN", "(idx15)",
]


def median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def wall(epoch):
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


def raw_epoch_span(path):
    """candump logs carry absolute epoch in parentheses; canre re-zeroes them."""
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        first = fh.readline()
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 4096))
        tail = fh.read().splitlines()
    def ep(line):
        line = line.strip()
        if line.startswith("("):
            return float(line[1:line.index(")")])
        return None
    a = ep(first)
    b = None
    for line in reversed(tail):
        b = ep(line)
        if b is not None:
            break
    return a, b


def analyse(label, path):
    t0 = None
    epoch0 = None
    times = {}
    events = []
    prev = {}

    for f in parse_file(path):
        if t0 is None:
            t0 = f.timestamp
            epoch0 = f.timestamp
        t = f.timestamp - t0
        d = f.data
        i = f.arbitration_id

        if i in MASTER or i in SECTION or i in HSC_CMD:
            times.setdefault(i, []).append(t)

        if i == 0x592 and len(d) >= 1:
            cur = ((d[0] >> 4) & 1, (d[0] >> 2) & 1)
            if prev.get("592") != cur:
                events.append((t, "KEY/EXPORT", "ignition=%d  export=%d" % cur))
                prev["592"] = cur
        elif i == 0x440 and len(d) >= 1:
            m = (d[0] >> 2) & 0xF
            if prev.get("440") != m:
                events.append((t, "CONTACTOR", MAINC_STAT_16[m]))
                prev["440"] = m
        elif i == 0x482 and len(d) >= 3:
            v = d[1] | ((d[2] & 0x0F) << 8)
            pv = prev.get("482")
            if pv is None or abs(v - pv) >= 40:
                events.append((t, "HV BUS", "%d V" % v))
                prev["482"] = v
        elif i == 0x054 and len(d) >= 2:
            rpm = (d[0] | (d[1] << 8)) - 32767
            pv = prev.get("054")
            if pv is None or abs(rpm - pv) >= 400:
                events.append((t, "GENERATOR", "%d rpm" % rpm))
                prev["054"] = rpm
        elif i == 0x053 and len(d) >= 1:
            m = (d[0] >> 4) & 0x7
            if prev.get("053") != m:
                events.append((t, "HCU op_mode", "mode=%d" % m))
                prev["053"] = m

    dur = t
    ep_a, ep_b = raw_epoch_span(path)
    print("=" * 100)
    print("  %s" % label)
    print("=" * 100)
    print("  wall clock : %s  ->  %s   (%.1f s)"
          % (wall(ep_a), wall(ep_b), dur))
    print()

    # ---- Part B: presence table -------------------------------------------
    for gname, group in (("BMS MASTER REPORTS  (pack V/I/SoC/limits/contactor state)", MASTER),
                         ("HSC -> BMS COMMAND  (0x400: enable / mainc_close / epo)", HSC_CMD),
                         ("PACK SECTION / MONITOR BOARDS", SECTION)):
        print("  %s" % gname)
        print("    %-8s %-7s %-9s %-9s %-9s %s"
              % ("ID", "frames", "first", "last", "period", "gaps > %gx period" % GAP_FACTOR))
        for i in group:
            ts = times.get(i)
            if not ts:
                print("    0x%03X    %-7s %-9s %-9s %-9s %s"
                      % (i, "0", "-", "-", "-", "*** NEVER TRANSMITTED ***"))
                continue
            deltas = [b - a for a, b in zip(ts, ts[1:])]
            per = median(deltas) if deltas else 0.0
            gaps = [(a, b - a) for a, b in zip(ts, ts[1:])
                    if (b - a) > max(GAP_FACTOR * per, MIN_GAP)]
            gtxt = "none" if not gaps else "; ".join("%.2fs @ t=%.2f" % (g, a) for a, g in gaps[:4])
            if len(gaps) > 4:
                gtxt += " (+%d more)" % (len(gaps) - 4)
            print("    0x%03X    %-7d %-9.2f %-9.2f %-9.3f %s"
                  % (i, len(ts), ts[0], ts[-1], per, gtxt))
        print()

    # ---- Part C: functional timeline --------------------------------------
    mstart = min((times[i][0] for i in MASTER if i in times), default=None)
    mend = max((times[i][-1] for i in MASTER if i in times), default=None)
    if mstart is not None:
        events.append((mstart, ">>> BMS MASTER", "FIRST FRAME (master joins bus)"))
        events.append((mend, ">>> BMS MASTER", "LAST FRAME (master leaves bus)"))
    hstart = min((times[i][0] for i in HSC_CMD if i in times), default=None)
    hend = max((times[i][-1] for i in HSC_CMD if i in times), default=None)
    if hstart is not None:
        events.append((hstart, "    0x400 HSC cmd", "first frame"))
        events.append((hend, "    0x400 HSC cmd", "last frame"))
    sstart = min((times[i][0] for i in SECTION if i in times), default=None)
    send = max((times[i][-1] for i in SECTION if i in times), default=None)
    if sstart is not None:
        events.append((sstart, "--- section boards", "first frame"))
        events.append((send, "--- section boards", "last frame"))

    print("  FUNCTIONAL TIMELINE")
    print("    %-9s %-20s %s" % ("t", "what", "detail"))
    print("    " + "-" * 84)
    for t, what, detail in sorted(events, key=lambda x: x[0]):
        print("    t=%7.3f %-20s %s" % (t, what, detail))
    print()
    return ep_a, dur


if __name__ == "__main__":
    spans = []
    for label, path in LOGS:
        spans.append((label,) + analyse(label, path))

    print("=" * 100)
    print("  COMMON WALL-CLOCK TIMELINE")
    print("=" * 100)
    base = min(s[1] for s in spans)
    for label, e0, dur in sorted(spans, key=lambda s: s[1]):
        print("  %-38s %s  ->  %s   (T+%8.1f s from first log)"
              % (label, wall(e0), wall(e0 + dur), e0 - base))
