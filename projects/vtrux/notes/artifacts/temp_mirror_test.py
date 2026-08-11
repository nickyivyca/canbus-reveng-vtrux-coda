"""Are the 0x50x / 0x37x temperatures rebroadcasts of the 0x430 cell temps?

Hypothesis (owner, 2026-08-09): the 0x370-0x375 / 0x506 / 0x507 / 0x50F group is not
independent BMS sensing but a pack-side conditioning module republishing temperatures
it reads -- which would explain why the whole group is present-or-absent as a unit and
why 0x506 carries the cooling-active flag (B0 bit5) alongside temperatures.

Test: time-align every temperature-bearing byte against 0x430 cell_tmax / cell_tmin
and look for
  * exact-copy relationships (same value, allowing for the 0.5 C vs 1 C scale change)
  * fixed offsets
  * lag (mirror should FOLLOW the source)
  * quantisation tells (a 1 C signal derived from a 0.5 C source shows floor/round
    artefacts locked to the source, not independent noise)

Encodings (from tools/diagnose_vtrux.py and powertrain-messages.md):
  0x430 B4/B5      cell_tmax / cell_tmin   raw*0.5 - 40   (0.5 C steps)
  0x506 B1/B2/B3   3 temperature sensors   raw - 40       (1 C steps)
  0x507 B0/B1      2 temperature sensors   raw - 40       (1 C steps)
  0x373 B3         battery system temp     raw - 40
  0x370/1/2/4 B*   section temps           raw - 40

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/temp_mirror_test.py
"""
import sys
import os
import re
import glob

sys.path.insert(0, ".")

BM = re.compile(r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
CD = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)$")

SRC = {("0x430", 4): "cell_tmax", ("0x430", 5): "cell_tmin"}
CAND = [("0x506", 1), ("0x506", 2), ("0x506", 3),
        ("0x507", 0), ("0x507", 1),
        ("0x373", 3), ("0x370", 0), ("0x370", 4), ("0x371", 0), ("0x372", 0)]
WATCH = {0x430, 0x506, 0x507, 0x373, 0x370, 0x371, 0x372}


def rows(paths):
    base = last = 0.0
    for p in paths:
        first = None
        try:
            fh = open(p, "r", encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                if line[:1] == "*":
                    continue
                m = BM.match(line)
                if m:
                    hh, mi, ss, tk, idh, _d, rest = m.groups()
                    aid = int(idh, 16)
                    if aid not in WATCH:
                        continue
                    t = int(hh) * 3600 + int(mi) * 60 + int(ss) + int(tk) / 10000.0
                    try:
                        d = bytes(int(b, 16) for b in rest.split())
                    except ValueError:
                        continue
                else:
                    m = CD.match(line.strip())
                    if not m:
                        continue
                    aid = int(m.group(2), 16)
                    if aid not in WATCH:
                        continue
                    t = float(m.group(1))
                    try:
                        d = bytes.fromhex(m.group(3)) if m.group(3) else b""
                    except ValueError:
                        continue
                if not d:
                    continue
                if first is None:
                    first = t
                    base = last
                tt = base + (t - first)
                if tt < last:
                    tt = last
                last = max(last, tt)
                yield tt, aid, d


def collect(paths):
    """Sample every candidate at 1 Hz on a common clock."""
    cur = {}
    series = {}
    nxt = None
    for t, aid, d in rows(paths):
        key = "0x%03X" % aid
        for i, b in enumerate(d):
            cur[(key, i)] = b
        if nxt is None:
            nxt = t
        while t >= nxt:
            snap = dict(cur)
            series.setdefault("t", []).append(nxt)
            for k in list(SRC) + CAND:
                v = snap.get(k)
                series.setdefault(k, []).append(v)
            nxt += 1.0
    return series


def corr(a, b):
    pair = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pair) < 20:
        return None, 0
    n = len(pair)
    ax = sum(p[0] for p in pair) / n
    by = sum(p[1] for p in pair) / n
    num = sum((p[0] - ax) * (p[1] - by) for p in pair)
    da = sum((p[0] - ax) ** 2 for p in pair) ** 0.5
    db = sum((p[1] - by) ** 2 for p in pair) ** 0.5
    if da == 0 or db == 0:
        return None, n
    return num / (da * db), n


SESSIONS = {
    "parts-orig 2026-07-14 (fan session, 35-41.5C)":
        sorted(glob.glob("../../CANLogs/VtruxLogs/vtrux_20260714_161319_T*.log"),
               key=lambda p: int(re.search(r"_T(\d+)", p).group(1)))[60:80],
    "parts-orig vtruxchargeafteroverheattest":
        ["projects/vtrux/logs/vtruxchargeafteroverheattest-32asetpoint.log"],
    "parts-orig vtruxexportafterucsc":
        ["projects/vtrux/logs/vtruxexportafterucsc.log"],
}

for name, paths in SESSIONS.items():
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        continue
    print("=" * 112)
    print("  %s   (%d file%s)" % (name, len(paths), "s" if len(paths) > 1 else ""))
    print("=" * 112)
    s = collect(paths)
    if "t" not in s or len(s["t"]) < 30:
        print("  too little data\n")
        continue
    print("  %d samples at 1 Hz" % len(s["t"]))
    for src, srcname in SRC.items():
        sv = s.get(src)
        if not sv or all(v is None for v in sv):
            continue
        real = [v * 0.5 - 40 if v is not None else None for v in sv]
        rr = [v for v in real if v is not None]
        print()
        print("  SOURCE %s (%s): %.1f .. %.1f C" % (src[0] + ".B%d" % src[1], srcname, min(rr), max(rr)))
        print("     %-13s %-8s %-9s %-22s %s"
              % ("candidate", "r", "range C", "offset vs source (C)", "exact-copy?"))
        for c in CAND:
            cv = s.get(c)
            if not cv or all(v is None for v in cv):
                continue
            creal = [v - 40 if v is not None else None for v in cv]
            r, n = corr(real, creal)
            pair = [(x, y) for x, y in zip(real, creal) if x is not None and y is not None]
            if not pair:
                continue
            diffs = [y - x for x, y in pair]
            lo, hi = min(diffs), max(diffs)
            cr = [y for _x, y in pair]
            # exact copy test: candidate == floor/round of source, consistently
            fl = sum(1 for x, y in pair if y == int(x // 1)) / len(pair)
            rd = sum(1 for x, y in pair if y == round(x)) / len(pair)
            tag = ""
            if fl > 0.95:
                tag = "FLOOR of source (%.0f%%)" % (fl * 100)
            elif rd > 0.95:
                tag = "ROUND of source (%.0f%%)" % (rd * 100)
            elif lo == hi:
                tag = "fixed offset %+.1f" % lo
            print("     %-13s %-8s %-9s %-22s %s"
                  % (c[0] + ".B%d" % c[1],
                     ("%.4f" % r) if r is not None else "-",
                     "%.0f..%.0f" % (min(cr), max(cr)),
                     "%+.1f .. %+.1f" % (lo, hi),
                     tag))
    print()
