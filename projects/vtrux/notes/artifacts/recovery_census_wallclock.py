"""Wall-clock re-verification of the EPO/ALARM recovery events found by
type1_census_merged.py.

That census's read_chunked() re-bases every chunk so its first frame lands exactly at
the previous chunk's last timestamp -- deliberately erasing inter-chunk wall-clock
gaps. Proven consequence: the "truklog_M0 self-recovery, held 5.03s" is actually a
25-MINUTE bus-dead gap between T9 (fault, 15:02) and T10 (fresh boot at replug,
15:27). Its basename dedup can also splice the September truklog_M0_T1.log into the
June session of the same name.

This script replays each session in TRUE wall-clock time (BUSMASTER: file anchored at
its START DATE AND TIME header, line offsets from first data line; candump: epoch),
finds every EPO 1->0 and alarm TYPE3->lesser transition, and reports:

  gap      wall-clock gap between the clear frame and the previous 0x410 frame
  x-file   whether that gap straddles a file boundary
  B1       0x410 B1 at the clear frame (0x3F = fresh pre-HV boot state)
  verdict  IN-COVERAGE (gap < 5s: the clear is genuinely observed) vs
           ACROSS-GAP (gap >= 5s: BMS was silent; clear cannot be attributed --
           an operator replug / 12V cycle during the blackout is the default
           explanation, NOT spontaneous recovery)

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/recovery_census_wallclock.py
"""
import sys
sys.path.insert(0, ".")

import os
import re
import glob
from datetime import datetime

BM_RE = re.compile(
    r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
CD_RE = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)$")
HDR_RE = re.compile(r"START DATE AND TIME\s+(\d+):(\d+):(\d+)\s+(\d+):(\d+):(\d+):(\d+)")
ALARM = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}


def file_frames(path):
    """Yield (t_abs_epoch, data) for 0x410 frames, wall-clock anchored."""
    anchor = None            # epoch of file start per header
    first_tod = None
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line[:1] == "*":
                m = HDR_RE.search(line)
                if m and anchor is None:
                    d, mo, y, hh, mm, ss, ms = (int(x) for x in m.groups())
                    anchor = datetime(y, mo, d, hh, mm, ss, ms * 1000).timestamp()
                continue
            m = BM_RE.match(line)
            if m:
                hh, mm, ss, tk, idh, _dlc, rest = m.groups()
                if int(idh, 16) != 0x410:
                    continue
                tod = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(tk) / 10000.0
                if first_tod is None:
                    first_tod = tod
                if anchor is None:
                    anchor = 0.0
                t = anchor + (tod - first_tod)
                try:
                    data = bytes(int(b, 16) for b in rest.split())
                except ValueError:
                    continue
                yield t, path, data
            else:
                m = CD_RE.match(line.strip())
                if not m:
                    continue
                ep, idh, payload = m.groups()
                if int(idh, 16) != 0x410:
                    continue
                yield float(ep), path, bytes.fromhex(payload) if payload else b""


def tnum(p):
    m = re.search(r"_T(\d+)\.", os.path.basename(p))
    return int(m.group(1)) if m else 0


# Optional: point globs at a directory of grep-prefiltered copies (0x410 + header
# lines only) to keep runtime manageable on multi-GB sessions. Produce them with:
#   grep -a -E " 0x410 |START DATE AND TIME| 410#" <log>  > f410/<tag>__<basename>
F410 = os.environ.get("F410_DIR")


def g(pattern):
    """Glob raw logs, or their prefiltered copies when F410_DIR is set."""
    if not F410:
        return sorted(glob.glob(pattern), key=tnum)
    base = os.path.basename(pattern)
    return sorted(glob.glob(os.path.join(F410, "*__" + base)), key=tnum)


def session_frames(paths):
    frames = []
    for p in paths:
        if os.path.exists(p):
            frames.extend(file_frames(p))
    frames.sort(key=lambda f: f[0])
    return frames


SESSIONS = {
    "truklog_M0 (June, actual-failed-charges)":
        g("projects/vtrux/logs/actual-failed-charges/truklog_M0_T*.log"),
    "truklog_M2 (June, other-logs lowercase)":
        [p for p in g("projects/vtrux/logs/other-logs/truklog_M2_T*.log") if "truklog_M2" in os.path.basename(p)],
    "TRUKLOG_M2 (other-logs uppercase)":
        [p for p in g("projects/vtrux/logs/other-logs/TRUKLOG_M2_T*.log") if "TRUKLOG_M2" in os.path.basename(p)],
    "another_M0":
        g("projects/vtrux/logs/after-battery-swap-charges/another_M0_T*.log"),
    "charge_M0":
        g("projects/vtrux/logs/after-battery-swap-charges/charge_M0_T*.log"),
    "vtrux_charge_M1":
        g("projects/vtrux/logs/vtrux_charge_M1_T*.log"),
    "debuglog_M4_T20": g("projects/vtrux/logs/debuglog_M4_T20.log"),
    "debuglog_M5 (chunks only)":
        g("projects/vtrux/logs/debuglog_M5_T*.log"),
    "vtrux_20260425_102730":
        g("../../CANLogs/VtruxLogs/vtrux_20260425_102730_T*.log"),
    "vtrux_20260513_180408":
        g("../../CANLogs/VtruxLogs/vtrux_20260513_180408_T*.log"),
    "vtrux_20260618_002023":
        g("../../CANLogs/VtruxLogs/vtrux_20260618_002023_T*.log"),
    "vtrux_20260714_151732":
        g("../../CANLogs/VtruxLogs/vtrux_20260714_151732_T*.log"),
    "vtrux_20260714_161319":
        g("../../CANLogs/VtruxLogs/vtrux_20260714_161319_T*.log"),
    "rainychargedebug4": g("projects/vtrux/logs/rainychargedebug4.log"),
    "vtrux_980charge": g("projects/vtrux/logs/vtrux_980charge.log"),
    "vtrux_newcharger": g("projects/vtrux/logs/vtrux_newcharger.log"),
    "vtrux_newcharger_part2": g("projects/vtrux/logs/vtrux_newcharger_part2.log"),
    "vtrux_partstruck_chargeagain2": g("projects/vtrux/logs/vtrux_partstruck_chargeagain2.log"),
    "vtrux_partstruck_evapfuseexperiment": g("projects/vtrux/logs/vtrux_partstruck_evapfuseexperiment.log"),
    "vtrux_partstruck_testdrive_part2": g("projects/vtrux/logs/vtrux_partstruck_testdrive_part2.log"),
    "vtrux_partstruck_testdrive_part4": g("projects/vtrux/logs/vtrux_partstruck_testdrive_part4.log"),
    "vtruxchargeafterafterucscexport2": g("projects/vtrux/logs/vtruxchargeafterafterucscexport2.log"),
    "vtruxchargeafteroverheattest-32a": g("projects/vtrux/logs/vtruxchargeafteroverheattest-32asetpoint.log"),
    "vtruxchargeafterscottsvalley": g("projects/vtrux/logs/vtruxchargeafterscottsvalley.log"),
    "vtruxextensioncabletest": g("projects/vtrux/logs/vtruxextensioncabletest.log"),
    "vtruxinterlocktest": g("projects/vtrux/logs/vtruxinterlocktest.log"),
    "vtruxisolationtestrecovery": g("projects/vtrux/logs/vtruxisolationtestrecovery.log"),
    "vtruxunpluggingchargehandle": g("projects/vtrux/logs/vtruxunpluggingchargehandleendofcharge.log"),
    "vtruxunplugpumpthenhvbatterylv": g("projects/vtrux/logs/vtruxunplugpumpthenhvbatterylvconnector.log"),
}

GAP_LIMIT = 5.0

print("%-42s %-6s %-22s %9s %7s %-6s %s" %
      ("session", "kind", "transition", "gap_s", "x-file", "B1", "verdict"))
print("-" * 118)
for name, paths in SESSIONS.items():
    frames = session_frames(paths)
    if not frames:
        print("%-42s NO FRAMES (files: %d)" % (name, len(paths)))
        continue
    prev = None              # (t, path, epo, alarm, b1)
    for t, path, d in frames:
        if len(d) < 2:
            continue
        epo = (d[0] >> 1) & 1
        al = (d[1] >> 6) & 3
        b1 = d[1]
        if prev is not None:
            gap = t - prev[0]
            xfile = "yes" if path != prev[1] else ""
            events = []
            if prev[2] == 1 and epo == 0:
                events.append(("EPO", "1 -> 0"))
            if prev[3] == 3 and al < 3:
                events.append(("ALARM", "TYPE3 -> %s" % ALARM[al]))
            for kind, desc in events:
                verdict = "IN-COVERAGE" if gap < GAP_LIMIT else "ACROSS-GAP (unattributable)"
                print("%-42s %-6s %-22s %9.2f %7s 0x%02X   %s" %
                      (name[:42], kind, desc, gap, xfile, b1, verdict))
        prev = (t, path, epo, al, b1)
