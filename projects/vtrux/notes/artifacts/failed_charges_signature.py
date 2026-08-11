"""
Scan "actual-failed-charges" logs for failure signatures, using the framework's
session grouping logic to correctly identify separate charge sessions.

For each session, merges all constituent chunks and reports state transitions for:
  0x410 (BMS alarm / EPO / HVIL / charge contactor)
  0x440 (contactor sequence)
  0x592 (ignition / EVSE switch)
  0x3FE (charger state -- significant changes only, suppresses 1<->2 oscillation)

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/failed_charges_signature.py
"""

import sys
sys.path.insert(0, ".")

from canre.utils.sessions import list_session_files
from canre.utils.merge import merge_files

from pathlib import Path
LOG_DIR = Path("projects/vtrux/Bel-Inverter/actual-failed-charges")

ALARM_STRINGS = ["NONE", "TYPE1", "TYPE2", "TYPE3", "Invalid"]
MAINC_STAT = [
    "ALL_OPEN", "FAILED_MAINP_OR_R_WELD", "CLOSE_MAINR", "FAILED_MAINR_OPEN",
    "FAILED_MAINN_WELD", "CLOSE_MAINN", "FAILED_MAINN_OPEN", "WAIT_PRECHARGE",
    "CLOSE_MAINP", "OPEN_MAINR", "FAILED_MAINP_OPEN", "MAIN_PN_CLOSED_DRIVE",
    "MAIN_P_CLOSED_CHARGE", "SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN", "(idx15)",
]
CHGC_STAT = ["OPEN", "CLOSED", "HIGH", "LOW"]


def analyze_session(session_name, paths):
    print(f"\n{'='*70}")
    print(f"Session: {session_name}  ({len(paths)} file(s))")
    for p in paths:
        print(f"  {p.name}")
    print()

    prev = {}
    last_3fe_in_range = None
    had_any = False

    def changed(key, val):
        if prev.get(key) != val:
            prev[key] = val
            return True
        return False

    for frame in merge_files(paths):
        t = frame.timestamp
        cid = frame.arbitration_id
        data = frame.data

        if cid == 0x410 and len(data) >= 2:
            B0, B1 = data[0], data[1]
            alarm = ALARM_STRINGS[(B1 >> 6) & 3]
            chgc  = CHGC_STAT[(B0 >> 6) & 3]
            epo   = (B0 >> 1) & 1   # bit 1
            hvil  = (B0 >> 3) & 1   # bit 3
            ready = B0 & 1
            state = (alarm, chgc, epo, hvil, ready)
            if changed("0x410", state):
                print(f"  t={t:8.2f}  0x410  alarm={alarm:<6} chgc={chgc:<6} epo={epo} hvil={hvil} ready={ready}  [B0={B0:02X} B1={B1:02X}]")
                had_any = True

        elif cid == 0x440 and len(data) >= 1:
            B0 = data[0]
            idx = (B0 >> 2) & 0xF
            mainc = MAINC_STAT[idx]
            if changed("0x440", mainc):
                print(f"  t={t:8.2f}  0x440  mainc_stat={mainc}  [B0={B0:02X}]")
                had_any = True

        elif cid == 0x592 and len(data) >= 1:
            B0 = data[0]
            ign  = (B0 >> 4) & 1
            evse = (B0 >> 1) & 1
            exp  = (B0 >> 2) & 1
            state = (ign, evse, exp)
            if changed("0x592", state):
                print(f"  t={t:8.2f}  0x592  ignition={ign} evse_sw={evse} export={exp}  [B0={B0:02X}]")
                had_any = True

        elif cid == 0x3FE and len(data) >= 1:
            sv = data[0]
            in_range = sv in (1, 2)
            if not in_range:
                if last_3fe_in_range != sv:
                    last_3fe_in_range = sv
                    print(f"  t={t:8.2f}  0x3FE  charger_state={sv}  [B0={sv:02X}]")
                    had_any = True
            else:
                if last_3fe_in_range not in (1, 2, None):
                    last_3fe_in_range = sv
                    print(f"  t={t:8.2f}  0x3FE  charger_state={sv} (returned to 1/2 range)")
                    had_any = True

    if not had_any:
        print("  (no state changes on monitored signals -- likely GM bus only)")


sessions, standalones = list_session_files(LOG_DIR)

# Process M-grouped sessions in sorted order
for name in sorted(sessions.keys()):
    analyze_session(name, sessions[name])

# Process any standalone files
for p in standalones:
    analyze_session(p.stem, [p])
