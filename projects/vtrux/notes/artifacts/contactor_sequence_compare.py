"""Unified contactor-sequence comparison across every known start outcome.

Finds every precharge/contactor-close attempt in each log and prints the full
state-machine walk with per-step dwell times, plus the 12V rail, HV bus rails and
pack state at each step. Puts healthy starts, Truck 3's three failure modes, and the
main-orig precharge failures side by side.

Signals (all decodes taken from tools/diagnose_vtrux.py -- do not hand-roll):
  0x440 B0[5:2]  bcm_mainc_stat        contactor state machine
  0x440 B4/B5/B6 vbus_pos / vbus_neg   HV rails, 0.25 V/count
  0x430 B7       lvbat                 12V rail, 0.1 V/count
  0x430          cell_vmax/vmin/tmax   pack state
  0x410          alarm / epo / interlock / vbat
  0x482 B1,B2    HV DC bus volts

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/contactor_sequence_compare.py
  py -3.12 projects/vtrux/notes/artifacts/contactor_sequence_compare.py --only healthy_main
"""
import sys
sys.path.insert(0, ".")

import os
import re

MAINC_STAT_16 = [
    "ALL_OPEN", "FAILED_MAINP_OR_R_WELD", "CLOSE_MAINR", "FAILED_MAINR_OPEN",
    "FAILED_MAINN_WELD", "CLOSE_MAINN", "FAILED_MAINN_OPEN", "WAIT_PRECHARGE",
    "CLOSE_MAINP", "OPEN_MAINR", "FAILED_MAINP_OPEN", "MAIN_PN_CLOSED_DRIVE",
    "MAIN_P_CLOSED_CHARGE", "SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN", "(idx15)",
]
ALARM = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}
GOOD_END = {11, 12}                      # MAIN_PN_CLOSED_DRIVE / MAIN_P_CLOSED_CHARGE
BAD_END = {1, 3, 4, 6, 10, 13, 14}
START_STATES = {2}                       # CLOSE_MAINR begins an attempt

WATCH = {0x410, 0x420, 0x430, 0x440, 0x482, 0x592}

LOGS = {
    # --- healthy references -------------------------------------------------
    "healthy_main_drive":   ("projects/vtrux/logs/generator-on-then-off.log",
                             "HEALTHY - main truck, key-on drive start"),
    "healthy_main_export":  ("projects/vtrux/logs/vtruxexportafterucsc.log",
                             "HEALTHY - main truck, export start"),
    "healthy_truck3_export": ("projects/vtrux/logs/truck3-logs/truck3-6_key_and_export.txt",
                             "HEALTHY - Truck 3, export start (post-repair, working)"),
    # --- Truck 3's failures ---------------------------------------------------
    "truck3_1_welded_mainn":  ("projects/vtrux/logs/truck3-logs/truck3-canlog.log",
                             "truck3-FAIL 1 - welded MAINN contactor"),
    "truck3_2_bad_precharge": ("projects/vtrux/logs/truck3-logs/truck3log2.log",
                             "truck3-FAIL 2 - bad precharge contactor"),
    "truck3_3_bms_absent":    ("projects/vtrux/logs/truck3-logs/truck3-truck4-keyoff-on-off-on.log",
                             "truck3-FAIL 3 - BMS master absent (loose connector)"),
    # --- main-orig pack precharge failures -----------------------------------
    "mainorig_M4_T20":      ("projects/vtrux/logs/debuglog_M4_T20.log",
                             "MAIN-ORIG FAIL - main truck 2025-08-21, CLOSE_MAINN abort"),
    "mainorig_partstruck1": ("projects/vtrux/logs/vtrux_partstruck_chargeagain2.log",
                             "MAIN-ORIG FAIL - parts truck 2026-04-25"),
    "mainorig_partstruck2": ("projects/vtrux/logs/vtrux_partstruck_evapfuseexperiment.log",
                             "MAIN-ORIG FAIL - parts truck 2026-05-03"),
    "mainorig_partstruck3": ("projects/vtrux/logs/vtrux_partstruck_chargeagain.log",
                             "MAIN-ORIG - parts truck 2026-04-25 (first attempt)"),
    "mainorig_reconnect":   ("projects/vtrux/logs/vtrux__partstruck_reconnect.log",
                             "MAIN-ORIG - parts truck battery reconnect"),
}

BM_RE = re.compile(
    r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
CD_RE = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)$")


def iter_watch(path):
    t0 = None
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line.startswith("*"):
                continue
            m = BM_RE.match(line)
            if m:
                hh, mm, ss, tk, idh, _dlc, rest = m.groups()
                aid = int(idh, 16)
                if aid not in WATCH:
                    continue
                t = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(tk) / 10000.0
                try:
                    data = bytes(int(b, 16) for b in rest.split())
                except ValueError:
                    continue
            else:
                m = CD_RE.match(line.strip())
                if not m:
                    continue
                ep, idh, payload = m.groups()
                aid = int(idh, 16)
                if aid not in WATCH:
                    continue
                t = float(ep)
                try:
                    data = bytes.fromhex(payload) if payload else b""
                except ValueError:
                    continue
            if t0 is None:
                t0 = t
            yield t - t0, aid, data


def analyse(name, path, note):
    print("=" * 108)
    print("  %-24s %s" % (name, note))
    print("=" * 108)
    if not os.path.exists(path):
        print("  FILE NOT FOUND\n")
        return

    st = {"lvbat": None, "vmax": None, "vmin": None, "tmax": None,
          "vbus_p": None, "vbus_n": None, "hv": None, "alarm": None,
          "epo": None, "interlock": None, "vbat": None, "ign": None, "export": None}
    seqs = []
    cur = None
    prev_mainc = None
    saw_master = False

    for t, aid, d in iter_watch(path):
        if aid == 0x430 and len(d) >= 8:
            saw_master = True
            st["lvbat"] = None if d[7] >= 0xFE else round(d[7] * 0.1, 1)
            rvx = d[1] | ((d[0] & 0x1F) << 8)
            rvn = d[3] | ((d[2] & 0x1F) << 8)
            st["vmax"] = None if rvx >= 0x1FFE else rvx
            st["vmin"] = None if rvn >= 0x1FFE else rvn
            st["tmax"] = None if d[4] >= 0xFE else round(d[4] * 0.5 - 40.0, 1)
        elif aid == 0x410 and len(d) >= 8:
            saw_master = True
            st["alarm"] = ALARM[(d[1] >> 6) & 3]
            st["epo"] = (d[0] >> 1) & 1
            st["interlock"] = (d[0] >> 3) & 1
            rv = d[7] | ((d[6] & 0xF) << 8)
            st["vbat"] = None if rv >= 0xFFE else rv * 0.25
        elif aid == 0x482 and len(d) >= 3:
            st["hv"] = d[1] | ((d[2] & 0x0F) << 8)
        elif aid == 0x592 and len(d) >= 1:
            st["ign"] = (d[0] >> 4) & 1
            st["export"] = (d[0] >> 2) & 1
        elif aid == 0x440 and len(d) >= 7:
            saw_master = True
            rp = (d[4] << 4) | (d[5] >> 4)
            rn = d[6] | ((d[5] & 0xF) << 8)
            st["vbus_p"] = None if rp >= 0xFFE else round(rp * 0.25, 1)
            st["vbus_n"] = None if rn >= 0xFFE else round(rn * 0.25 - 500.0, 1)
            m = (d[0] >> 2) & 0xF
            if m != prev_mainc:
                if m in START_STATES and cur is None:
                    cur = {"t0": t, "steps": [], "lv_min": st["lvbat"]}
                if cur is not None:
                    cur["steps"].append((t, m, dict(st)))
                    if st["lvbat"] is not None:
                        cur["lv_min"] = min(cur["lv_min"] or 99, st["lvbat"])
                    if m in GOOD_END or m in BAD_END:
                        cur["end"] = m
                        seqs.append(cur)
                        cur = None
                prev_mainc = m
        # track 12V minimum inside an active sequence
        if cur is not None and st["lvbat"] is not None:
            cur["lv_min"] = min(cur["lv_min"] or 99, st["lvbat"])

    if not saw_master:
        print("  *** BMS MASTER NEVER TRANSMITTED -- no contactor sequence exists ***")
        print("      Failure mode: module absent. Nothing to compare at this level.\n")
        return
    if not seqs:
        print("  no CLOSE_MAINR sequence found in this log\n")
        return

    for n, s in enumerate(seqs, 1):
        end = s.get("end")
        verdict = "SUCCESS" if end in GOOD_END else "FAIL"
        print("  --- attempt %d --  %s  (ends %s)   12V min during attempt: %sV"
              % (n, verdict, MAINC_STAT_16[end], s["lv_min"]))
        print("      %-8s %-24s %-7s %-9s %-9s %-8s %s"
              % ("dt(ms)", "state", "12V", "vbus_p", "vbus_n", "HVbus", "pack / alarm"))
        base = s["t0"]
        for i, (t, m, ss) in enumerate(s["steps"]):
            dwell = ""
            if i + 1 < len(s["steps"]):
                dwell = "%.0f" % ((s["steps"][i + 1][0] - t) * 1000)
            pack = ""
            if ss["vmax"] is not None:
                pack = "vmax=%dmV vmin=%dmV" % (ss["vmax"], ss["vmin"])
            print("      %+8.0f %-24s %-7s %-9s %-9s %-8s %s %s [dwell %s ms]"
                  % ((t - base) * 1000, MAINC_STAT_16[m],
                     ss["lvbat"], ss["vbus_p"], ss["vbus_n"], ss["hv"],
                     pack, ss["alarm"], dwell))
        print()
    print()


if __name__ == "__main__":
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    for nm, (p, note) in LOGS.items():
        if only and only != nm:
            continue
        analyse(nm, p, note)
