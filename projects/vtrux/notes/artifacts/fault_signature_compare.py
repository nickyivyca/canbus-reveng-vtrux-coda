"""Cross-fault signature comparison for Vtrux BMS/HV fault modes.

Extracts a common set of discriminator signals around each fault event so that
different fault modes can be laid side by side:

  0x440  bcm_mainc_stat   contactor state machine (which step it aborts from)
  0x410  B0 bit3          interlock loop status   (1 = closed)
         B0 bit1          fault-only bit
         B1[7:6]          alarm type (NONE/TYPE1/TYPE2/TYPE3)
         B0 bit1 (epo)    emergency power off
  0x420  B3               iso_r, BMS periodic isolation test result
  0x430  B4/B5            lvbat (12V rail)
  0x482  B1|(B2&F)<<8     HV DC bus volts

For each log it locates the fault instant (first EPO assert, or first entry to a
FAILED_*/ALL_OPEN_SHUTDOWN contactor state) and dumps a window around it.

BUSMASTER logs are pre-filtered by ID with a raw text scan so multi-hundred-MB
files do not have to be fully parsed.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/fault_signature_compare.py [--only NAME]
"""
import sys
sys.path.insert(0, ".")

import os
import re

WATCH = {0x410, 0x420, 0x430, 0x440, 0x482, 0x400, 0x592, 0x054, 0x053}

MAINC_STAT_16 = [
    "ALL_OPEN", "FAILED_MAINP_OR_R_WELD", "CLOSE_MAINR", "FAILED_MAINR_OPEN",
    "FAILED_MAINN_WELD", "CLOSE_MAINN", "FAILED_MAINN_OPEN", "WAIT_PRECHARGE",
    "CLOSE_MAINP", "OPEN_MAINR", "FAILED_MAINP_OPEN", "MAIN_PN_CLOSED_DRIVE",
    "MAIN_P_CLOSED_CHARGE", "SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN", "(idx15)",
]
ALARM = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}

# name -> (path, note)
LOGS = {
    "truck3_1_welded_mainn":  ("projects/vtrux/logs/truck3-logs/truck3-canlog.log",
                             "truck3-round 1 - welded MAINN contactor (CONFIRMED)"),
    "truck3_2_bad_precharge": ("projects/vtrux/logs/truck3-logs/truck3log2.log",
                             "truck3-round 2 - bad precharge contactor (CONFIRMED)"),
    "truck3_3_bms_powerloss": ("projects/vtrux/logs/truck3-logs/truck3-truck4-keyoff-on-off-on.log",
                             "truck3-round 3 - loose connector, BMS master feed (CONFIRMED)"),
    "isolation_fault":      ("projects/vtrux/logs/vtruxisolationtest.log",
                             "Deliberate isolation fault - 1kOhm HV-to-chassis (CONFIRMED)"),
    "interlock_fault":      ("projects/vtrux/logs/vtruxinterlocktest.log",
                             "Deliberate interlock fault - HVAC then HVD pull (CONFIRMED)"),
    "precharge_fail":       ("projects/vtrux/logs/debuglog_M4_T20.log",
                             "Intermittent precharge fail at CLOSE_MAINN, main-orig battery"),
    "mystery_2025":         ("projects/vtrux/logs/full-charge-then-fail.log",
                             "Summer 2025 mystery - full charge then fail, root cause UNKNOWN"),
}

BM_RE = re.compile(
    r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
CD_RE = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)$")


def iter_watch(path):
    """Yield (t, arb_id, data) for WATCH ids only, straight from raw text."""
    t0 = None
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line.startswith("*"):
                continue
            m = BM_RE.match(line)
            if m:
                hh, mm, ss, ticks, idhex, dlc, rest = m.groups()
                aid = int(idhex, 16)
                if aid not in WATCH:
                    continue
                # BUSMASTER TTTT = 10 kHz ticks (0.1 ms), NOT milliseconds
                t = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ticks) / 10000.0
                data = bytes(int(b, 16) for b in rest.split())
            else:
                m = CD_RE.match(line.strip())
                if not m:
                    continue
                ep, idhex, payload = m.groups()
                aid = int(idhex, 16)
                if aid not in WATCH:
                    continue
                t = float(ep)
                data = bytes.fromhex(payload) if payload else b""
            if t0 is None:
                t0 = t
            yield t - t0, aid, data


def decode(aid, d):
    """Return dict of discriminator fields present in this frame."""
    out = {}
    if aid == 0x410 and len(d) >= 8:
        out["interlock"] = (d[0] >> 3) & 1
        out["epo"] = (d[0] >> 1) & 1
        out["b0"] = d[0]
        out["b1"] = d[1]
        out["alarm"] = ALARM[(d[1] >> 6) & 3]
        out["vbat"] = (d[7] | ((d[6] & 0xF) << 8)) * 0.25
    elif aid == 0x420 and len(d) >= 4:
        out["iso_r"] = d[3]
    elif aid == 0x430 and len(d) >= 6:
        out["lvbat"] = None
    elif aid == 0x440 and len(d) >= 1:
        out["mainc"] = (d[0] >> 2) & 0xF
    elif aid == 0x482 and len(d) >= 3:
        out["hv"] = d[1] | ((d[2] & 0x0F) << 8)
    elif aid == 0x592 and len(d) >= 1:
        out["ign"] = (d[0] >> 4) & 1
        out["export"] = (d[0] >> 2) & 1
    elif aid == 0x054 and len(d) >= 2:
        out["rpm"] = (d[0] | (d[1] << 8)) - 32767
    return out


FAULT_STATES = {1, 3, 4, 6, 10, 13, 14}


def analyse(name, path, note, window=3.0):
    print("=" * 100)
    print("  %-22s %s" % (name, note))
    print("  %s" % path)
    print("=" * 100)
    if not os.path.exists(path):
        print("  FILE NOT FOUND\n")
        return None

    rows = []
    fault_t = None
    fault_why = None
    prev_epo = None
    prev_mainc = None
    master_seen = False

    for t, aid, d in iter_watch(path):
        f = decode(aid, d)
        if not f:
            continue
        if aid in (0x410, 0x420, 0x430, 0x440):
            master_seen = True
        rows.append((t, aid, f))
        if fault_t is None:
            if "epo" in f and prev_epo == 0 and f["epo"] == 1:
                fault_t, fault_why = t, "EPO asserted"
            elif "mainc" in f and prev_mainc is not None \
                    and f["mainc"] in FAULT_STATES and prev_mainc not in FAULT_STATES:
                fault_t, fault_why = t, "contactor -> %s" % MAINC_STAT_16[f["mainc"]]
        if "epo" in f:
            prev_epo = f["epo"]
        if "mainc" in f:
            prev_mainc = f["mainc"]

    if not master_seen:
        print("  *** BMS MASTER NEVER TRANSMITTED -- no fault event to locate ***")
        print("      This IS the signature: the fault is the absence of the module.\n")
        return {"name": name, "kind": "master_absent"}

    if fault_t is None:
        print("  no EPO / contactor-fault transition found\n")
        return None

    print("  FAULT INSTANT: t=%.3fs   (%s)" % (fault_t, fault_why))
    print()
    print("  %-9s %-8s %s" % ("t-tf", "id", "fields"))
    print("  " + "-" * 92)
    shown = 0
    last = {}
    for t, aid, f in rows:
        if not (fault_t - window <= t <= fault_t + window):
            continue
        key = (aid, tuple(sorted(f.items(), key=lambda kv: kv[0])))
        if last.get(aid) == f:
            continue
        last[aid] = dict(f)
        desc = []
        if "mainc" in f:
            desc.append("mainc=%s" % MAINC_STAT_16[f["mainc"]])
        for k in ("interlock", "epo", "alarm", "iso_r", "hv", "vbat", "rpm", "ign", "export"):
            if k in f and f[k] is not None:
                desc.append("%s=%s" % (k, f[k]))
        if "b0" in f:
            desc.append("B0=0x%02X B1=0x%02X" % (f["b0"], f["b1"]))
        if not desc:
            continue
        print("  %+9.3f 0x%03X   %s" % (t - fault_t, aid, "  ".join(desc)))
        shown += 1
        if shown > 70:
            print("  ... truncated")
            break
    print()
    return {"name": name, "kind": "fault", "t": fault_t, "why": fault_why}


if __name__ == "__main__":
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    for name, (path, note) in LOGS.items():
        if only and only != name:
            continue
        analyse(name, path, note)


# ---------------------------------------------------------------------------
# Phase 2: TYPE1 precursor deep-dive. The 2025 mystery raised TYPE1 ~10s before
# EPO. Find every alarm-state transition in a log and report what else moved.
# ---------------------------------------------------------------------------
def alarm_timeline(name, path, note):
    print("=" * 100)
    print("  ALARM TIMELINE  %-18s %s" % (name, note))
    print("=" * 100)
    if not os.path.exists(path):
        print("  FILE NOT FOUND\n")
        return
    prev = {}
    events = []
    for t, aid, d in iter_watch(path):
        f = decode(aid, d)
        if not f:
            continue
        if aid == 0x410:
            cur = (f["alarm"], f["epo"], f["interlock"], f["b0"], f["b1"])
            if prev.get("410") != cur:
                if prev.get("410") is None or cur[0] != prev["410"][0] \
                        or cur[1] != prev["410"][1] or cur[2] != prev["410"][2]:
                    events.append((t, "0x410", "alarm=%-5s epo=%d interlock=%d B0=0x%02X B1=0x%02X"
                                   % (f["alarm"], f["epo"], f["interlock"], f["b0"], f["b1"])))
                prev["410"] = cur
        elif aid == 0x440:
            if prev.get("440") != f["mainc"]:
                events.append((t, "0x440", "mainc=%s" % MAINC_STAT_16[f["mainc"]]))
                prev["440"] = f["mainc"]
        elif aid == 0x420:
            pv = prev.get("420")
            if pv is None or abs(f["iso_r"] - pv) >= 2:
                events.append((t, "0x420", "iso_r=%d" % f["iso_r"]))
                prev["420"] = f["iso_r"]
    for t, src, msg in events:
        print("    t=%10.3f  %-7s %s" % (t, src, msg))
    print()


if "--alarms" in sys.argv:
    tgt = sys.argv[sys.argv.index("--alarms") + 1]
    alarm_timeline(tgt, LOGS[tgt][0], LOGS[tgt][1])
