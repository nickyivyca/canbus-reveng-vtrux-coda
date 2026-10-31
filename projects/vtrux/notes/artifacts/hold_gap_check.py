"""hold_gap_check.py -- maximum inter-frame gaps of the interposer's staleness-
trip ids, bulk vs Low Power hold, all 10 hold sessions (2026-10-10).

For the charge-interposer reviewer: spec 6 trips on any of 0x410, 0x420,
0x430, 0x440 (BMS) or 0x18FFD4C0 (charger status) going 500 ms stale, each
timed separately. hold_msgrate_check.py showed mean rates are flat through
the hold; a flat mean can still hide a single long gap, so this measures gaps.

  1  grep-filter the raw logs to the six ids below (0x18FFD7C0 is only used to
     class the state), in parallel, into gapcheck_filtered/ (deleted after)
  2  per file, the channel carrying both 0x18FFD7C0 and 0x410 is powertrain;
     each (channel, id) series is SORTED BY TIME before gaps are taken (file
     order is not time order, AGENTS.md). Gaps are taken within a file only --
     a chunk boundary is a capture boundary, not a bus gap. A gap is classed by
     the state at its start (forward-filled charger reading; bulk = |Idc| >= 10
     A and Iac > 15 A, hold = 0.5 <= |Idc| < 3.5 A and Iac > 5 A).
     A gap > 250 ms that overlaps a gap > 250 ms on at least 3 of the other
     ids is flagged CONCURRENT: every id silent at once points at the capture
     (logger, USB) rather than one transmitter.
Gap times are file-relative seconds plus the header wall clock (local time,
header-derived, so approximate: some chunk headers state the wrong time).
"""
import sys
sys.path.insert(0, ".")
import glob
import json
import multiprocessing as mp
import os
import re
import subprocess

import cantools
from canre.parsers import parse_file

PHASES = {1, 2}
ART = "projects/vtrux/notes/artifacts/"
FILT = ART + "gapcheck_filtered/"
OUT = ART + "hold_gap_check.json"
SESS = {
    "another_M0": "projects/vtrux/logs/after-battery-swap-charges/another_M0_T*.log",
    "charge_M0": "projects/vtrux/logs/after-battery-swap-charges/charge_M0_T*.log",
    "full-charge-then-fail": "projects/vtrux/logs/full-charge-then-fail.log",
    "vtrux_20260503_192242": "../../CANLogs/VtruxLogs/vtrux_20260503_192242_T*.log",
    "vtrux_20260726_191901": "../../CANLogs/VtruxLogs/vtrux_20260726_191901_T*.log",
    "vtrux_20260816_111915": "../../CANLogs/VtruxLogs/vtrux_20260816_111915_T*.log",
    "vtrux_20260912_192748": "../../CANLogs/VtruxLogs/vtrux_20260912_192748_T*.log",
    "vtrux_charge_M1": "projects/vtrux/logs/vtrux_charge_M1_T*.log",
    "vtrux_partstruck_charge": "projects/vtrux/logs/big-logs/vtrux_partstruck_charge.log",
    "vtruxchargeafterexportchargetest-80pctcv":
        "projects/vtrux/logs/vtruxchargeafterexportchargetest-80pctcv.log",
}
CHG = 0x18FFD7C0
WATCH = [0x410, 0x420, 0x430, 0x440, 0x18FFD4C0]
NAMES = {0x410: "0x410", 0x420: "0x420", 0x430: "0x430", 0x440: "0x440",
         0x18FFD4C0: "0x18FFD4C0"}
PAT = " 0x18FFD7C0 | 0x410 | 0x420 | 0x430 | 0x440 | 0x18FFD4C0 "


def cls(idc, iac):
    a = abs(idc)
    if a >= 10 and iac > 15:
        return "bulk"
    if 0.5 <= a < 3.5 and iac > 5:
        return "hold"
    return "other"


def filt(job):
    src, dst = job
    with open(src, "rb") as f, open(dst, "wb") as o:
        for line in f:
            o.write(line)
            if line.startswith(b"***<Time>"):
                break
        o.flush()
        subprocess.run(["grep", "-aE", PAT, src], stdout=o)
    return dst


def header_clock(path):
    with open(path, "rb") as f:
        for _ in range(20):
            m = re.search(rb"START DATE AND TIME (\d+):(\d+):(\d+) (\d+):(\d+):(\d+)",
                          f.readline())
            if m:
                return int(m[4]) * 3600 + int(m[5]) * 60 + int(m[6])
    return None


def one(path):
    bel = cantools.database.load_file("projects/vtrux/BelInverter-v2.dbc")
    ser = {}
    for f in parse_file(path):
        ser.setdefault(f.bus, {}).setdefault(f.arbitration_id, []).append(
            (f.timestamp, f.data))
    hc = header_clock(path)
    out = []
    for ch, ids in ser.items():
        if CHG not in ids or 0x410 not in ids:
            continue
        chg = sorted(ids[CHG])
        st_t, st_v = [], []
        idc = iac = None
        for t, d in chg:
            v = bel.decode_message(CHG, d)
            if abs(v["BELINV_hvBatteryCurrent"]) < 100 and v["BELINV_chargerInputCurrent"] < 60:
                idc, iac = v["BELINV_hvBatteryCurrent"], v["BELINV_chargerInputCurrent"]
            if idc is not None:
                st_t.append(t)
                st_v.append(cls(idc, iac))

        def state_at(t):
            lo, hi = 0, len(st_t)
            while lo < hi:
                m = (lo + hi) // 2
                if st_t[m] <= t:
                    lo = m + 1
                else:
                    hi = m
            return st_v[lo - 1] if lo else "other"

        gaps = {}
        span = {}
        for i in WATCH:
            ts = sorted(t for t, _ in ids.get(i, []))
            gaps[i] = [(a, b - a) for a, b in zip(ts, ts[1:])]
            span[i] = (ts[0], ts[-1], len(ts)) if ts else None
        big = {i: [g for g in gaps[i] if g[1] > 0.25] for i in WATCH}
        rec = {"file": os.path.basename(path), "ch": ch, "hdr": hc, "ids": {}}
        for i in WATCH:
            r = {"span": span[i], "bulk": [0.0, 0, 0], "hold": [0.0, 0, 0],
                 "over500": []}
            for a, g in gaps[i]:
                s = state_at(a)
                if s not in ("bulk", "hold"):
                    continue
                x = r[s]
                x[0] = max(x[0], g)
                x[1] += g > 0.25
                x[2] += g > 0.5
            for a, g in big[i]:
                conc = sum(1 for j in WATCH if j != i and any(
                    b0 < a + g and a < b0 + g2 for b0, g2 in big[j]))
                if g > 0.5:
                    r["over500"].append((a, g, state_at(a), conc >= 3))
            rec["ids"][NAMES[i]] = r
        out.append(rec)
    return out


if 1 in PHASES:
    os.makedirs(FILT, exist_ok=True)
    jobs = [(p, FILT + s + "__" + os.path.basename(p))
            for s, pat in SESS.items() for p in sorted(glob.glob(pat))]
    print("phase1: filtering %d files" % len(jobs), flush=True)
    with mp.get_context("fork").Pool(12) as pool:
        for _ in pool.imap_unordered(filt, jobs):
            pass

if 2 in PHASES:
    files = sorted(glob.glob(FILT + "*.log"))
    res = []
    with mp.get_context("fork").Pool(12) as pool:
        for out in pool.imap_unordered(one, files):
            res.extend(out)
    with open(OUT, "w") as f:
        json.dump(res, f)
else:
    res = json.load(open(OUT))


def clock(hdr, t):
    if hdr is None:
        return "  n/a   "
    s = int(hdr + t) % 86400
    return "%02d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60)


print("\nphase2: inter-frame gaps on the powertrain channel, per id and state")
print("  max gap s | n > 250 ms | n > 500 ms   (gaps within a file only)")
allover = []
for s in SESS:
    recs = [r for r in res if r["file"].startswith(s + "__")]
    print("\n  %s  (%d file-channels)" % (s, len(recs)))
    for name in NAMES.values():
        agg = {"bulk": [0.0, 0, 0], "hold": [0.0, 0, 0]}
        nfr = 0
        for r in recs:
            x = r["ids"][name]
            if x["span"]:
                nfr += x["span"][2]
            for k in agg:
                agg[k] = [max(agg[k][0], x[k][0]), agg[k][1] + x[k][1], agg[k][2] + x[k][2]]
            for a, g, stt, conc in x["over500"]:
                allover.append((s, r["file"].split("__", 1)[1], r["ch"], name, a, g,
                                stt, conc, clock(r["hdr"], a)))
        print("    %-11s frames %8d | bulk max %6.3f  >250 %4d  >500 %3d | "
              "hold max %6.3f  >250 %4d  >500 %3d"
              % ((name, nfr) + tuple(agg["bulk"]) + tuple(agg["hold"])))

print("\n  every gap > 500 ms, any state (file, ch, id, file-rel t, length,"
      " state, concurrent-with->=3-other-ids, header clock):")
for row in sorted(allover):
    print("    %-26s %-40s ch%-2s %-10s t=%9.3f  gap %7.3f s  %-4s  %s  %s"
          % (row[0][:26], row[1], row[2], row[3], row[4], row[5], row[6],
             "CONCURRENT" if row[7] else "isolated  ", row[8]))
if not allover:
    print("    none")
